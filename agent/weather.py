import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass


@dataclass
class WeatherReport:
    location: str
    temperature_f: float | None = None
    apparent_temperature_f: float | None = None
    precipitation_probability: int | None = None
    wind_speed_mph: float | None = None
    condition: str = ""
    high_f: float | None = None
    low_f: float | None = None

    def format_response(self, question=""):
        parts = [
            f"Weather for {self.location}:"
        ]

        if self.condition:
            parts.append(self.condition + ".")

        if self.temperature_f is not None:
            current = f"Current temperature is {round(self.temperature_f)} degrees"

            if self.apparent_temperature_f is not None:
                current += f", feels like {round(self.apparent_temperature_f)}"

            parts.append(current + ".")

        if self.high_f is not None and self.low_f is not None:
            parts.append(
                f"Today's range is {round(self.low_f)} to {round(self.high_f)} degrees."
            )

        if self.precipitation_probability is not None:
            parts.append(
                f"Precipitation chance is {self.precipitation_probability}%."
            )

        if self.wind_speed_mph is not None:
            parts.append(f"Wind is about {round(self.wind_speed_mph)} mph.")

        advice = self._advice(question)

        if advice:
            parts.append(advice)

        return " ".join(parts)

    def _advice(self, question):
        normalized = question.lower()
        advice = []

        if self.precipitation_probability is not None:
            if self.precipitation_probability >= 50:
                advice.append("Bring an umbrella or rain jacket.")
            elif any(word in normalized for word in ("rain", "umbrella", "wet")):
                advice.append("Rain risk looks low, but check again before leaving.")

        temp = self.apparent_temperature_f

        if temp is None:
            temp = self.temperature_f

        if temp is not None:
            if temp <= 45:
                advice.append("Wear a warm layer.")
            elif temp <= 60 and any(
                word in normalized
                for word in ("jacket", "wear", "outside", "cold")
            ):
                advice.append("A light jacket is reasonable.")

        return " ".join(advice)


