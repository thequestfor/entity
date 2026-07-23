import urllib.parse

from agent.connectors.base import JsonConnector
from agent.connectors.mail_common import clean_html
from agent.intelligence.models import ConnectorBatch, SourceItem
from agent.intelligence.store import utc_now


class WhoOutbreakConnector(JsonConnector):
    source_id = "who_outbreaks"
    name = "WHO Disease Outbreak News"
    kind = "public_health"
    base_url = "https://www.who.int/api/news/diseaseoutbreaknews"
    credibility = 1.0
    poll_seconds = 1800

    def poll(self, cursor=None):
        if not self.enabled:
            return ConnectorBatch(cursor=cursor or {})
        query = urllib.parse.urlencode({
            "$top": self.max_items,
            "$orderby": "PublicationDateAndTime desc"
        })
        payload = self.fetch_json(f"{self.base_url}?{query}")
        items = []
        for entry in payload.get("value", payload.get("items", []))[:self.max_items]:
            title = entry.get("Title") or entry.get("title") or "WHO outbreak update"
            relative_url = (
                entry.get("ItemDefaultUrl") or entry.get("Url")
                or entry.get("url") or ""
            )
            url = urllib.parse.urljoin("https://www.who.int", relative_url)
            external_id = str(
                entry.get("Id") or entry.get("id") or entry.get("UrlName")
                or relative_url or title
            )
            summary = clean_html(
                entry.get("Summary") or entry.get("Overview")
                or entry.get("summary") or ""
            )
            items.append(SourceItem(
                external_id=external_id,
                title=title,
                url=url,
                summary=summary,
                published_at=(
                    entry.get("PublicationDateAndTime")
                    or entry.get("publicationDate")
                ),
                category="disease-outbreak",
                metadata={
                    "provider": "World Health Organization",
                    "publication_type": entry.get("PublicationType")
                }
            ))
        return ConnectorBatch(items=items, cursor={
            "retrieved_at": utc_now(),
            "newest_external_id": items[0].external_id if items else None
        })
