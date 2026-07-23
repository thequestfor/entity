import csv
import io
import urllib.parse
import urllib.request

from agent.intelligence.models import ConnectorBatch, SourceItem
from agent.intelligence.store import utc_now


class FirmsConnector:
    """Collect NASA FIRMS fire detections using an operator-supplied MAP_KEY."""

    source_id = "nasa_firms_wildfires"
    name = "NASA FIRMS Active Fire Detections"
    kind = "wildfire"
    base_url = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
    credibility = 0.95
    poll_seconds = 1800

    def __init__(self, map_key="", source="VIIRS_SNPP_NRT", days=1, timeout=15,
                 max_items=50, enabled=False, fetch_csv=None):
        self.map_key = str(map_key or "").strip()
        self.source = str(source or "VIIRS_SNPP_NRT").strip()
        self.days = max(1, min(10, int(days)))
        self.timeout = max(1, int(timeout))
        self.max_items = max(1, int(max_items))
        self._fetch_csv_override = fetch_csv
        self.enabled = bool(enabled and self.map_key)

    def poll(self, cursor=None):
        if not self.enabled:
            return ConnectorBatch(cursor=cursor or {})
        url = "/".join((self.base_url, urllib.parse.quote(self.map_key, safe=""),
                          urllib.parse.quote(self.source, safe=""), "world", str(self.days)))
        try:
            response = self._fetch_csv(url)
        except Exception as exc:
            # Collector errors are persisted; never place the MAP_KEY in them.
            message = str(exc).replace(self.map_key, "[REDACTED]")
            raise RuntimeError(message) from None
        rows = list(csv.DictReader(io.StringIO(response)))
        items = [self._normalize(row) for row in rows[:self.max_items]]
        items = [item for item in items if item is not None]
        return ConnectorBatch(items=items, cursor={
            "retrieved_at": utc_now(),
            "newest_external_id": items[0].external_id if items else None
        })

    def _fetch_csv(self, url):
        if self._fetch_csv_override is not None:
            return self._fetch_csv_override(url)
        request = urllib.request.Request(url, headers={
            "Accept": "text/csv",
            "User-Agent": "EntityIntelligence/0.1 (read-only wildfire monitoring)"
        })
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return response.read().decode("utf-8", errors="replace")

    def _normalize(self, row):
        latitude = _float(row.get("latitude"))
        longitude = _float(row.get("longitude"))
        date = str(row.get("acq_date") or "").strip()
        time = str(row.get("acq_time") or "").strip().zfill(4)
        if latitude is None or longitude is None or not date:
            return None
        external_id = "firms:{}:{}:{}:{}".format(
            self.source, date, time, row.get("latitude"), row.get("longitude")
        )
        confidence = row.get("confidence")
        brightness = _float(row.get("bright_ti4") or row.get("brightness"))
        return SourceItem(
            external_id=external_id,
            title=f"NASA FIRMS active fire detection ({confidence or 'unknown'} confidence)",
            url="https://firms.modaps.eosdis.nasa.gov/map/",
            summary=(
                f"Satellite fire detection at {latitude:.3f}, {longitude:.3f}. "
                f"Confidence: {confidence or 'unknown'}; brightness: {brightness or 'unknown'}."
            ),
            published_at=f"{date}T{time[:2]}:{time[2:]}:00Z",
            category="wildfire",
            latitude=latitude,
            longitude=longitude,
            metadata={
                "provider": "NASA FIRMS",
                "satellite_source": self.source,
                "confidence": confidence,
                "brightness_kelvin": brightness,
                "frp": _float(row.get("frp")),
                "daynight": row.get("daynight")
            }
        )


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
