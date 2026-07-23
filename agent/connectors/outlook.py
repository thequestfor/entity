import json
import urllib.parse
import urllib.request
from pathlib import Path

from agent.connectors.base import JsonConnector
from agent.connectors.mail_common import clean_html, secure_write
from agent.intelligence.models import ConnectorBatch, SourceItem
from agent.intelligence.store import utc_now


class OutlookConnector(JsonConnector):
    source_id = "outlook_mail"
    name = "Outlook Mail (private, read-only)"
    kind = "private_mail"
    base_url = "https://graph.microsoft.com/v1.0"
    credibility = 0.45
    poll_seconds = 300
    scopes = ["Mail.Read"]

    def __init__(
        self,
        client_id="",
        tenant="common",
        token_cache_path="agent/outlook_mail_token_cache.json",
        folder="inbox",
        store_body=False,
        fetch_graph=None,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.client_id = str(client_id or "").strip()
        self.tenant = str(tenant or "common").strip()
        self.token_cache_path = Path(token_cache_path)
        self.folder = str(folder or "inbox").strip()
        self.store_body = bool(store_body)
        self._fetch_graph_override = fetch_graph
        self.enabled = (
            self.enabled and bool(self.client_id) and self.token_cache_path.is_file()
        )

    @classmethod
    def authorize(cls, client_id, tenant, token_cache_path):
        app, cache = _msal_app(client_id, tenant, token_cache_path)
        result = app.acquire_token_interactive(scopes=cls.scopes)
        if "access_token" not in result:
            raise RuntimeError(
                "Outlook authorization failed: "
                + str(result.get("error_description") or result.get("error") or "unknown error")
            )
        _save_cache(cache, token_cache_path)
        return Path(token_cache_path)

    def poll(self, cursor=None):
        if not self.enabled:
            return ConnectorBatch(cursor=cursor or {})
        token = self._access_token()
        fields = [
            "id", "internetMessageId", "subject", "receivedDateTime", "from",
            "bodyPreview", "webLink", "isRead", "categories"
        ]
        if self.store_body:
            fields.append("body")
        params = urllib.parse.urlencode({
            "$top": self.max_items,
            "$select": ",".join(fields),
            "$orderby": "receivedDateTime desc"
        })
        folder = urllib.parse.quote(self.folder, safe="")
        url = f"{self.base_url}/me/mailFolders/{folder}/messages?{params}"
        payload = self._fetch_graph(url, token)
        items = [self._normalize(message) for message in payload.get("value", [])]
        items = [item for item in items if item][:self.max_items]
        return ConnectorBatch(
            items=items,
            cursor={
                "retrieved_at": utc_now(),
                "newest_message_id": items[0].external_id if items else None
            }
        )

    def _access_token(self):
        app, cache = _msal_app(self.client_id, self.tenant, self.token_cache_path)
        accounts = app.get_accounts()
        result = app.acquire_token_silent(self.scopes, account=accounts[0]) if accounts else None
        if not result or "access_token" not in result:
            raise RuntimeError("Outlook authorization expired; authorize it again.")
        _save_cache(cache, self.token_cache_path)
        return result["access_token"]

    def _fetch_graph(self, url, token):
        if self._fetch_graph_override:
            return self._fetch_graph_override(url, token)
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
                "User-Agent": "EntityIntelligence/0.2"
            }
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))

    def _normalize(self, message):
        message_id = str(message.get("id") or "")
        if not message_id:
            return None
        sender = ((message.get("from") or {}).get("emailAddress") or {})
        body = message.get("body") or {}
        content = clean_html(body.get("content")) if self.store_body else ""
        return SourceItem(
            external_id=message_id,
            title=message.get("subject") or "(no subject)",
            url=message.get("webLink") or "https://outlook.live.com/mail/0/",
            summary=clean_html(message.get("bodyPreview"))[:2000],
            content=content[:20_000],
            published_at=message.get("receivedDateTime"),
            category="private-mail",
            metadata={
                "visibility": "private",
                "mail_provider": "outlook",
                "sender": sender.get("address") or sender.get("name") or "",
                "internet_message_id": message.get("internetMessageId") or "",
                "is_read": bool(message.get("isRead")),
                "categories": message.get("categories") or [],
                "body_stored": self.store_body
            }
        )


def _msal_app(client_id, tenant, cache_path):
    try:
        import msal
    except ImportError as exc:
        raise RuntimeError("Microsoft MSAL dependency is missing.") from exc
    cache = msal.SerializableTokenCache()
    path = Path(cache_path)
    if path.is_file():
        cache.deserialize(path.read_text(encoding="utf-8"))
    app = msal.PublicClientApplication(
        str(client_id),
        authority=f"https://login.microsoftonline.com/{tenant}",
        token_cache=cache
    )
    return app, cache


def _save_cache(cache, path):
    if cache.has_state_changed:
        secure_write(path, cache.serialize())
