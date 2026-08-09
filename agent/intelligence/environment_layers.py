"""Deterministic weather-forecast and infrastructure reference projections."""

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from agent.intelligence.store import utc_now


LANE = "environment-layers-v1"
METHOD = "environment-layer-projection-v1"
SOURCE_KINDS = ("weather_forecast", "infrastructure_reference")


@dataclass(frozen=True)
class EnvironmentLayerResult:
    processed: int = 0
    weather_cells: int = 0
    infrastructure_assets: int = 0
    versions: int = 0


class EnvironmentLayerEngine:
    """Materialize contextual layers without creating events or claims."""

    def __init__(self, store, enabled=True, batch_size=100):
        self.store = store
        self.enabled = bool(enabled)
        self.batch_size = max(1, min(500, int(batch_size)))

    def run_batch(self):
        if not self.enabled:
            return EnvironmentLayerResult()
        now = utc_now()
        with self.store._connect() as connection:
            state = connection.execute(
                "SELECT * FROM environment_layer_state WHERE lane=?", (LANE,)
            ).fetchone()
            if state:
                cursor = int(state["cursor_version_id"])
            else:
                connection.execute(
                    "INSERT INTO environment_layer_state (lane,started_at,updated_at) VALUES (?,?,?)",
                    (LANE, now, now),
                )
                cursor = 0

            selection = """SELECT versions.id version_id,versions.metadata version_metadata,
                       versions.published_at version_published_at,versions.captured_at,
                       documents.id document_id,documents.external_id,documents.title,
                       documents.status document_status,documents.latitude,documents.longitude,
                       documents.source_id,sources.kind source_kind,sources.credibility
                   FROM document_versions versions
                   JOIN documents ON documents.id=versions.document_id
                   JOIN sources ON sources.id=documents.source_id
                   WHERE {condition}
                     AND sources.kind IN ('weather_forecast','infrastructure_reference')"""
            recent_limit = min(20, max(1, self.batch_size // 5)) if self.batch_size > 1 else 0
            historical_limit = self.batch_size - recent_limit
            recent = connection.execute(
                selection.format(condition="NOT EXISTS (SELECT 1 FROM weather_forecast_versions weather WHERE weather.document_version_id=versions.id) AND NOT EXISTS (SELECT 1 FROM infrastructure_asset_versions assets WHERE assets.document_version_id=versions.id)")
                + " ORDER BY versions.id DESC LIMIT ?",
                (recent_limit,),
            ).fetchall() if recent_limit else []
            historical = connection.execute(
                selection.format(condition="versions.id>?")
                + " ORDER BY versions.id LIMIT ?",
                (cursor, historical_limit),
            ).fetchall()

            rows = []
            seen = set()
            for row in [*recent, *historical]:
                if row["version_id"] in seen:
                    continue
                seen.add(row["version_id"])
                rows.append(dict(row))

            weather_cells = assets = versions = 0
            for row in rows:
                if row["source_kind"] == "weather_forecast":
                    result = self._weather(connection, row, now)
                    weather_cells += result[0]
                    versions += result[1]
                else:
                    result = self._infrastructure(connection, row, now)
                    assets += result[0]
                    versions += result[1]

            if historical:
                connection.execute(
                    """UPDATE environment_layer_state SET cursor_version_id=?,
                       processed=processed+?,materialized=materialized+?,completed=0,
                       completed_at=NULL,last_error='',updated_at=? WHERE lane=?""",
                    (
                        historical[-1]["version_id"], len(rows),
                        weather_cells + assets, now, LANE,
                    ),
                )
            else:
                connection.execute(
                    """UPDATE environment_layer_state SET processed=processed+?,
                       materialized=materialized+?,completed=1,
                       completed_at=COALESCE(completed_at,?),last_error='',updated_at=?
                       WHERE lane=?""",
                    (len(rows), weather_cells + assets, now, now, LANE),
                )

        return EnvironmentLayerResult(
            processed=len(rows), weather_cells=weather_cells,
            infrastructure_assets=assets, versions=versions,
        )

    def _weather(self, connection, row, now):
        metadata = _json_load(row.get("version_metadata"), {})
        forecasts = metadata.get("forecasts") or []
        units = metadata.get("units") if isinstance(metadata.get("units"), dict) else {}
        latitude = _coordinate(row.get("latitude"), -90, 90)
        longitude = _coordinate(row.get("longitude"), -180, 180)
        if latitude is None or longitude is None:
            return 0, 0
        run_at = _time(metadata.get("forecast_run_at")) or _time(
            row.get("version_published_at")
        ) or row["captured_at"]
        grid_key = f"weather:{latitude:.4f}:{longitude:.4f}"
        materialized = version_count = 0
        for forecast in forecasts[:8]:
            if not isinstance(forecast, dict):
                continue
            valid_at = _time(forecast.get("valid_at"))
            if not valid_at:
                continue
            expires_at = _add_hours(valid_at, 6)
            values = {
                "temperature_c": _number(forecast.get("temperature_2m")),
                "precipitation_mm": _number(forecast.get("precipitation")),
                "wind_speed_kph": _number(forecast.get("wind_speed_10m")),
                "wind_gust_kph": _number(forecast.get("wind_gusts_10m")),
                "pressure_hpa": _number(forecast.get("surface_pressure")),
                "weather_code": _integer(forecast.get("weather_code")),
            }
            encoded = json.dumps(
                {"values": values, "units": units},
                sort_keys=True, separators=(",", ":"), default=str,
            )
            inserted = connection.execute(
                """INSERT OR IGNORE INTO weather_forecast_versions
                   (source_id,external_id,valid_at,document_version_id,
                    forecast_run_at,captured_at,forecast,created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    row["source_id"], row["external_id"], valid_at,
                    row["version_id"], run_at, row["captured_at"], encoded, now,
                ),
            ).rowcount
            version_count += int(inserted > 0)
            connection.execute(
                """INSERT INTO weather_forecast_cells
                   (source_id,external_id,valid_at,document_id,document_version_id,
                    latitude,longitude,grid_key,forecast_run_at,captured_at,
                    temperature_c,precipitation_mm,wind_speed_kph,wind_gust_kph,
                    pressure_hpa,weather_code,units,properties,expires_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(source_id,external_id,valid_at) DO UPDATE SET
                   document_id=excluded.document_id,
                   document_version_id=excluded.document_version_id,
                   latitude=excluded.latitude,longitude=excluded.longitude,
                   grid_key=excluded.grid_key,forecast_run_at=excluded.forecast_run_at,
                   captured_at=excluded.captured_at,
                   temperature_c=excluded.temperature_c,
                   precipitation_mm=excluded.precipitation_mm,
                   wind_speed_kph=excluded.wind_speed_kph,
                   wind_gust_kph=excluded.wind_gust_kph,
                   pressure_hpa=excluded.pressure_hpa,
                   weather_code=excluded.weather_code,units=excluded.units,
                   properties=excluded.properties,expires_at=excluded.expires_at,
                   updated_at=excluded.updated_at
                   WHERE excluded.forecast_run_at>=weather_forecast_cells.forecast_run_at""",
                (
                    row["source_id"], row["external_id"], valid_at,
                    row["document_id"], row["version_id"], latitude, longitude,
                    grid_key, run_at, row["captured_at"], values["temperature_c"],
                    values["precipitation_mm"], values["wind_speed_kph"],
                    values["wind_gust_kph"], values["pressure_hpa"],
                    values["weather_code"], json.dumps(units, separators=(",", ":")),
                    json.dumps({
                        "method": METHOD,
                        "epistemic_type": "forecast",
                        "grid_degrees": metadata.get("grid_degrees"),
                        "elevation_m": metadata.get("elevation_m"),
                    }, separators=(",", ":"), default=str),
                    expires_at, now,
                ),
            )
            materialized += 1
        return materialized, version_count

    def _infrastructure(self, connection, row, now):
        metadata = _json_load(row.get("version_metadata"), {})
        asset_type = str(metadata.get("asset_type") or "").strip().lower()
        if asset_type not in {"airport", "port"}:
            return 0, 0
        latitude = _coordinate(row.get("latitude"), -90, 90)
        longitude = _coordinate(row.get("longitude"), -180, 180)
        if latitude is None or longitude is None:
            return 0, 0
        asset_id = hashlib.sha256(
            f"infrastructure:{row['source_id']}:{row['external_id']}".encode()
        ).hexdigest()
        status = "retired" if row.get("document_status") in {"closed", "deleted", "expired"} else "active"
        identifiers = metadata.get("identifiers") if isinstance(metadata.get("identifiers"), dict) else {}
        properties = metadata.get("properties") if isinstance(metadata.get("properties"), dict) else {}
        for key in (
            "municipality", "region_code", "infrastructure_type",
            "scheduled_service", "elevation_ft",
        ):
            if metadata.get(key) not in (None, ""):
                properties[key] = metadata[key]
        geometry = metadata.get("geometry") if isinstance(metadata.get("geometry"), dict) else {
            "type": "Point", "coordinates": [longitude, latitude]
        }
        confidence = max(0.1, min(1.0, float(row.get("credibility") or 0.5)))
        observed_at = _time(row.get("version_published_at")) or row["captured_at"]
        connection.execute(
            """INSERT INTO infrastructure_assets
               (id,asset_type,name,country_code,country_name,latitude,longitude,
                geometry,identifiers,properties,source_id,confidence,observed_at,
                created_at,updated_at,external_id,status,document_id,
                document_version_id,source_updated_at,retired_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET asset_type=excluded.asset_type,
               name=excluded.name,country_code=excluded.country_code,
               country_name=excluded.country_name,latitude=excluded.latitude,
               longitude=excluded.longitude,geometry=excluded.geometry,
               identifiers=excluded.identifiers,properties=excluded.properties,
               confidence=excluded.confidence,observed_at=excluded.observed_at,
               updated_at=excluded.updated_at,external_id=excluded.external_id,
               status=excluded.status,document_id=excluded.document_id,
               document_version_id=excluded.document_version_id,
               source_updated_at=excluded.source_updated_at,
               retired_at=excluded.retired_at
               WHERE excluded.document_version_id>=infrastructure_assets.document_version_id""",
            (
                asset_id, asset_type, str(metadata.get("name") or row["title"])[:300],
                str(metadata.get("country_code") or "").upper()[:3],
                str(metadata.get("country") or "")[:120], latitude, longitude,
                json.dumps(geometry, separators=(",", ":"), default=str),
                json.dumps(identifiers, separators=(",", ":"), default=str),
                json.dumps(properties, separators=(",", ":"), default=str),
                row["source_id"], confidence, observed_at, now, now,
                row["external_id"], status, row["document_id"], row["version_id"],
                observed_at, now if status == "retired" else None,
            ),
        )
        snapshot = json.dumps({
            "asset_type": asset_type,
            "name": metadata.get("name") or row["title"],
            "country_code": metadata.get("country_code") or "",
            "latitude": latitude, "longitude": longitude,
            "geometry": geometry, "identifiers": identifiers,
            "properties": properties, "status": status,
            "method": METHOD,
        }, sort_keys=True, separators=(",", ":"), default=str)
        inserted = connection.execute(
            """INSERT OR IGNORE INTO infrastructure_asset_versions
               (asset_id,document_version_id,snapshot,captured_at,created_at)
               VALUES (?,?,?,?,?)""",
            (asset_id, row["version_id"], snapshot, row["captured_at"], now),
        ).rowcount
        return 1, int(inserted > 0)


def _json_load(value, default):
    try:
        return json.loads(value or "")
    except (TypeError, ValueError):
        return default


def _number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _integer(value):
    number = _number(value)
    return int(number) if number is not None else None


def _coordinate(value, minimum, maximum):
    number = _number(value)
    return number if number is not None and minimum <= number <= maximum else None


def _time(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _add_hours(value, hours):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (parsed + timedelta(hours=hours)).isoformat(timespec="seconds").replace("+00:00", "Z")
