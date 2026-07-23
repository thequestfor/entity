import hashlib
import urllib.parse

from agent.connectors.base import JsonConnector
from agent.intelligence.models import ConnectorBatch, SourceItem
from agent.intelligence.store import utc_now


class GdeltConnector(JsonConnector):
    source_id = "gdelt"
    name = "GDELT Project"
    kind = "global_news_index"
    base_url = "https://api.gdeltproject.org/api/v2/doc/doc"
    credibility = 0.55
    poll_seconds = 900

    def __init__(self, queries=(), **kwargs):
        super().__init__(**kwargs)
        self.queries = tuple(query.strip() for query in queries if query.strip())
        self.enabled = self.enabled and bool(self.queries)

    def poll(self, cursor=None):
        if not self.enabled:
            return ConnectorBatch(cursor=cursor or {})
        items = []
        seen_urls = set()
        per_query = max(10, min(250, self.max_items))
        for query in self.queries:
            params = urllib.parse.urlencode({
                "query": query,
                "mode": "ArtList",
                "maxrecords": per_query,
                "format": "json",
                "sort": "DateDesc",
                "timespan": "24h"
            })
            payload = self.fetch_json(f"{self.base_url}?{params}")
            for article in payload.get("articles", []):
                url = str(article.get("url") or "").strip()
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                title = article.get("title") or "GDELT indexed report"
                items.append(SourceItem(
                    external_id=hashlib.sha256(url.encode("utf-8")).hexdigest(),
                    title=title,
                    url=url,
                    summary=title,
                    published_at=_gdelt_time(article.get("seendate")),
                    category="world-news",
                    metadata={
                        "discovery_source": "GDELT",
                        "domain": article.get("domain"),
                        "language": article.get("language"),
                        "source_country": article.get("sourcecountry"),
                        "query": query
                    }
                ))
                if len(items) >= self.max_items:
                    break
            if len(items) >= self.max_items:
                break
        return ConnectorBatch(items=items, cursor={
            "retrieved_at": utc_now(),
            "newest_external_id": items[0].external_id if items else None
        })


def _gdelt_time(value):
    value = str(value or "")
    if len(value) in {15, 16} and value[8] == "T":
        return (
            f"{value[:4]}-{value[4:6]}-{value[6:8]}T"
            f"{value[9:11]}:{value[11:13]}:{value[13:15]}Z"
        )
    return value or None
