"""Bounded OpenSky current-state collector for the visual map layer."""

import base64
import json
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime

from agent.intelligence.store import utc_now


class OpenSkyAircraftMonitor:
    endpoint = "https://opensky-network.org/api/states/all"
    token_endpoint = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"

    def __init__(self, store, enabled=False, bounds="", client_id="", client_secret="", poll_seconds=120, max_states=300, timeout=15):
        self.store, self.enabled = store, bool(enabled)
        self.bounds = self._bounds(bounds)
        self.client_id, self.client_secret = client_id, client_secret
        self.poll_seconds, self.max_states, self.timeout = max(60, int(poll_seconds)), max(1, min(1000, int(max_states))), max(1, int(timeout))
        self._next_at = 0.0
        self._token, self._token_expires_at = "", 0.0

    @staticmethod
    def _bounds(value):
        try:
            west, south, east, north = (float(part.strip()) for part in str(value).split(","))
        except (TypeError, ValueError):
            return None
        if -180 <= west <= 180 and -180 <= east <= 180 and -90 <= south < north <= 90 and west < east:
            return west, south, east, north
        return None

    def run_if_due(self, force=False):
        if not self.enabled or not self.bounds or (not force and time.monotonic() < self._next_at):
            return 0
        try:
            states = self._fetch()
            self.store.replace_aircraft_states(states, source_id="opensky")
            self._next_at = time.monotonic() + self.poll_seconds
            return len(states)
        except Exception as exc:
            # Never include tokens/secrets in worker logs.
            print("OpenSky aircraft update failed:", type(exc).__name__)
            self._next_at = time.monotonic() + max(self.poll_seconds, 300)
            return 0

    def _headers(self):
        headers = {"Accept": "application/json", "User-Agent": "EntityIntelligence/0.1"}
        if self.client_id and self.client_secret:
            if not self._token or time.monotonic() >= self._token_expires_at:
                body = urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": self.client_id, "client_secret": self.client_secret}).encode()
                request = urllib.request.Request(self.token_endpoint, data=body, headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}, method="POST")
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                self._token = str(payload.get("access_token") or "")
                self._token_expires_at = time.monotonic() + max(30, int(payload.get("expires_in") or 1800) - 60)
            if self._token:
                headers["Authorization"] = "Bearer " + self._token
        return headers

    def _fetch(self):
        west, south, east, north = self.bounds
        query = urllib.parse.urlencode({"lomin": west, "lamin": south, "lomax": east, "lamax": north})
        request = urllib.request.Request(self.endpoint + "?" + query, headers=self._headers())
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        observed = datetime.fromtimestamp(int(payload.get("time") or time.time()), UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
        output = []
        for raw in (payload.get("states") or [])[:self.max_states]:
            if not isinstance(raw, list) or len(raw) < 9:
                continue
            latitude, longitude = raw[6], raw[5]
            if not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float)) or not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                continue
            icao24 = str(raw[0] or "").strip().lower()
            if not icao24:
                continue
            contact = raw[4]
            last_contact = datetime.fromtimestamp(contact, UTC).isoformat(timespec="seconds").replace("+00:00", "Z") if isinstance(contact, (int, float)) else None
            output.append({"icao24": icao24, "callsign": str(raw[1] or "").strip(), "origin_country": str(raw[2] or "").strip(),
                           "longitude": longitude, "latitude": latitude, "altitude_m": raw[7], "on_ground": bool(raw[8]),
                           "velocity_mps": raw[9] if len(raw) > 9 else None, "heading_degrees": raw[10] if len(raw) > 10 else None,
                           "vertical_rate_mps": raw[11] if len(raw) > 11 else None, "last_contact_at": last_contact, "observed_at": observed})
        return output
