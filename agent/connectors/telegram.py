import asyncio
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
            timeout=self.timeout
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
    def __init__(self, api_id, api_hash, session_path, timeout=30):
        self.api_id = int(api_id)
        self.api_hash = api_hash
        self.session_path = Path(session_path)
        self.timeout = timeout

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
                    messages.append(_message_record(message))
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
        "media_type": type(media).__name__ if media else None
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
            "media_type": message.get("media_type"),
            "media_downloaded": False,
            "translation_status": "pending"
        }
    )


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
