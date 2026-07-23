import urllib.parse

from agent.connectors.base import JsonConnector
from agent.intelligence.models import ConnectorBatch, SourceItem
from agent.intelligence.store import utc_now


class FredConnector(JsonConnector):
    """Collect selected FRED time series with an operator-provided API key."""

    source_id = "fred_economic_indicators"
    name = "Federal Reserve Economic Data"
    kind = "economic_indicator"
    base_url = "https://api.stlouisfed.org/fred/series/observations"
    credibility = 1.0
    poll_seconds = 21600

    def __init__(self, api_key="", series=(), **kwargs):
        super().__init__(**kwargs)
        self.api_key = str(api_key or "").strip()
        self.series = tuple(
            str(value).strip().upper() for value in series if str(value).strip()
        )
        self.enabled = bool(self.enabled and self.api_key and self.series)

    def poll(self, cursor=None):
        if not self.enabled:
            return ConnectorBatch(cursor=cursor or {})
        items = []
        for series_id in self.series[:self.max_items]:
            try:
                item = self._series_item(series_id)
            except Exception as exc:
                # Worker errors are stored in the database; API keys must not be.
                raise RuntimeError(str(exc).replace(self.api_key, "[REDACTED]")) from None
            if item:
                items.append(item)
        return ConnectorBatch(items=items, cursor={
            "retrieved_at": utc_now(), "series": self.series
        })

    def _series_item(self, series_id):
        query = urllib.parse.urlencode({
            "series_id": series_id, "api_key": self.api_key,
            "file_type": "json", "sort_order": "desc", "limit": 2
        })
        payload = self.fetch_json(f"{self.base_url}?{query}")
        observations = payload.get("observations", [])
        usable = [row for row in observations if _number(row.get("value")) is not None]
        if not usable:
            return None
        latest = usable[0]
        value = _number(latest.get("value"))
        previous = _number(usable[1].get("value")) if len(usable) > 1 else None
        change = value - previous if previous is not None else None
        detail = f"Latest FRED observation for {series_id}: {value:g} ({latest.get('date')})."
        if change is not None:
            detail += f" Change from prior observation: {change:+g}."
        return SourceItem(
            external_id=f"{series_id}:{latest.get('date')}",
            title=f"FRED {series_id} ({latest.get('date')})",
            url=f"https://fred.stlouisfed.org/series/{urllib.parse.quote(series_id, safe='')}",
            summary=detail,
            published_at=f"{latest.get('date')}T00:00:00Z",
            category="economic-indicator",
            metadata={
                "provider": "Federal Reserve Economic Data",
                "series_id": series_id,
                "value": value,
                "previous_value": previous,
                "change": change,
                "observation_date": latest.get("date")
            }
        )


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
