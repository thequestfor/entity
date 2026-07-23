import base64
from pathlib import Path

from agent.connectors.base import JsonConnector
from agent.connectors.mail_common import clean_html, normalize_mail_time, secure_write
from agent.intelligence.models import ConnectorBatch, SourceItem
from agent.intelligence.store import normalize_timestamp, utc_now


class GmailConnector(JsonConnector):
    source_id = "gmail"
    name = "Gmail (private, read-only)"
    kind = "private_mail"
    base_url = "https://gmail.googleapis.com/gmail/v1"
    credibility = 0.45
    poll_seconds = 300
    scopes = ["https://www.googleapis.com/auth/gmail.readonly"]

    def __init__(
        self,
        credentials_path="agent/google_gmail_credentials.json",
        token_path="agent/google_gmail_token.json",
        query="newer_than:7d -in:spam -in:trash",
        store_body=False,
        service=None,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.credentials_path = Path(credentials_path)
        self.token_path = Path(token_path)
        self.query = str(query or "").strip()
        self.store_body = bool(store_body)
        self._service_override = service
        self.enabled = (
            self.enabled
            and (
                service is not None
                or (
                    self.credentials_path.is_file()
                    and self.token_path.is_file()
                )
            )
        )

    @classmethod
    def authorize(cls, credentials_path, token_path):
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError as exc:
            raise RuntimeError("Google OAuth dependencies are missing.") from exc
        credentials_path = Path(credentials_path)
        if not credentials_path.is_file():
            raise RuntimeError(f"Gmail credentials are missing: {credentials_path}")
        try:
            credentials_path.chmod(0o600)
        except OSError:
            pass
        flow = InstalledAppFlow.from_client_secrets_file(
            str(credentials_path),
            cls.scopes
        )
        credentials = flow.run_local_server(port=0)
        secure_write(token_path, credentials.to_json())
        return Path(token_path)

    def poll(self, cursor=None):
        if not self.enabled:
            return ConnectorBatch(cursor=cursor or {})
        service = self._service_override or self._service()
        response = service.users().messages().list(
            userId="me",
            maxResults=self.max_items,
            q=self.query or None,
            includeSpamTrash=False
        ).execute()
        items = []
        for reference in response.get("messages", [])[:self.max_items]:
            message = service.users().messages().get(
                userId="me",
                id=reference["id"],
                format="full" if self.store_body else "metadata",
                metadataHeaders=["Subject", "From", "Date", "Message-ID"]
            ).execute()
            item = self._normalize(message)
            if item:
                items.append(item)
        return ConnectorBatch(
            items=items,
            cursor={
                "retrieved_at": utc_now(),
                "newest_message_id": items[0].external_id if items else None
            }
        )

    def _service(self):
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise RuntimeError("Gmail dependencies are missing.") from exc
        credentials = Credentials.from_authorized_user_file(
            str(self.token_path),
            self.scopes
        )
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
            secure_write(self.token_path, credentials.to_json())
        if not credentials.valid:
            raise RuntimeError("Gmail authorization expired; authorize it again.")
        return build("gmail", "v1", credentials=credentials, cache_discovery=False)

    def _normalize(self, message):
        message_id = str(message.get("id") or "")
        if not message_id:
            return None
        headers = {
            str(header.get("name") or "").lower(): str(header.get("value") or "")
            for header in (message.get("payload") or {}).get("headers", [])
        }
        subject = headers.get("subject") or "(no subject)"
        snippet = clean_html(message.get("snippet"))
        body = _gmail_body(message.get("payload") or {}) if self.store_body else ""
        published_at = normalize_mail_time(headers.get("date"))
        if not published_at and message.get("internalDate"):
            try:
                published_at = normalize_timestamp(int(message["internalDate"]))
            except (TypeError, ValueError):
                published_at = None
        return SourceItem(
            external_id=message_id,
            title=subject,
            url=f"https://mail.google.com/mail/u/0/#inbox/{message_id}",
            summary=snippet[:2000],
            content=body[:20_000],
            published_at=published_at,
            category="private-mail",
            metadata={
                "visibility": "private",
                "mail_provider": "gmail",
                "sender": headers.get("from", ""),
                "internet_message_id": headers.get("message-id", ""),
                "thread_id": message.get("threadId"),
                "labels": message.get("labelIds") or [],
                "body_stored": self.store_body
            }
        )


def _gmail_body(payload):
    plain = []
    rich = []

    def visit(part):
        mime_type = str(part.get("mimeType") or "")
        data = (part.get("body") or {}).get("data")
        if data and mime_type in {"text/plain", "text/html"}:
            try:
                decoded = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
                text = decoded.decode("utf-8", errors="replace")
            except (TypeError, ValueError):
                text = ""
            (plain if mime_type == "text/plain" else rich).append(text)
        for child in part.get("parts") or []:
            visit(child)

    visit(payload)
    return clean_html("\n".join(plain or rich))
