import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


@dataclass
class RouteEstimate:
    origin: str
    destination: str
    duration_seconds: float
    distance_meters: float
    profile: str

    @property
    def duration_minutes(self):
        return max(1, round(self.duration_seconds / 60))

    @property
    def distance_miles(self):
        return self.distance_meters / 1609.344


class RoutePlanner:
    def __init__(self, store=None):
        self.provider = os.getenv("ENTITY_ROUTES_PROVIDER", "").lower()
        self.api_key = os.getenv("ENTITY_OPENROUTESERVICE_API_KEY", "")
        self.home_address = os.getenv("ENTITY_HOME_ADDRESS", "")
        self.profile = os.getenv(
            "ENTITY_DEFAULT_TRAVEL_MODE",
            "driving-car"
        )
        self.buffer_minutes = int(
            os.getenv("ENTITY_DEPARTURE_BUFFER_MINUTES", "10")
        )
        self.timezone = ZoneInfo(
            os.getenv("ENTITY_TIMEZONE", "America/New_York")
        )
        self.base_url = os.getenv(
            "ENTITY_OPENROUTESERVICE_URL",
            "https://api.openrouteservice.org"
        ).rstrip("/")
        self._geocode_cache = {}
        self.store = store or self._default_store()

    def available(self):
        return (
            self.provider == "openrouteservice"
            and bool(self.api_key)
            and bool(self.home_address)
        )

    def setup_status(self):
        if self.provider != "openrouteservice":
            return "Route planning disabled."

        if not self.api_key:
            return "Route planning enabled but openrouteservice API key is missing."

        if not self.home_address:
            return "Route planning enabled but home address is missing."

        return f"Route planning configured through openrouteservice using {self.profile}."

    def departure_advice(self, event_payload):
        location = event_payload.get("location", "")
        start = event_payload.get("start", "")

        if not location or not start:
            return None

        if not self.available():
            return None

        estimate = self.estimate(self.home_address, location)
        start_dt = datetime.fromisoformat(start).astimezone(self.timezone)
        leave_at = start_dt - timedelta(
            seconds=estimate.duration_seconds,
            minutes=self.buffer_minutes
        )
        summary = event_payload.get("summary", "your calendar event")
        event_time = start_dt.strftime("%-I:%M %p")
        leave_time = leave_at.strftime("%-I:%M %p")
        distance = round(estimate.distance_miles, 1)

        return (
            f"You have {summary} at {event_time} at {location}. "
            f"Estimated {estimate.profile} travel time is "
            f"{estimate.duration_minutes} minutes over {distance} miles. "
            f"Leave by {leave_time}."
        )

    def estimate(self, origin, destination):
        origin_coords = self.geocode(origin)
        destination_coords = self.geocode(destination)
        payload = {
            "coordinates": [
                origin_coords,
                destination_coords
            ],
            "instructions": False
        }
        result = self._post_json(
            f"/v2/directions/{self.profile}/json",
            payload
        )
        route = result["routes"][0]
        summary = route["summary"]

        return RouteEstimate(
            origin=origin,
            destination=destination,
            duration_seconds=summary["duration"],
            distance_meters=summary["distance"],
            profile=self.profile
        )

    def geocode(self, query):
        key = query.strip().lower()

        if key in self._geocode_cache:
            return self._geocode_cache[key]

        cached = self.store.get_geocode(query, self.provider)

        if cached:
            coords = [
                cached["longitude"],
                cached["latitude"]
            ]
            self._geocode_cache[key] = coords
            return coords

        params = urllib.parse.urlencode(
            {
                "text": query,
                "size": 1
            }
        )
        result = self._get_json(f"/geocode/search?{params}")
        features = result.get("features", [])

        if not features:
            raise RuntimeError(f"Could not geocode location: {query}")

        coords = features[0]["geometry"]["coordinates"]
        formatted = features[0].get("properties", {}).get("label", "")
        self.store.set_geocode(
            query,
            self.provider,
            longitude=coords[0],
            latitude=coords[1],
            formatted=formatted
        )
        self._geocode_cache[key] = coords
        return coords

    def _default_store(self):
        from agent.memory.store import MemoryStore

        return MemoryStore()

    def _get_json(self, path):
        request = urllib.request.Request(
            self.base_url + path,
            headers={
                "Authorization": self.api_key
            }
        )

        return self._open_json(request)

    def _post_json(self, path, payload):
        request = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": self.api_key,
                "Content-Type": "application/json"
            },
            method="POST"
        )

        return self._open_json(request)

    def _open_json(self, request):
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise RuntimeError(f"Route provider request failed: {exc}") from exc
