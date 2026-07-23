import urllib.parse

from agent.connectors.base import JsonConnector
from agent.intelligence.models import ConnectorBatch, SourceItem
from agent.intelligence.store import utc_now


class NwsAlertsConnector(JsonConnector):
    source_id = "nws_alerts"
    name = "US National Weather Service Alerts"
    kind = "weather_alert"
    base_url = "https://api.weather.gov/alerts/active"
    credibility = 1.0
    poll_seconds = 120

    def poll(self, cursor=None):
        if not self.enabled:
            return ConnectorBatch(cursor=cursor or {})
        query = urllib.parse.urlencode({
            "status": "actual",
            "message_type": "alert"
        })
        payload = self.fetch_json(f"{self.base_url}?{query}")
        items = []
        for feature in payload.get("features", [])[:self.max_items]:
            properties = feature.get("properties") or {}
            external_id = str(
                feature.get("id") or properties.get("id")
                or properties.get("@id") or ""
            )
            if not external_id:
                continue
            description = properties.get("description") or ""
            instruction = properties.get("instruction") or ""
            summary = description
            if instruction:
                summary = f"{description}\n\nInstructions: {instruction}".strip()
            items.append(SourceItem(
                external_id=external_id,
                title=(properties.get("headline") or properties.get("event")
                       or "NWS weather alert"),
                url=(properties.get("@id") or feature.get("id") or self.base_url),
                summary=summary,
                published_at=(properties.get("sent") or properties.get("effective")),
                category=_weather_category(properties.get("event")),
                metadata={
                    "event": properties.get("event"),
                    "severity": properties.get("severity"),
                    "certainty": properties.get("certainty"),
                    "urgency": properties.get("urgency"),
                    "area": properties.get("areaDesc"),
                    "onset": properties.get("onset"),
                    "expires": properties.get("expires"),
                    "sender": properties.get("senderName")
                }
            ))
        return ConnectorBatch(items=items, cursor={
            "retrieved_at": utc_now(),
            "newest_external_id": items[0].external_id if items else None
        })


def _weather_category(event):
    value = str(event or "").lower()
    if any(word in value for word in ("tornado", "hurricane", "storm", "cyclone")):
        return "severe-storms"
    if "flood" in value:
        return "floods"
    if any(word in value for word in ("fire", "red flag")):
        return "wildfires"
    return "weather-alert"
