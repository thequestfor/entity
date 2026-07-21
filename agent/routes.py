import json
import os
import urllib.error
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
    provider: str = ""
    traffic_delay_seconds: float | None = None

    @property
    def duration_minutes(self):
        return max(1, round(self.duration_seconds / 60))

    @property
    def distance_miles(self):
        return self.distance_meters / 1609.344


class RoutePlanner:
    def __init__(self, store=None):
        self.provider = os.getenv("ENTITY_ROUTES_PROVIDER", "").lower()
        self.openrouteservice_api_key = os.getenv(
            "ENTITY_OPENROUTESERVICE_API_KEY",
            ""
        )
        self.tomtom_api_key = os.getenv("ENTITY_TOMTOM_API_KEY", "")
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
            "https://api.heigit.org/openrouteservice"
        ).rstrip("/")
        self.geocode_url = os.getenv(
            "ENTITY_OPENROUTESERVICE_GEOCODE_URL",
            "https://api.heigit.org/pelias/v1"
        ).rstrip("/")
        self.tomtom_base_url = os.getenv(
            "ENTITY_TOMTOM_BASE_URL",
            "https://api.tomtom.com"
        ).rstrip("/")
        self._geocode_cache = {}
        self.store = store or self._default_store()

    def available(self):
        if not self.home_address:
            return False

        if self.provider == "tomtom":
            return bool(self.tomtom_api_key)

        if self.provider == "openrouteservice":
            return bool(self.openrouteservice_api_key)

        return False

    def setup_status(self):
        if self.provider == "tomtom":
            if not self.tomtom_api_key:
                return "Live traffic routing enabled but TomTom API key is missing."

            if not self.home_address:
                return "Live traffic routing enabled but home address is missing."

            return (
                "Live traffic routing configured through TomTom "
                f"using {self._tomtom_travel_mode()}."
            )

        if self.provider == "openrouteservice":
            if not self.openrouteservice_api_key:
                return "Route planning enabled but openrouteservice API key is missing."

            if not self.home_address:
                return "Route planning enabled but home address is missing."

            return (
                "Route planning configured through openrouteservice "
                f"using {self.profile}. Provides route travel-time estimates, "
                "not guaranteed live traffic."
            )

        if self.provider:
            return f"Route planning provider unsupported: {self.provider}."

        return "Route planning disabled."

    def uses_live_traffic(self):
        return self.provider == "tomtom" and self.available()

    def traffic_mode_label(self):
        if self.uses_live_traffic():
            return "Live traffic"

        if self.provider == "openrouteservice":
            return "Estimated route"

        return "Route"

    def _unsupported_provider_message(self):
        if not self.provider:
            return "Route planning disabled."

        return f"Route planning provider unsupported: {self.provider}."

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
        mode = self.traffic_mode_label()
        traffic_delay = self._traffic_delay_text(estimate)

        return (
            f"You have {summary} at {event_time} at {location}. "
            f"{mode} travel time is "
            f"{estimate.duration_minutes} minutes over {distance} miles. "
            f"{traffic_delay}Leave by {leave_time}."
        )

    def estimate(self, origin, destination):
        if self.provider == "tomtom":
            return self._tomtom_estimate(origin, destination)

        if self.provider == "openrouteservice":
            return self._openrouteservice_estimate(origin, destination)

        raise RuntimeError(self._unsupported_provider_message())

    def _openrouteservice_estimate(self, origin, destination):
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
            profile=self.profile,
            provider=self.provider
        )

    def _tomtom_estimate(self, origin, destination):
        origin_coords = self.geocode(origin)
        destination_coords = self.geocode(destination)
        origin_text = self._tomtom_coordinate_text(origin_coords)
        destination_text = self._tomtom_coordinate_text(destination_coords)
        params = urllib.parse.urlencode(
            {
                "key": self.tomtom_api_key,
                "traffic": "true",
                "departAt": "now",
                "routeType": "fastest",
                "travelMode": self._tomtom_travel_mode(),
                "computeTravelTimeFor": "all"
            }
        )
        result = self._get_tomtom_json(
            f"/routing/1/calculateRoute/"
            f"{origin_text}:{destination_text}/json?{params}"
        )
        route = result["routes"][0]
        summary = route["summary"]

        return RouteEstimate(
            origin=origin,
            destination=destination,
            duration_seconds=summary["travelTimeInSeconds"],
            distance_meters=summary["lengthInMeters"],
            profile=self._tomtom_travel_mode(),
            provider=self.provider,
            traffic_delay_seconds=summary.get("trafficDelayInSeconds")
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

        if self.provider == "tomtom":
            coords = self._tomtom_geocode(query)
            self._geocode_cache[key] = coords
            return coords

        if self.provider != "openrouteservice":
            raise RuntimeError(self._unsupported_provider_message())

        params = urllib.parse.urlencode(
            {
                "text": query,
                "size": 1
            }
        )
        result = self._get_geocode_json(f"/search?{params}")
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

    def _tomtom_geocode(self, query):
        encoded_query = urllib.parse.quote(query)
        params = urllib.parse.urlencode(
            {
                "key": self.tomtom_api_key,
                "limit": 1
            }
        )
        result = self._get_tomtom_json(
            f"/search/2/geocode/{encoded_query}.json?{params}"
        )
        results = result.get("results", [])

        if not results:
            raise RuntimeError(f"Could not geocode location: {query}")

        item = results[0]
        position = item["position"]
        lon = position["lon"]
        lat = position["lat"]
        formatted = item.get("address", {}).get("freeformAddress", "")
        self.store.set_geocode(
            query,
            self.provider,
            longitude=lon,
            latitude=lat,
            formatted=formatted
        )
        return [lon, lat]

    def _default_store(self):
        from agent.memory.store import MemoryStore

        return MemoryStore()

    def _get_json(self, path):
        request = urllib.request.Request(
            self.base_url + path,
            headers={
                "Authorization": self.openrouteservice_api_key
            }
        )

        return self._open_json(request)

    def _get_geocode_json(self, path):
        request = urllib.request.Request(
            self.geocode_url + path,
            headers={
                "Authorization": self.openrouteservice_api_key
            }
        )

        return self._open_json(request)

    def _get_tomtom_json(self, path):
        request = urllib.request.Request(
            self.tomtom_base_url + path
        )

        return self._open_json(request)

    def _post_json(self, path, payload):
        request = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": self.openrouteservice_api_key,
                "Content-Type": "application/json"
            },
            method="POST"
        )

        return self._open_json(request)

    def _tomtom_coordinate_text(self, coords):
        lon, lat = coords
        return f"{lat},{lon}"

    def _tomtom_travel_mode(self):
        mapping = {
            "driving-car": "car",
            "driving-hgv": "truck",
            "cycling-regular": "bicycle",
            "foot-walking": "pedestrian",
            "walking": "pedestrian",
            "driving": "car"
        }

        return mapping.get(self.profile, self.profile or "car")

    def _traffic_delay_text(self, estimate):
        if estimate.traffic_delay_seconds is None:
            return ""

        delay_minutes = round(estimate.traffic_delay_seconds / 60)

        if delay_minutes <= 0:
            return "No traffic delay reported. "

        return f"Traffic is adding about {delay_minutes} minutes. "

    def _open_json(self, request):
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = self._http_error_detail(exc)
            raise RuntimeError(
                f"Route provider request failed ({exc.code}): {detail}"
            ) from exc
        except Exception as exc:
            raise RuntimeError(f"Route provider request failed: {exc}") from exc

    def _http_error_detail(self, error):
        try:
            payload = json.loads(error.read().decode("utf-8"))
        except (AttributeError, UnicodeDecodeError, json.JSONDecodeError):
            return error.reason or "HTTP request failed"

        detailed = payload.get("detailedError") or {}
        return (
            detailed.get("message")
            or payload.get("errorText")
            or payload.get("message")
            or error.reason
            or "HTTP request failed"
        )
