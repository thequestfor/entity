from agent.connectors.base import JsonConnector
from agent.intelligence.models import ConnectorBatch, SourceItem
from agent.intelligence.store import utc_now


class UsgsConnector(JsonConnector):
    source_id = "usgs_earthquakes"
    name = "USGS Earthquakes"
    kind = "natural_hazard"
    base_url = (
        "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/"
        "2.5_day.geojson"
    )
    credibility = 1.0
    poll_seconds = 120

    def poll(self, cursor=None):
        if not self.enabled:
            return ConnectorBatch(cursor=cursor or {})

        payload = self.fetch_json(self.base_url)
        items = []

        for feature in payload.get("features", [])[:self.max_items]:
            properties = feature.get("properties") or {}
            geometry = feature.get("geometry") or {}
            coordinates = geometry.get("coordinates") or []
            external_id = str(feature.get("id") or properties.get("code") or "")
            url = properties.get("url") or properties.get("detail") or ""

            if not external_id or not url:
                continue

            magnitude = properties.get("mag")
            place = properties.get("place") or "unknown location"
            title = properties.get("title") or f"Earthquake near {place}"
            summary = f"Magnitude {magnitude} earthquake near {place}."

            items.append(
                SourceItem(
                    external_id=external_id,
                    title=title,
                    url=url,
                    summary=summary,
                    published_at=properties.get("time"),
                    category="earthquake",
                    latitude=_coordinate(coordinates, 1),
                    longitude=_coordinate(coordinates, 0),
                    metadata={
                        "magnitude": magnitude,
                        "place": place,
                        "significance": properties.get("sig"),
                        "alert": properties.get("alert"),
                        "tsunami": bool(properties.get("tsunami")),
                        "status": properties.get("status"),
                        "updated_at": properties.get("updated"),
                        "depth_km": _coordinate(coordinates, 2)
                    }
                )
            )

        return ConnectorBatch(
            items=items,
            cursor={
                "retrieved_at": utc_now(),
                "feed_generated_at": payload.get("metadata", {}).get("generated")
            }
        )


def _coordinate(coordinates, index):
    try:
        return float(coordinates[index])
    except (IndexError, TypeError, ValueError):
        return None
