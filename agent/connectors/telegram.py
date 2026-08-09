import asyncio
import hashlib
import os
import re
from pathlib import Path

from agent.intelligence.models import ConnectorBatch, SourceItem
from agent.intelligence.store import utc_now


class TelegramConnector:
    source_id = "telegram_public"
    name = "Telegram public channels"
    kind = "social_signal"
    base_url = "https://t.me"
    credibility = 0.3
    poll_seconds = 120

    def __init__(
        self,
        api_id="",
        api_hash="",
        session_path="agent/telegram_entity",
        channels=(),
        messages_per_channel=50,
        deletion_scan_size=100,
        media_enabled=False,
        media_directory="agent/private/intelligence_media",
        media_max_bytes=10_000_000,
        media_max_per_cycle=3,
        poll_seconds=120,
        timeout=30,
        gateway=None,
        enabled=False
    ):
        self.api_id = str(api_id or "").strip()
        self.api_hash = str(api_hash or "").strip()
        self.session_path = Path(session_path)
        self.channels = tuple(
            channel for channel in (_channel_name(value) for value in channels)
            if channel
        )
        self.messages_per_channel = max(1, min(200, int(messages_per_channel)))
        self.deletion_scan_size = max(1, min(500, int(deletion_scan_size)))
        self.media_enabled = bool(media_enabled)
        self.media_directory = Path(media_directory)
        self.media_max_bytes = max(1, min(100_000_000, int(media_max_bytes)))
        self.media_max_per_cycle = max(1, min(25, int(media_max_per_cycle)))
        self.timeout = max(1, int(timeout))
        self.poll_seconds = max(60, int(poll_seconds))
        self.gateway = gateway
        self.enabled = bool(
            enabled and self.api_id and self.api_hash and self.channels
        )

    def poll(self, cursor=None):
        cursor = cursor or {}
        if not self.enabled:
            return ConnectorBatch(cursor=cursor)
        gateway = self.gateway or TelethonGateway(
            api_id=self.api_id,
            api_hash=self.api_hash,
            session_path=self.session_path,
            timeout=self.timeout,
            media_enabled=self.media_enabled,
            media_directory=self.media_directory,
            media_max_bytes=self.media_max_bytes,
            media_max_per_cycle=self.media_max_per_cycle,
        )
        previous = cursor.get("known_message_ids") or {}
        result = gateway.collect(
            self.channels,
            previous,
            self.messages_per_channel
        )
        items = []
        known = {}
        for channel in result:
            channel_id = str(channel["id"])
            username = channel["username"]
            known[channel_id] = [
                int(value) for value in channel.get("message_ids", [])
            ][:self.deletion_scan_size]
            for message in channel.get("messages", []):
                items.append(_message_item(channel, message))
            for message_id in channel.get("deleted_ids", []):
                items.append(_deleted_item(channel, int(message_id)))
        return ConnectorBatch(items=items, cursor={
            "retrieved_at": utc_now(),
            "known_message_ids": known
        })


