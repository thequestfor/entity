"""Public Copernicus Emergency Management activation feed."""

import re
import urllib.parse

from agent.connectors.base import JsonConnector
from agent.intelligence.models import ConnectorBatch, SourceItem
from agent.intelligence.store import utc_now


class CopernicusEmsConnector(JsonConnector):
    source_id = "copernicus_ems"
    name = "Copernicus Emergency Management Service"
    kind = "emergency_mapping"
    base_url = "https://mapping.emergency.copernicus.eu/activations/api/activations/"
    credibility = 0.97
    poll_seconds = 900

    def poll(self, cursor=None):
        if not self.enabled:
            return ConnectorBatch(cursor=cursor or {})
        params = urllib.parse.urlencode({"limit":self.max_items,"offset":0})
        payload = self.fetch_json(f"{self.base_url}?{params}")
        records = payload.get("results") if isinstance(payload, dict) else payload
        items = []
        for activation in (records or [])[:self.max_items]:
            code = str(activation.get("code") or activation.get("activationCode") or "").strip()
            if not code:
                continue
            countries = activation.get("countries") or []
            if isinstance(countries, str):
                countries = [countries]
            country_names = [
                str(value.get("name") if isinstance(value, dict) else value).strip()
                for value in countries if value
            ]
            latitude, longitude = _centroid(activation.get("centroid"))
            category = _category(activation.get("category") or activation.get("eventType"))
            name = str(activation.get("name") or activation.get("title") or f"Copernicus activation {code}").strip()
            last_update = activation.get("lastUpdate") or activation.get("updatedAt") or activation.get("activationTime")
            closed = bool(activation.get("closed"))
            items.append(SourceItem(
                external_id=code,title=name,
                url=f"https://mapping.emergency.copernicus.eu/activations/{urllib.parse.quote(code)}",
                summary=f"Copernicus emergency mapping activation {code} covering {', '.join(country_names) or 'an identified area'}.",
                published_at=activation.get("eventTime") or activation.get("activationTime"),
                category=category,latitude=latitude,longitude=longitude,
                status="closed" if closed else "active",
                metadata={
                    "activation_code":code,"countries":country_names,
                    "country":country_names[0] if len(country_names) == 1 else "",
                    "event_type":activation.get("category") or activation.get("eventType") or "",
                    "activation_time":activation.get("activationTime"),
                    "last_update":last_update,"closed":closed,
                    "gdacs_id":activation.get("gdacsId") or "",
                    "area_of_interest_count":activation.get("n_aois") or activation.get("aoiCount"),
                    "product_count":activation.get("n_products") or activation.get("productCount"),
                    "epistemic_type":"satellite-mapping-activation",
                    "geometry":{"type":"Point","coordinates":[longitude,latitude]}
                    if latitude is not None and longitude is not None else {}
                }
            ))
        return ConnectorBatch(items=items,cursor={
            "retrieved_at":utc_now(),
            "newest_update":max((str(item.metadata.get("last_update") or "") for item in items),default="")
        })


def _centroid(value):
    if isinstance(value, dict):
        coordinates = value.get("coordinates") or []
        if len(coordinates) >= 2:
            return _valid(coordinates[1], -90, 90), _valid(coordinates[0], -180, 180)
    match = re.search(r"POINT\s*\(\s*([-+\d.]+)\s+([-+\d.]+)\s*\)", str(value or ""), re.I)
    if not match:
        return None, None
    return _valid(match.group(2), -90, 90), _valid(match.group(1), -180, 180)


def _valid(value, minimum, maximum):
    try:
        number = float(value)
        return number if minimum <= number <= maximum else None
    except (TypeError, ValueError):
        return None


def _category(value):
    value = str(value or "").lower()
    for token, category in (
        ("wildfire","wildfire"),("fire","wildfire"),("earthquake","earthquake"),
        ("flood","flood"),("storm","storm"),("cyclone","storm"),
        ("volcano","volcano"),("drought","drought")
    ):
        if token in value:
            return category
    return "emergency-mapping"
