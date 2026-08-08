"""Bounded ADSB.lol current-state collector for the visual map layer."""

import json
import time
import urllib.request
from datetime import UTC, datetime

from agent.intelligence.store import utc_now


class AdsbLolAircraftMonitor:
    endpoint = "https://api.adsb.lol/v2/point"

    def __init__(self, store, enabled=False, center="", radius_nm=100, poll_seconds=120, max_states=300, timeout=15):
        self.store, self.enabled = store, bool(enabled)
        self.center = self._center(center)
        self.radius_nm = max(1, min(250, int(radius_nm)))
        self.poll_seconds, self.max_states, self.timeout = max(60, int(poll_seconds)), max(1, min(1000, int(max_states))), max(1, int(timeout))
        self._next_at = 0.0

    @staticmethod
    def _center(value):
        try:
            latitude, longitude = (float(part.strip()) for part in str(value).split(","))
        except (TypeError, ValueError):
            return None
        return (latitude, longitude) if -90 <= latitude <= 90 and -180 <= longitude <= 180 else None

    def run_if_due(self, force=False):
        if not self.enabled or not self.center or (not force and time.monotonic() < self._next_at):
            return 0
        try:
            states = self._fetch()
            self.store.replace_aircraft_states(states, source_id="adsb_lol")
            self._next_at = time.monotonic() + self.poll_seconds
            return len(states)
        except Exception as exc:
            # Never include tokens/secrets in worker logs.
            print("ADSB.lol aircraft update failed:", type(exc).__name__)
            self._next_at = time.monotonic() + max(self.poll_seconds, 300)
            return 0

    def _fetch(self):
        latitude, longitude = self.center
        url = f"{self.endpoint}/{latitude}/{longitude}/{self.radius_nm}"
        request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "EntityIntelligence/0.1"})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        observed = datetime.fromtimestamp(int(payload.get("now") or time.time()), UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
        output = []
        for raw in (payload.get("ac") or [])[:self.max_states]:
            if not isinstance(raw, dict):
                continue
            latitude, longitude = raw.get("lat"), raw.get("lon")
            if not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float)) or not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                continue
            icao24 = str(raw.get("hex") or "").strip().lower()
            if not icao24:
                continue
            seen = raw.get("seen_pos")
            last_contact = datetime.fromtimestamp(time.time() - seen, UTC).isoformat(timespec="seconds").replace("+00:00", "Z") if isinstance(seen, (int, float)) else None
            altitude = raw.get("alt_baro")
            output.append({"icao24": icao24, "callsign": str(raw.get("flight") or "").strip(), "origin_country": "",
                           "longitude": longitude, "latitude": latitude, "altitude_m": altitude * .3048 if isinstance(altitude, (int, float)) else None,
                           "on_ground": altitude == "ground", "velocity_mps": raw.get("gs", 0) * .514444 if isinstance(raw.get("gs"), (int, float)) else None,
                           "heading_degrees": raw.get("track"), "vertical_rate_mps": raw.get("baro_rate", 0) * .00508 if isinstance(raw.get("baro_rate"), (int, float)) else None,
                           "last_contact_at": last_contact, "observed_at": observed})
        return output