class TelethonGateway:
    def __init__(self, api_id, api_hash, session_path, timeout=30,
                 media_enabled=False,
                 media_directory="agent/private/intelligence_media",
                 media_max_bytes=10_000_000, media_max_per_cycle=3):
        self.api_id = int(api_id)
        self.api_hash = api_hash
        self.session_path = Path(session_path)
        self.timeout = timeout
        self.media_enabled = bool(media_enabled)
        self.media_directory = Path(media_directory)
        self.media_max_bytes = max(1, min(100_000_000, int(media_max_bytes)))
        self.media_max_per_cycle = max(1, min(25, int(media_max_per_cycle)))

    def collect(self, channels, previous, limit):
        return asyncio.run(self._collect(channels, previous, limit))

    async def _collect(self, channels, previous, limit):
        TelegramClient, Channel = _telethon_types()
        self.session_path.parent.mkdir(parents=True, exist_ok=True)
        client = TelegramClient(
            str(self.session_path), self.api_id, self.api_hash,
            timeout=self.timeout, receive_updates=False,
            device_model="Entity read-only intelligence",
            app_version="0.4"
        )
        await client.connect()
        try:
            if not await client.is_user_authorized():
                raise RuntimeError(
                    "Telegram is not authorized. Run: "
                    ".venv/bin/python -m agent.intelligence.telegram_auth authorize"
                )
            collected = []
            media_downloads = 0
            for selector in channels:
                entity = await client.get_entity(selector)
                if not isinstance(entity, Channel) or not entity.broadcast:
                    raise RuntimeError(
                        f"Telegram target {selector!r} is not a broadcast channel."
                    )
                username = str(entity.username or "").strip()
                if not username:
                    raise RuntimeError(
                        f"Telegram channel {selector!r} is not public."
                    )
                channel_id = str(entity.id)
                prior_ids = [
                    int(value) for value in previous.get(channel_id, [])
                ]
                present_ids = set()
                if prior_ids:
                    prior_messages = await client.get_messages(
                        entity, ids=prior_ids
                    )
                    present_ids = {
                        message.id for message in prior_messages if message
                    }
                messages = []
                async for message in client.iter_messages(entity, limit=limit):
                    if not message or not message.id:
                        continue
                    record = _message_record(message)
                    if (
                        self.media_enabled and message.media
                        and media_downloads < self.media_max_per_cycle
                    ):
                        downloaded = await self._download_media(client, message, record)
                        if downloaded:
                            record.update(downloaded)
                            media_downloads += 1
                    messages.append(record)
                    present_ids.add(message.id)
                message_ids = [message["id"] for message in messages]
                collected.append({
                    "id": entity.id,
                    "username": username,
                    "title": str(getattr(entity, "title", "") or username),
                    "messages": messages,
                    "message_ids": message_ids,
                    "deleted_ids": [
                        message_id for message_id in prior_ids
                        if message_id not in present_ids
                    ]
                })
            return collected
        finally:
            await client.disconnect()
            _secure_session(self.session_path)

    async def _download_media(self, client, message, record):
        declared = int(record.get("media_size_bytes") or 0)
        if declared and declared > self.media_max_bytes:
            return {"media_derivation_status": "oversized"}
        try:
            payload = await client.download_media(message, file=bytes)
        except Exception:
            return {"media_derivation_status": "download-failed"}
        if not isinstance(payload, bytes) or not payload:
            return {"media_derivation_status": "unavailable"}
        if len(payload) > self.media_max_bytes:
            return {"media_derivation_status": "oversized"}
        digest = hashlib.sha256(payload).hexdigest()
        self.media_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.media_directory, 0o700)
        target = self.media_directory / digest
        try:
            descriptor = os.open(
                target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            )
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
        except FileExistsError:
            pass
        return {
            "media_downloaded": True,
            "media_local_path": str(target),
            "media_sha256": digest,
            "media_size_bytes": len(payload),
            "media_derivation_status": "pending",
        }


def _telethon_types():
    try:
        from telethon import TelegramClient
        from telethon.tl.types import Channel
    except ImportError as exc:
        raise RuntimeError(
            "Telegram support requires Telethon. Install requirements.txt."
        ) from exc
    return TelegramClient, Channel


def _message_record(message):
    forward = getattr(message, "forward", None)
    media = getattr(message, "media", None)
    forward_peer = getattr(forward, "from_id", None) if forward else None
    document = getattr(media, "document", None) if media else None
    attributes = list(getattr(document, "attributes", None) or [])
    media_details = _media_details(media, document, attributes)
    return {
        "id": int(message.id),
        "text": str(getattr(message, "raw_text", "") or ""),
        "date": getattr(message, "date", None),
        "edit_date": getattr(message, "edit_date", None),
        "views": getattr(message, "views", None),
        "forwards": getattr(message, "forwards", None),
        "post_author": getattr(message, "post_author", None),
        "grouped_id": getattr(message, "grouped_id", None),
        "reply_to_message_id": getattr(message, "reply_to_msg_id", None),
        "forwarded": bool(forward),
        "forward_date": getattr(forward, "date", None) if forward else None,
        "forward_origin_channel_id": (
            getattr(forward_peer, "channel_id", None) if forward_peer else None
        ),
        "forward_origin_message_id": (
            getattr(forward, "channel_post", None) if forward else None
        ),
        "forward_origin_label": (
            getattr(forward, "from_name", None) if forward else None
        ),
        "forward_origin_post_author": (
            getattr(forward, "post_author", None) if forward else None
        ),
        "media_type": type(media).__name__ if media else None,
        **media_details,
    }


