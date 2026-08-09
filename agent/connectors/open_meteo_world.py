"""Bounded global forecast-grid connector backed by Open-Meteo."""

import math
import urllib.parse

from agent.connectors.base import JsonConnector
from agent.intelligence.models import ConnectorBatch, SourceItem
from agent.intelligence.store import utc_now


HOURLY_VARIABLES = (
    "temperature_2m",
    "precipitation",
    "wind_speed_10m",
    "wind_gusts_10m",
    "surface_pressure",
    "weather_code",
)


class OpenMeteoWorldConnector(JsonConnector):
    source_id = "open_meteo_world"
    name = "Open-Meteo Global Forecast"
    kind = "weather_forecast"
    base_url = "https://api.open-meteo.com/v1/forecast"
    credibility = 0.8
    poll_seconds = 21600

    def __init__(
        self,
        grid_degrees=30.0,
        horizon_hours=24,
        max_cells=200,
        batch_cells=25,
        poll_seconds=21600,
        **kwargs,
    ):
        super().__init__(max_items=max_cells, **kwargs)
        self.grid_degrees = max(5.0, min(90.0, float(grid_degrees)))
        self.horizon_hours = max(6, min(168, int(horizon_hours)))
        self.batch_cells = max(1, min(50, int(batch_cells)))
        self.poll_seconds = max(3600, int(poll_seconds))

    def poll(self, cursor=None):
        if not self.enabled:
            return ConnectorBatch(cursor=cursor or {})

        cells = _global_grid(self.grid_degrees, self.max_items)
        run_at = utc_now()
        items = []
        for offset in range(0, len(cells), self.batch_cells):
            batch = cells[offset:offset + self.batch_cells]
            payload = self.fetch_json(self._url(batch))
            responses = payload if isinstance(payload, list) else [payload]
            if len(responses) != len(batch):
                raise ValueError("Open-Meteo returned an unexpected location count")
            for requested, response in zip(batch, responses):
                item = self._item(requested, response, run_at)
                if item is not None:
                    items.append(item)

        return ConnectorBatch(items=items, cursor={
            "retrieved_at": run_at,
            "grid_degrees": self.grid_degrees,
            "cell_count": len(items),
            "horizon_hours": self.horizon_hours,
        })

    def _url(self, cells):
        params = urllib.parse.urlencode({
            "latitude": ",".join(_coordinate(lat) for lat, _ in cells),
            "longitude": ",".join(_coordinate(lon) for _, lon in cells),
            "hourly": ",".join(HOURLY_VARIABLES),
            "forecast_hours": self.horizon_hours + 1,
            "timezone": "UTC",
        })
        return f"{self.base_url}?{params}"

    def _item(self, requested, response, run_at):
        if not isinstance(response, dict):
            return None
        hourly = response.get("hourly") or {}
        times = hourly.get("time") or []
        if not times:
            return None
        wanted = sorted(set((0, 6, 12, self.horizon_hours)))
        forecasts = []
        for index in wanted:
            if index >= len(times):
                continue
            values = {"valid_at": _utc_time(times[index])}
            for variable in HOURLY_VARIABLES:
                series = hourly.get(variable) or []
                values[variable] = _number(series[index]) if index < len(series) else None
            forecasts.append(values)
        if not forecasts:
            return None

        requested_latitude, requested_longitude = requested
        latitude = _bounded_coordinate(
            response.get("latitude"), -90, 90, requested_latitude
        )
        longitude = _bounded_coordinate(
            response.get("longitude"), -180, 180, requested_longitude
        )
        external_id = f"grid:{_coordinate(requested_latitude)}:{_coordinate(requested_longitude)}"
        item_url = (
            "https://open-meteo.com/en/docs?"
            + urllib.parse.urlencode({
                "latitude": _coordinate(requested_latitude),
                "longitude": _coordinate(requested_longitude),
            })
        )
        return SourceItem(
            external_id=external_id,
            title=(
                "Open-Meteo forecast near "
                f"{requested_latitude:.1f}, {requested_longitude:.1f}"
            ),
            url=item_url,
            summary=(
                "Model-derived weather forecast for a coarse global grid cell; "
                "it is not a direct weather observation or an alert."
            ),
            published_at=run_at,
            category="weather-forecast",
            latitude=latitude,
            longitude=longitude,
            metadata={
                "epistemic_type": "forecast",
                "asset_type": "weather-grid-cell",
                "forecast_run_at": run_at,
                "requested_latitude": requested_latitude,
                "requested_longitude": requested_longitude,
                "grid_degrees": self.grid_degrees,
                "timezone": response.get("timezone") or "GMT",
                "elevation_m": _number(response.get("elevation")),
                "units": response.get("hourly_units") or {},
                "forecasts": forecasts,
                "geometry": {
                    "type": "Point",
                    "coordinates": [longitude, latitude],
                },
            },
        )


def _global_grid(spacing, limit):
    cells = []
    latitude = -75.0
    while latitude <= 75.000001:
        longitude = -180.0
        while longitude < 180.0:
            cells.append((round(latitude, 6), round(longitude, 6)))
            longitude += spacing
        latitude += spacing
    if len(cells) <= limit:
        return cells
    stride = len(cells) / limit
    return [cells[min(len(cells) - 1, math.floor(index * stride))] for index in range(limit)]


def _coordinate(value):
    text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return "0" if text == "-0" else text


def _number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _bounded_coordinate(value, minimum, maximum, fallback):
    number = _number(value)
    return number if number is not None and minimum <= number <= maximum else fallback


def _utc_time(value):
    text = str(value or "").strip()
    if not text:
        return ""
    if text.endswith("Z") or "+" in text[10:]:
        return text
    return text + ":00Z" if len(text) == 16 else text + "Z"
