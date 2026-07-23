import json
import os
import subprocess
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class LocationEstimate:
    latitude: float
    longitude: float
    label: str
    method: str
    accuracy: str


class LocationResolver:
    """Resolve location without collecting or transmitting nearby BSSIDs."""

    def __init__(self, fetch_json=None, connection_name=None):
        self.enabled = self._env_bool("ENTITY_LOCATION_DETECTION_ENABLED", True)
        self.wifi_enabled = self._env_bool(
            "ENTITY_LOCATION_WIFI_MAPPING_ENABLED", True
        )
        self.public_ip_enabled = self._env_bool(
            "ENTITY_LOCATION_PUBLIC_IP_ENABLED", False
        )
        self.public_ip_url = os.getenv(
            "ENTITY_LOCATION_PUBLIC_IP_URL", "https://ipapi.co/json/"
        ).strip()
        self.timeout = self._env_int(
            "ENTITY_LOCATION_TIMEOUT_SECONDS", 5, minimum=1
        )
        self.wifi_mappings = self._wifi_mappings(
            os.getenv("ENTITY_LOCATION_WIFI_MAP", "")
        )
        self._fetch_json_override = fetch_json
        self._connection_name_override = connection_name

    def resolve(self):
        if not self.enabled:
            return None
        if self.wifi_enabled:
            connection = self._active_wifi_connection()
            mapping = self.wifi_mappings.get(connection)
            if mapping:
                return LocationEstimate(
                    latitude=mapping[1],
                    longitude=mapping[2],
                    label=mapping[0],
                    method="recognized_wifi",
                    accuracy="configured place"
                )
        if self.public_ip_enabled:
            return self._public_ip_location()
        return None

    def describe(self):
        estimate = self.resolve()
        if estimate is None:
            return (
                "I could not determine the current location safely. I only "
                "use locally recognized Wi-Fi mappings unless coarse public-IP "
                "location is explicitly enabled."
            )
        if estimate.method == "recognized_wifi":
            return (
                f"Current location is {estimate.label}, based on a locally "
                "recognized Wi-Fi connection. No nearby Wi-Fi identifiers "
                "were uploaded."
            )
        return (
            f"Coarse network location is {estimate.label}. This is based on "
            "the public internet address and may be wrong by many miles."
        )

    def setup_status(self):
        if not self.enabled:
            return "Location detection disabled."
        return (
            "Location detection enabled with local Wi-Fi mappings"
            + (
                " and opt-in coarse public-IP fallback."
                if self.public_ip_enabled else
                "; public-IP fallback disabled."
            )
        )

    def _active_wifi_connection(self):
        if self._connection_name_override is not None:
            return str(self._connection_name_override)
        try:
            result = subprocess.run(
                [
                    "nmcli", "--terse", "--fields",
                    "DEVICE,TYPE,STATE,CONNECTION", "device", "status"
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=self.timeout
            )
        except (FileNotFoundError, subprocess.SubprocessError):
            return ""
        for line in result.stdout.splitlines():
            parts = line.split(":", 3)
            if len(parts) == 4 and parts[1] == "wifi" and parts[2] == "connected":
                return parts[3].replace("\\:", ":").replace("\\\\", "\\")
        return ""

    def _public_ip_location(self):
        try:
            payload = self._fetch_json(self.public_ip_url)
            if payload.get("error"):
                return None
            latitude = float(payload["latitude"])
            longitude = float(payload["longitude"])
        except (KeyError, TypeError, ValueError, OSError):
            return None
        label = ", ".join(
            str(payload.get(key) or "").strip()
            for key in ("city", "region", "country_name")
            if str(payload.get(key) or "").strip()
        )
        return LocationEstimate(
            latitude, longitude, label or "unknown network area",
            "public_ip", "city-level coarse estimate"
        )

    def _fetch_json(self, url):
        if self._fetch_json_override is not None:
            return self._fetch_json_override(url)
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "EntityLocation/1.0 local personal assistant"}
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def _wifi_mappings(self, value):
        mappings = {}
        for definition in value.split("||"):
            parts = [part.strip() for part in definition.split("|")]
            if len(parts) != 4 or not parts[0] or not parts[1]:
                continue
            try:
                mappings[parts[0]] = (parts[1], float(parts[2]), float(parts[3]))
            except ValueError:
                continue
        return mappings

    def _env_bool(self, name, default=False):
        value = os.getenv(name)
        if value is None:
            return default
        return value.strip().lower() in {"1", "true", "yes", "on"}

    def _env_int(self, name, default, minimum=0):
        try:
            value = int(os.getenv(name, str(default)))
        except ValueError:
            value = default
        return max(minimum, value)
