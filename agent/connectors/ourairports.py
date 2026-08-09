"""Public-domain global airport reference connector."""

import csv
import io
import urllib.request

from agent.intelligence.models import ConnectorBatch, SourceItem
from agent.intelligence.source_registry import validate_connector_url
from agent.intelligence.store import utc_now


class OurAirportsConnector:
    source_id = "ourairports"
    name = "OurAirports"
    kind = "infrastructure_reference"
    base_url = "https://davidmegginson.github.io/ourairports-data/airports.csv"
    credibility = 0.78
    poll_seconds = 86400

    def __init__(
        self,
        airport_types=("large_airport", "medium_airport"),
        timeout=15,
        max_items=10000,
        max_bytes=20_000_000,
        poll_seconds=86400,
        fetch_csv=None,
        enabled=True,
    ):
        self.airport_types = tuple(str(value).strip() for value in airport_types if str(value).strip())
        self.timeout = max(1, int(timeout))
        self.max_items = max(1, min(25000, int(max_items)))
        self.max_bytes = max(1000, min(50_000_000, int(max_bytes)))
        self.poll_seconds = max(3600, int(poll_seconds))
        self._fetch_csv_override = fetch_csv
        self.enabled = bool(enabled and self.airport_types)

    def poll(self, cursor=None):
        if not self.enabled:
            return ConnectorBatch(cursor=cursor or {})
        text = self._fetch_csv()
        reader = csv.DictReader(io.StringIO(text))
        items = []
        for row in reader:
            if row.get("type") not in self.airport_types:
                continue
            latitude = _coordinate(row.get("latitude_deg"), -90, 90)
            longitude = _coordinate(row.get("longitude_deg"), -180, 180)
            external_id = str(row.get("id") or row.get("ident") or "").strip()
            if not external_id or latitude is None or longitude is None:
                continue
            ident = str(row.get("ident") or external_id).strip()
            name = str(row.get("name") or ident).strip()
            items.append(SourceItem(
                external_id=external_id,
                title=name,
                url=f"https://ourairports.com/airports/{ident}/",
                summary=(
                    f"OurAirports lists {name} as a {row.get('type', 'airport').replace('_', ' ')}. "
                    "This reference entry does not establish current operating status."
                ),
                category="infrastructure-airport",
                latitude=latitude,
                longitude=longitude,
                metadata={
                    "epistemic_type": "reference",
                    "asset_type": "airport",
                    "name": name,
                    "country_code": str(row.get("iso_country") or "").upper()[:3],
                    "region_code": row.get("iso_region") or "",
                    "municipality": row.get("municipality") or "",
                    "infrastructure_type": row.get("type") or "",
                    "scheduled_service": row.get("scheduled_service") == "yes",
                    "elevation_ft": _number(row.get("elevation_ft")),
                    "identifiers": {
                        key: row.get(key) or ""
                        for key in ("ident", "icao_code", "iata_code", "gps_code", "local_code")
                    },
                    "geometry": {
                        "type": "Point",
                        "coordinates": [longitude, latitude],
                    },
                },
            ))
            if len(items) >= self.max_items:
                break
        return ConnectorBatch(items=items, cursor={
            "retrieved_at": utc_now(),
            "airport_types": self.airport_types,
            "asset_count": len(items),
        })

    def _fetch_csv(self):
        url = validate_connector_url(self, self.base_url)
        if self._fetch_csv_override is not None:
            payload = self._fetch_csv_override(url)
            payload = payload if isinstance(payload, bytes) else str(payload).encode("utf-8")
            if len(payload) > self.max_bytes:
                raise ValueError("OurAirports response exceeded configured byte limit")
            return payload.decode("utf-8-sig", errors="replace")
        request = urllib.request.Request(url, headers={
            "Accept": "text/csv",
            "User-Agent": "EntityIntelligence/0.1 (read-only reference collector)",
        })
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            payload = response.read(self.max_bytes + 1)
        if len(payload) > self.max_bytes:
            raise ValueError("OurAirports response exceeded configured byte limit")
        return payload.decode("utf-8-sig", errors="replace")


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coordinate(value, minimum, maximum):
    number = _number(value)
    return number if number is not None and minimum <= number <= maximum else None
