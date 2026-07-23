import urllib.parse

from agent.connectors.base import JsonConnector
from agent.intelligence.models import ConnectorBatch, SourceItem
from agent.intelligence.store import utc_now


class WorldBankIndicatorsConnector(JsonConnector):
    """Collect selected public World Bank macroeconomic indicators."""

    source_id = "world_bank_indicators"
    name = "World Bank Open Data"
    kind = "economic_indicator"
    base_url = "https://api.worldbank.org/v2/country"
    credibility = 0.95
    poll_seconds = 86400

    def __init__(self, countries=("WLD",), indicators=(), **kwargs):
        super().__init__(**kwargs)
        self.countries = tuple(
            str(value).strip().upper() for value in countries if str(value).strip()
        ) or ("WLD",)
        self.indicators = tuple(
            str(value).strip().upper() for value in indicators if str(value).strip()
        )
        self.enabled = bool(self.enabled and self.indicators)

    def poll(self, cursor=None):
        if not self.enabled:
            return ConnectorBatch(cursor=cursor or {})

        items = []
        for country in self.countries:
            for indicator in self.indicators:
                if len(items) >= self.max_items:
                    break
                items.extend(self._indicator_items(country, indicator))
            if len(items) >= self.max_items:
                break
        items = items[:self.max_items]
        return ConnectorBatch(items=items, cursor={
            "retrieved_at": utc_now(),
            "countries": self.countries,
            "indicators": self.indicators
        })

    def _indicator_items(self, country, indicator):
        url = "/".join((self.base_url, urllib.parse.quote(country, safe=""),
                          "indicator", urllib.parse.quote(indicator, safe="")))
        payload = self.fetch_json(f"{url}?format=json&per_page=10")
        rows = payload[1] if isinstance(payload, list) and len(payload) > 1 else []
        for row in rows:
            value = _number(row.get("value"))
            year = str(row.get("date") or "").strip()
            country_info = row.get("country") or {}
            indicator_info = row.get("indicator") or {}
            if value is None or not year:
                continue
            country_name = str(country_info.get("value") or country)
            indicator_name = str(indicator_info.get("value") or indicator)
            return [SourceItem(
                external_id=f"{country}:{indicator}:{year}",
                title=f"{country_name}: {indicator_name} ({year})",
                url=(
                    "https://data.worldbank.org/indicator/"
                    f"{urllib.parse.quote(indicator, safe='')}?locations={urllib.parse.quote(country, safe='')}"
                ),
                summary=f"World Bank reports {value:g} for {indicator_name} in {country_name} during {year}.",
                published_at=f"{year}-12-31T00:00:00Z",
                category="economic-indicator",
                metadata={
                    "provider": "World Bank Open Data",
                    "country_code": country,
                    "country": country_name,
                    "indicator_code": indicator,
                    "indicator": indicator_name,
                    "year": year,
                    "value": value,
                    "unit": row.get("unit")
                }
            )]
        return []


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