def _message_item(channel, message):
    message_id = int(message["id"])
    username = channel["username"]
    text = re.sub(r"\s+", " ", str(message.get("text") or "")).strip()
    if not text:
        text = f"Media post from @{username}"
    return SourceItem(
        external_id=f"{channel['id']}:{message_id}",
        title=text[:280],
        url=f"https://t.me/{username}/{message_id}",
        summary=text[:2000],
        content=text[:20_000],
        published_at=message.get("date"),
        category=_signal_category(text),
        metadata={
            "visibility": "public",
            "platform": "telegram",
            "channel_id": channel["id"],
            "channel_username": username,
            "channel_title": channel.get("title"),
            "message_id": message_id,
            "edited_at": message.get("edit_date"),
            "views": message.get("views"),
            "forwards": message.get("forwards"),
            "post_author": message.get("post_author"),
            "grouped_id": message.get("grouped_id"),
            "reply_to_message_id": message.get("reply_to_message_id"),
            "forwarded": bool(message.get("forwarded")),
            "forward_date": message.get("forward_date"),
            "forward_origin_channel_id": message.get("forward_origin_channel_id"),
            "forward_origin_message_id": message.get("forward_origin_message_id"),
            "forward_origin_label": message.get("forward_origin_label"),
            "forward_origin_post_author": message.get("forward_origin_post_author"),
            "media_type": message.get("media_type"),
            "media_mime_type": message.get("media_mime_type"),
            "media_size_bytes": message.get("media_size_bytes"),
            "media_duration_seconds": message.get("media_duration_seconds"),
            "media_width": message.get("media_width"),
            "media_height": message.get("media_height"),
            "media_file_name": message.get("media_file_name"),
            "media_downloaded": bool(message.get("media_downloaded")),
            "media_local_path": message.get("media_local_path"),
            "media_sha256": message.get("media_sha256"),
            "media_derivation_status": message.get("media_derivation_status"),
            "translation_status": "pending"
        }
    )


def _media_details(media, document, attributes):
    if not media:
        return {}
    details = {
        "media_mime_type": getattr(document, "mime_type", None),
        "media_size_bytes": getattr(document, "size", None),
    }
    for attribute in attributes:
        for source, target in (
            ("duration", "media_duration_seconds"),
            ("w", "media_width"), ("h", "media_height"),
            ("file_name", "media_file_name"),
        ):
            value = getattr(attribute, source, None)
            if value not in (None, ""):
                details[target] = value
    photo = getattr(media, "photo", None)
    sizes = list(getattr(photo, "sizes", None) or [])
    if sizes:
        largest = max(
            sizes,
            key=lambda value: int(getattr(value, "w", 0) or 0)
                              * int(getattr(value, "h", 0) or 0),
        )
        details.setdefault("media_width", getattr(largest, "w", None))
        details.setdefault("media_height", getattr(largest, "h", None))
    return details


def _deleted_item(channel, message_id):
    username = channel["username"]
    return SourceItem(
        external_id=f"{channel['id']}:{message_id}",
        title=f"Deleted Telegram post from @{username}",
        url=f"https://t.me/{username}/{message_id}",
        summary="This previously captured public post was deleted.",
        category="social-signal",
        metadata={
            "visibility": "public",
            "platform": "telegram",
            "channel_id": channel["id"],
            "channel_username": username,
            "channel_title": channel.get("title"),
            "message_id": message_id,
            "deleted": True,
            "deleted_detected_at": utc_now()
        },
        status="deleted"
    )


def _channel_name(value):
    value = str(value or "").strip().rstrip("/")
    if value.startswith("https://t.me/"):
        value = value.rsplit("/", 1)[-1]
    value = value.lstrip("@")
    return value if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,}", value) else ""


def _signal_category(text):
    normalized = str(text or "").lower()
    categories = (
        ("earthquake", ("earthquake", "aftershock", "seismic", "tsunami")),
        ("wildfires", ("wildfire", "bushfire", "forest fire")),
        ("severe-storms", ("hurricane", "typhoon", "cyclone", "tornado")),
        ("floods", ("flood", "flash flooding")),
        ("disease-outbreak", ("outbreak", "epidemic", "pandemic")),
        ("conflict", ("airstrike", "missile", "invasion", "ceasefire")),
        ("civil-unrest", ("protest", "riot", "coup", "demonstration")),
        ("cybersecurity", ("cyberattack", "ransomware", "data breach")),
        ("finance", ("bank run", "default", "market crash", "capital controls")),
        ("humanitarian", ("refugee", "displacement", "aid convoy"))
    )
    for category, keywords in categories:
        if any(keyword in normalized for keyword in keywords):
            return category
    return "social-signal"


def _secure_session(path):
    for suffix in (".session", ".session-journal"):
        candidate = Path(str(path) + suffix)
        if candidate.exists():
            try:
                os.chmod(candidate, 0o600)
            except OSError:
                pass