class WeatherTool:
    def __init__(self):
        self.enabled = self._env_bool("ENTITY_WEATHER_ENABLED", default=True)
        self.provider = os.getenv("ENTITY_WEATHER_PROVIDER", "open-meteo").lower()
        self.default_location = os.getenv("ENTITY_WEATHER_LOCATION", "")
        self.latitude = os.getenv("ENTITY_WEATHER_LATITUDE", "")
        self.longitude = os.getenv("ENTITY_WEATHER_LONGITUDE", "")
        self.timeout = self._env_int(
            "ENTITY_WEATHER_TIMEOUT_SECONDS",
            default=10,
            minimum=1
        )
        self.forecast_url = os.getenv(
            "ENTITY_OPEN_METEO_FORECAST_URL",
            "https://api.open-meteo.com/v1/forecast"
        )
        self.geocode_url = os.getenv(
            "ENTITY_OPEN_METEO_GEOCODE_URL",
            "https://geocoding-api.open-meteo.com/v1/search"
        )

    def available(self):
        return self.enabled and self.provider == "open-meteo"

    def setup_status(self):
        if not self.enabled:
            return "Weather lookup disabled."

        if self.provider != "open-meteo":
            return f"Weather lookup provider unsupported: {self.provider}."

        if self.latitude and self.longitude:
            return "Weather lookup online through Open-Meteo with default coordinates."

        if self.default_location:
            return "Weather lookup online through Open-Meteo with default location."

        return "Weather lookup online through Open-Meteo. No default location configured."

    def lookup(self, location="", question=""):
        if not self.available():
            return "Weather lookup is disabled."

        location = location.strip()

        try:
            latitude, longitude, label = self._resolve_location(location)
            payload = self._forecast(latitude, longitude)
        except Exception as exc:
            return f"Weather lookup failed: {exc}"

        report = self._report_from_payload(payload, label)
        return report.format_response(question=question)

    def _resolve_location(self, location):
        if location:
            return self._geocode(location)

        if self.latitude and self.longitude:
            label = self.default_location or "configured location"
            return float(self.latitude), float(self.longitude), label

        if self.default_location:
            return self._geocode(self.default_location)

        raise RuntimeError(
            "No location provided. Ask for a location or set "
            "ENTITY_WEATHER_LOCATION, ENTITY_WEATHER_LATITUDE, and "
            "ENTITY_WEATHER_LONGITUDE."
        )

    def _geocode(self, location):
        data = {}

        for candidate in self._location_candidates(location):
            data = self._geocode_candidate(candidate)
            results = data.get("results") or []

            if results:
                item = results[0]
                label = self._format_location(item, fallback=location)
                return float(item["latitude"]), float(item["longitude"]), label

        raise RuntimeError(f"Could not find weather location: {location}")

    def _location_candidates(self, location):
        candidates = [location]

        if "," in location:
            candidates.append(location.split(",", 1)[0].strip())

        seen = set()
        unique = []

        for candidate in candidates:
            key = candidate.lower()

            if candidate and key not in seen:
                unique.append(candidate)
                seen.add(key)

        return unique

    def _geocode_candidate(self, location):
        params = urllib.parse.urlencode(
            {
                "name": location,
                "count": 1,
                "language": "en",
                "format": "json"
            }
        )
        return self._get_json(f"{self.geocode_url}?{params}")

    def _forecast(self, latitude, longitude):
        params = urllib.parse.urlencode(
            {
                "latitude": latitude,
                "longitude": longitude,
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
                "precipitation_unit": "inch",
                "timezone": os.getenv("ENTITY_TIMEZONE", "America/New_York"),
                "current": (
                    "temperature_2m,apparent_temperature,"
                    "weather_code,wind_speed_10m"
                ),
                "daily": (
                    "temperature_2m_max,temperature_2m_min,"
                    "precipitation_probability_max,weather_code"
                ),
                "forecast_days": 1
            }
        )
        return self._get_json(f"{self.forecast_url}?{params}")

    def _report_from_payload(self, payload, label):
        current = payload.get("current", {})
        daily = payload.get("daily", {})
        daily_codes = daily.get("weather_code") or []
        current_code = current.get("weather_code")

        if current_code is None and daily_codes:
            current_code = daily_codes[0]

        return WeatherReport(
            location=label,
            temperature_f=self._number(current.get("temperature_2m")),
            apparent_temperature_f=self._number(
                current.get("apparent_temperature")
            ),
            precipitation_probability=self._integer_first(
                daily.get("precipitation_probability_max")
            ),
            wind_speed_mph=self._number(current.get("wind_speed_10m")),
            condition=self._condition(current_code),
            high_f=self._number_first(daily.get("temperature_2m_max")),
            low_f=self._number_first(daily.get("temperature_2m_min"))
        )

    def _get_json(self, url):
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "EntityWeather/1.0 local personal assistant"
            }
        )

        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def _format_location(self, item, fallback):
        parts = [
            item.get("name"),
            item.get("admin1"),
            item.get("country")
        ]
        label = ", ".join(part for part in parts if part)
        return label or fallback

    def _condition(self, code):
        try:
            code = int(code)
        except (TypeError, ValueError):
            return ""

        conditions = {
            0: "Clear",
            1: "Mostly clear",
            2: "Partly cloudy",
            3: "Overcast",
            45: "Fog",
            48: "Depositing rime fog",
            51: "Light drizzle",
            53: "Drizzle",
            55: "Heavy drizzle",
            56: "Light freezing drizzle",
            57: "Freezing drizzle",
            61: "Light rain",
            63: "Rain",
            65: "Heavy rain",
            66: "Light freezing rain",
            67: "Freezing rain",
            71: "Light snow",
            73: "Snow",
            75: "Heavy snow",
            77: "Snow grains",
            80: "Light rain showers",
            81: "Rain showers",
            82: "Heavy rain showers",
            85: "Light snow showers",
            86: "Snow showers",
            95: "Thunderstorm",
            96: "Thunderstorm with hail",
            99: "Thunderstorm with heavy hail"
        }
        return conditions.get(code, f"Weather code {code}")

    def _number_first(self, values):
        if not values:
            return None

        return self._number(values[0])

    def _integer_first(self, values):
        number = self._number_first(values)

        if number is None:
            return None

        return int(round(number))

    def _number(self, value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _env_bool(self, name, default=False):
        raw = os.getenv(name)

        if raw is None:
            return default

        return raw.lower().strip() in {
            "1",
            "true",
            "yes",
            "on"
        }

    def _env_int(self, name, default, minimum):
        try:
            value = int(os.getenv(name, str(default)))
        except ValueError:
            value = default

        return max(minimum, value)
