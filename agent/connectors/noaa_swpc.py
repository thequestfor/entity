from agent.connectors.base import JsonConnector
from agent.intelligence.models import ConnectorBatch, SourceItem
from agent.intelligence.store import utc_now


class NoaaSpaceWeatherConnector(JsonConnector):
    """Read NOAA SWPC's public space-weather alert feed."""

    source_id = "noaa_space_weather_alerts"
    name = "NOAA Space Weather Prediction Center Alerts"
    kind = "space_weather"
    base_url = "https://services.swpc.noaa.gov/products/alerts.json"
    credibility = 1.0
    poll_seconds = 900

    def poll(self, cursor=None):
        if not self.enabled:
            return ConnectorBatch(cursor=cursor or {})

        payload = self.fetch_json(self.base_url)
        alerts = payload if isinstance(payload, list) else payload.get("alerts", [])
        items = []
        for alert in alerts[:self.max_items]:
            alert_id = str(
                alert.get("product_id") or alert.get("id") or ""
            ).strip()
            if not alert_id:
                continue
            message = str(alert.get("message") or alert.get("text") or "")
            issue_time = alert.get("issue_datetime") or alert.get("issueDate")
            items.append(SourceItem(
                external_id=alert_id,
                title=str(alert.get("product_name") or "NOAA space weather alert"),
                url="https://www.swpc.noaa.gov/products-and-data",
                summary=message,
                published_at=issue_time,
                category="space-weather",
                metadata={
                    "provider": "NOAA Space Weather Prediction Center",
                    "issue_datetime": issue_time,
                    "message_id": alert_id
                }
            ))
        return ConnectorBatch(items=items, cursor={
            "retrieved_at": utc_now(),
            "newest_external_id": items[0].external_id if items else None
        })
