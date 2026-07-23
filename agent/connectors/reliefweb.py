import re
import urllib.parse

from agent.connectors.base import JsonConnector
from agent.intelligence.models import ConnectorBatch, SourceItem
from agent.intelligence.store import utc_now


class ReliefWebConnector(JsonConnector):
    source_id = "reliefweb"
    name = "ReliefWeb"
    kind = "humanitarian"
    base_url = "https://api.reliefweb.int/v2/reports"
    credibility = 0.9
    poll_seconds = 900

    def __init__(self, appname="", **kwargs):
        super().__init__(**kwargs)
        self.appname = str(appname or "").strip()
        self.enabled = self.enabled and bool(self.appname)

    def poll(self, cursor=None):
        if not self.enabled:
            return ConnectorBatch(cursor=cursor or {})

        params = urllib.parse.urlencode(
            {
                "appname": self.appname,
                "limit": self.max_items,
                "profile": "full",
                "preset": "latest"
            }
        )
        payload = self.fetch_json(f"{self.base_url}?{params}")
        items = []

        for record in payload.get("data", [])[:self.max_items]:
            fields = record.get("fields") or {}
            external_id = str(record.get("id") or fields.get("id") or "")
            title = fields.get("title") or "ReliefWeb report"
            url = fields.get("url") or fields.get("url_alias") or ""

            if isinstance(url, dict):
                url = url.get("href") or url.get("url") or ""

            if url.startswith("/"):
                url = "https://reliefweb.int" + url

            if not external_id or not url:
                continue

            body = fields.get("body") or fields.get("description") or ""
            if isinstance(body, dict):
                body = body.get("value") or ""

            date = fields.get("date") or {}
            published_at = (
                date.get("original")
                or date.get("created")
                or fields.get("date.created")
            )
            countries = _names(fields.get("country"))
            disasters = _names(fields.get("disaster"))
            sources = _names(fields.get("source"))
            summary = re.sub(r"<[^>]+>", " ", str(body))

            items.append(
                SourceItem(
                    external_id=external_id,
                    title=title,
                    url=url,
                    summary=summary[:2000],
                    content=summary[:20_000],
                    published_at=published_at,
                    category="humanitarian",
                    metadata={
                        "countries": countries,
                        "disasters": disasters,
                        "reporting_sources": sources,
                        "format": _names(fields.get("format"))
                    }
                )
            )

        return ConnectorBatch(
            items=items,
            cursor={
                "retrieved_at": utc_now(),
                "newest_external_id": items[0].external_id if items else None
            }
        )


def _names(value):
    if not value:
        return []

    if not isinstance(value, list):
        value = [value]

    names = []

    for item in value:
        if isinstance(item, dict):
            name = item.get("name") or item.get("shortname") or item.get("id")
        else:
            name = item

        if name not in (None, ""):
            names.append(str(name))

    return names
