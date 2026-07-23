import urllib.parse

from agent.connectors.base import JsonConnector
from agent.intelligence.models import ConnectorBatch, SourceItem
from agent.intelligence.store import utc_now


class EonetConnector(JsonConnector):
    source_id = "nasa_eonet"
    name = "NASA EONET"
    kind = "natural_hazard"
    base_url = "https://eonet.gsfc.nasa.gov/api/v3/events"
    credibility = 0.95
    poll_seconds = 900

    def poll(self, cursor=None):
        if not self.enabled:
            return ConnectorBatch(cursor=cursor or {})

        params = urllib.parse.urlencode(
            {
                "status": "open",
                "limit": self.max_items
            }
        )
        payload = self.fetch_json(f"{self.base_url}?{params}")
        items = []

        for event in payload.get("events", [])[:self.max_items]:
            external_id = str(event.get("id") or "")
            title = event.get("title") or "NASA natural event"
            url = event.get("link") or ""

            if not external_id:
                continue

            if not url:
                url = f"{self.base_url}/{urllib.parse.quote(external_id)}"

            categories = [
                str(category.get("title") or category.get("id"))
                for category in event.get("categories", [])
                if category.get("title") or category.get("id")
            ]
            geometry = event.get("geometry") or []
            latest_geometry = geometry[-1] if geometry else {}
            coordinates = latest_geometry.get("coordinates") or []
            latitude, longitude = _lat_lon(coordinates)
            published_at = (
                latest_geometry.get("date")
                or event.get("closed")
            )
            sources = [
                {
                    "id": source.get("id"),
                    "url": source.get("url")
                }
                for source in event.get("sources", [])
            ]

            items.append(
                SourceItem(
                    external_id=external_id,
                    title=title,
                    url=url,
                    summary=event.get("description") or title,
                    published_at=published_at,
                    category=_category(categories),
                    latitude=latitude,
                    longitude=longitude,
                    metadata={
                        "categories": categories,
                        "closed_at": event.get("closed"),
                        "source_links": sources,
                        "geometry_type": latest_geometry.get("type"),
                        "geometry_count": len(geometry)
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


def _category(categories):
    if not categories:
        return "natural-event"

    return categories[0]


def _lat_lon(coordinates):
    try:
        if not coordinates or isinstance(coordinates[0], (list, tuple)):
            return None, None

        return float(coordinates[1]), float(coordinates[0])
    except (IndexError, TypeError, ValueError):
        return None, None
