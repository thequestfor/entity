"""Native hazard observations, geographic change detection, and forecast features."""

import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from agent.intelligence.store import utc_now


BACKFILL_NAME = "native-geospatial-v1"
FEATURE_VERSION = "geospatial-prediction-v1"
AUTHORITATIVE_SOURCES = {
    "usgs_earthquakes", "nasa_eonet", "nasa_firms_wildfires",
    "gdacs", "nws_alerts"
}
FEATURE_TYPES = {
    "earthquake": "earthquake", "eq": "earthquake",
    "wildfire": "wildfire", "wildfires": "wildfire", "fires": "wildfire",
    "flood": "flood", "floods": "flood",
    "severe-storms": "storm", "storm": "storm", "cyclones": "storm",
    "volcano": "volcano", "volcanoes": "volcano",
    "drought": "drought", "droughts": "drought",
    "weather-alert": "weather"
}
TTL_DAYS = {
    "earthquake": 14, "wildfire": 7, "flood": 7, "storm": 5,
    "volcano": 30, "drought": 45, "weather": 3
}


def _parse_time(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value) / (1000 if value > 10_000_000_000 else 1), UTC)
        except (ValueError, OSError, OverflowError):
            return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def _iso(value):
    parsed = _parse_time(value)
    return parsed.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z") if parsed else None


def _number(value, default=None):
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _json_load(value, default):
    try:
        return json.loads(value or "")
    except (TypeError, ValueError):
        return default


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _country(metadata):
    raw = metadata.get("country") or metadata.get("country_name") or metadata.get("countries") or ""
    if isinstance(raw, list):
        raw = raw[0] if raw else ""
    if isinstance(raw, dict):
        raw = raw.get("name") or raw.get("title") or raw.get("iso3") or ""
    name = str(raw or "").strip()[:120]
    code = str(metadata.get("country_code") or "").strip().upper()[:3]
    return code, name


def _coordinates(geometry, fallback_latitude, fallback_longitude):
    if not isinstance(geometry, dict):
        geometry = {}
    geometry_type = str(geometry.get("type") or "Point")[:30]
    coordinates = geometry.get("coordinates")
    if coordinates in (None, []):
        coordinates = [fallback_longitude, fallback_latitude]
        geometry_type = "Point"
    safe_geometry = {"type": geometry_type, "coordinates": coordinates}
    points = []

    def visit(value, depth=0):
        if depth > 8 or len(points) >= 5000 or not isinstance(value, list):
            return
        if len(value) >= 2 and all(isinstance(item, (int, float)) for item in value[:2]):
            lon, lat = float(value[0]), float(value[1])
            if -180 <= lon <= 180 and -90 <= lat <= 90:
                points.append((lat, lon))
            return
        for item in value:
            visit(item, depth + 1)

    visit(coordinates)
    if not points and fallback_latitude is not None and fallback_longitude is not None:
        points = [(fallback_latitude, fallback_longitude)]
        safe_geometry = {"type": "Point", "coordinates": [fallback_longitude, fallback_latitude]}
    if not points:
        return None
    latitudes = [point[0] for point in points]
    longitudes = [point[1] for point in points]
    centroid = (sum(latitudes) / len(latitudes), sum(longitudes) / len(longitudes))
    bbox = (min(longitudes), min(latitudes), max(longitudes), max(latitudes))
    encoded = json.dumps(safe_geometry, separators=(",", ":"), default=str)
    if len(encoded) > 250_000:
        safe_geometry = {"type": "Point", "coordinates": [centroid[1], centroid[0]]}
    return safe_geometry, centroid, bbox


def _feature_type(category, metadata):
    category = str(category or "").strip().lower()
    if category in FEATURE_TYPES:
        return FEATURE_TYPES[category]
    event = str(metadata.get("event_type") or metadata.get("event") or "").lower()
    for token, feature_type in (
        ("earthquake", "earthquake"), ("wildfire", "wildfire"),
        ("fire", "wildfire"), ("flood", "flood"), ("storm", "storm"),
        ("cyclone", "storm"), ("hurricane", "storm"), ("volcano", "volcano"),
        ("drought", "drought")
    ):
        if token in event:
            return feature_type
    return ""


def _severity(feature_type, metadata):
    label = str(metadata.get("alert_level") or metadata.get("alert") or metadata.get("severity") or metadata.get("confidence") or "").strip()
    label_lower = label.lower()
    if feature_type == "earthquake":
        magnitude = _number(metadata.get("magnitude"), 0.0)
        return min(1.0, max(0.0, magnitude / 8.0)), label or (f"M{magnitude:g}" if magnitude else "")
    if feature_type == "wildfire":
        frp = _number(metadata.get("frp"), 0.0)
        confidence = _number(metadata.get("confidence"))
        if confidence is None:
            confidence = {"low": .35, "nominal": .65, "high": .9}.get(label_lower, .55)
        elif confidence > 1:
            confidence /= 100
        return min(1.0, max(confidence, min(1.0, frp / 100))), label
    mapped = {"extreme": 1.0, "red": 1.0, "severe": .85, "orange": .72, "moderate": .58, "green": .35, "minor": .3}
    return mapped.get(label_lower, .5), label


def _haversine(first, second):
    lat1, lon1 = map(math.radians, first)
    lat2, lon2 = map(math.radians, second)
    value = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 6371.0088 * 2 * math.asin(min(1, math.sqrt(value)))


class GeospatialIntelligenceEngine:
    """Incrementally materialize authoritative geographic observations."""

    def __init__(self, store, enabled=True, batch_size=100):
        self.store = store
        self.enabled = bool(enabled)
        self.batch_size = max(1, min(500, int(batch_size)))

    def run_batch(self):
        if not self.enabled:
            return {"processed": 0, "features": 0, "observations": 0}
        now = utc_now()
        with self.store._connect() as connection:
            state = connection.execute(
                "SELECT * FROM geospatial_backfill_state WHERE name=?", (BACKFILL_NAME,)
            ).fetchone()
            if not state:
                connection.execute(
                    "INSERT INTO geospatial_backfill_state (name,started_at,updated_at) VALUES (?,?,?)",
                    (BACKFILL_NAME, now, now)
                )
                cursor = 0
            else:
                cursor = int(state["cursor_version_id"])
            rows = connection.execute(
                """SELECT versions.id version_id,versions.metadata version_metadata,
                       versions.published_at version_published_at,versions.captured_at,
                       documents.id document_id,documents.source_id,documents.external_id,
                       documents.category,documents.latitude,documents.longitude,
                       documents.status document_status,sources.kind source_kind,
                       sources.credibility,
                       situation_documents.situation_id,
                       situations.location_country_code,situations.location_country_name
                   FROM document_versions versions
                   JOIN documents ON documents.id=versions.document_id
                   JOIN sources ON sources.id=documents.source_id
                   LEFT JOIN situation_documents ON situation_documents.document_id=documents.id
                   LEFT JOIN situations ON situations.id=situation_documents.situation_id
                   WHERE versions.id>? AND (
                     documents.source_id IN ('usgs_earthquakes','nasa_eonet','nasa_firms_wildfires','gdacs','nws_alerts')
                     OR sources.kind IN ('natural_hazard','wildfire','weather_alert'))
                   ORDER BY versions.id LIMIT ?""",
                (cursor, self.batch_size)
            ).fetchall()
            features = observations = 0
            for row in rows:
                result = self._process(connection, dict(row), now)
                features += int(result[0])
                observations += int(result[1])
            if rows:
                connection.execute(
                    """UPDATE geospatial_backfill_state SET cursor_version_id=?,processed=processed+?,
                       features_created=features_created+?,observations_created=observations_created+?,
                       completed=0,last_error='',updated_at=? WHERE name=?""",
                    (rows[-1]["version_id"], len(rows), features, observations, now, BACKFILL_NAME)
                )
            else:
                connection.execute(
                    """UPDATE geospatial_backfill_state SET completed=1,completed_at=COALESCE(completed_at,?),
                       updated_at=? WHERE name=?""", (now, now, BACKFILL_NAME)
                )
            self._refresh_cell_anomalies(connection, now)
            self._refresh_country_profiles(connection, now, limit=30)
        return {"processed": len(rows), "features": features, "observations": observations}

    def _process(self, connection, row, now):
        metadata = _json_load(row.get("version_metadata"), {})
        feature_type = _feature_type(row.get("category"), metadata)
        if not feature_type:
            return False, False
        latitude = _number(row.get("latitude"))
        longitude = _number(row.get("longitude"))
        if latitude is not None and not -90 <= latitude <= 90:
            latitude = None
        if longitude is not None and not -180 <= longitude <= 180:
            longitude = None
        geometry = metadata.get("geometry") or {}
        spatial = _coordinates(geometry, latitude, longitude)
        if not spatial:
            return False, False
        geometry, centroid, bbox = spatial
        severity, severity_label = _severity(feature_type, metadata)
        country_code, country_name = _country(metadata)
        country_code = country_code or str(row.get("location_country_code") or "")
        country_name = country_name or str(row.get("location_country_name") or "")
        observed = _iso(row.get("version_published_at")) or _iso(row.get("captured_at")) or now
        started = _iso(metadata.get("onset") or metadata.get("date")) or observed
        explicit_expiry = _iso(metadata.get("expires") or metadata.get("closed_at"))
        expiry = explicit_expiry or (datetime.fromisoformat(observed.replace("Z", "+00:00")) + timedelta(days=TTL_DAYS.get(feature_type, 7))).isoformat(timespec="seconds").replace("+00:00", "Z")
        external_id = str(row.get("external_id") or row["document_id"])
        feature_id = hashlib.sha256(f"{row['source_id']}:{external_id}".encode()).hexdigest()
        grid_key = f"z6:{math.floor((centroid[0]+90)*2)}:{math.floor((centroid[1]+180)*2)}"
        properties = {
            key: metadata.get(key) for key in (
                "magnitude", "depth_km", "significance", "tsunami", "alert",
                "frp", "brightness_kelvin", "confidence", "event", "event_type",
                "severity", "certainty", "urgency", "area", "satellite_source"
            ) if metadata.get(key) not in (None, "")
        }
        existing = connection.execute("SELECT * FROM geo_features WHERE id=?", (feature_id,)).fetchone()
        connection.execute(
            """INSERT INTO geo_features (id,source_id,external_id,document_id,situation_id,feature_type,
               geometry_type,geometry,centroid_latitude,centroid_longitude,bbox_west,bbox_south,bbox_east,bbox_north,
               grid_key,country_code,country_name,severity,severity_label,confidence,authoritative,status,
               started_at,observed_at,expires_at,properties,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET document_id=excluded.document_id,
               situation_id=COALESCE(excluded.situation_id,geo_features.situation_id),feature_type=excluded.feature_type,
               geometry_type=excluded.geometry_type,geometry=excluded.geometry,centroid_latitude=excluded.centroid_latitude,
               centroid_longitude=excluded.centroid_longitude,bbox_west=excluded.bbox_west,bbox_south=excluded.bbox_south,
               bbox_east=excluded.bbox_east,bbox_north=excluded.bbox_north,grid_key=excluded.grid_key,
               country_code=COALESCE(NULLIF(excluded.country_code,''),geo_features.country_code),
               country_name=COALESCE(NULLIF(excluded.country_name,''),geo_features.country_name),
               severity=excluded.severity,severity_label=excluded.severity_label,confidence=excluded.confidence,
               status=excluded.status,observed_at=excluded.observed_at,expires_at=excluded.expires_at,
               properties=excluded.properties,updated_at=excluded.updated_at""",
            (feature_id,row["source_id"],external_id,row["document_id"],row.get("situation_id"),feature_type,
             geometry.get("type","Point"),json.dumps(geometry,separators=(",",":")),centroid[0],centroid[1],
             bbox[0],bbox[1],bbox[2],bbox[3],grid_key,country_code,country_name,severity,severity_label,
             max(.1,min(1,float(row.get("credibility") or .5))),int(row["source_id"] in AUTHORITATIVE_SOURCES),
             "closed" if row.get("document_status") in {"closed","expired"} else "active",started,observed,expiry,
             json.dumps(properties,separators=(",",":"),default=str),now,now)
        )
        observation = {"geometry": geometry, "severity": severity, "properties": properties, "observed": observed}
        observation_hash = _hash(observation)
        inserted = connection.execute(
            """INSERT OR IGNORE INTO geo_feature_observations
               (feature_id,document_version_id,observed_at,latitude,longitude,severity,confidence,geometry,
                properties,observation_hash,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (feature_id,row["version_id"],observed,centroid[0],centroid[1],severity,
             max(.1,min(1,float(row.get("credibility") or .5))),json.dumps(geometry,separators=(",",":")),
             json.dumps(properties,separators=(",",":"),default=str),observation_hash,now)
        ).rowcount > 0
        if inserted:
            self._update_cell(connection, feature_type, grid_key, centroid, severity, row, observed, now)
            self._detect_feature_change(connection, feature_id, row.get("situation_id"), country_name, existing, centroid, severity, observed, now)
        return existing is None, inserted

    def _update_cell(self, connection, feature_type, grid_key, centroid, severity, row, observed, now):
        if feature_type not in {"wildfire", "earthquake", "flood", "storm"}:
            return
        window = observed[:10] + "T00:00:00Z"
        confidence = max(.1,min(1,float(row.get("credibility") or .5)))
        connection.execute(
            """INSERT INTO geo_cells (cell_key,feature_type,window_start,detection_count,max_severity,
               average_confidence,centroid_latitude,centroid_longitude,latest_observed_at,updated_at)
               VALUES (?,?,?,1,?,?,?,?,?,?)
               ON CONFLICT(cell_key,feature_type,window_start) DO UPDATE SET
               average_confidence=((geo_cells.average_confidence*geo_cells.detection_count)+excluded.average_confidence)/(geo_cells.detection_count+1),
               detection_count=geo_cells.detection_count+1,max_severity=MAX(geo_cells.max_severity,excluded.max_severity),
               centroid_latitude=((geo_cells.centroid_latitude*geo_cells.detection_count)+excluded.centroid_latitude)/(geo_cells.detection_count+1),
               centroid_longitude=((geo_cells.centroid_longitude*geo_cells.detection_count)+excluded.centroid_longitude)/(geo_cells.detection_count+1),
               latest_observed_at=MAX(geo_cells.latest_observed_at,excluded.latest_observed_at),updated_at=excluded.updated_at""",
            (grid_key,feature_type,window,severity,confidence,centroid[0],centroid[1],observed,now)
        )

    def _detect_feature_change(self, connection, feature_id, situation_id, country_name, existing, centroid, severity, observed, now):
        if not existing:
            return
        previous = (float(existing["centroid_latitude"] or centroid[0]), float(existing["centroid_longitude"] or centroid[1]))
        movement = _haversine(previous, centroid)
        severity_change = severity - float(existing["severity"] or 0)
        if movement < 50 and severity_change < .2:
            return
        score = min(1.0, max(movement / 500, severity_change))
        kind = "feature-movement" if movement >= 50 else "severity-increase"
        anomaly_id = hashlib.sha256(f"{feature_id}:{kind}:{observed[:13]}".encode()).hexdigest()
        evidence = {"movement_km": round(movement,2), "severity_change": round(severity_change,4), "feature_id": feature_id}
        connection.execute(
            """INSERT OR IGNORE INTO geo_anomalies (id,feature_id,situation_id,country_key,anomaly_type,
               expected_value,observed_value,anomaly_score,severity,confidence,evidence,status,first_seen_at,
               last_seen_at,expires_at,method) VALUES (?,?,?,?,?,?,?,?,?,?,?,'active',?,?,?,?)""",
            (anomaly_id,feature_id,situation_id,_country_key(country_name),kind,
             float(existing["severity"] or 0),severity,score,max(severity,score),
             min(float(existing["confidence"] or .5),.95),json.dumps(evidence,separators=(",",":")),
             observed,observed,(datetime.now(UTC)+timedelta(days=7)).isoformat(timespec="seconds").replace("+00:00","Z"),
             "bounded-change-v1")
        )

    def _refresh_cell_anomalies(self, connection, now):
        rows = connection.execute(
            """SELECT current.*,
               (SELECT AVG(previous.detection_count) FROM geo_cells previous
                WHERE previous.cell_key=current.cell_key AND previous.feature_type=current.feature_type
                  AND previous.window_start<current.window_start) baseline
               FROM geo_cells current WHERE current.window_start>=date('now','-1 day')
               ORDER BY current.detection_count DESC LIMIT 100"""
        ).fetchall()
        for row in rows:
            baseline = float(row["baseline"] or 0)
            observed = float(row["detection_count"] or 0)
            if observed < 3 or (baseline and observed < baseline * 2):
                continue
            score = min(1.0, (observed - baseline) / max(3.0, baseline * 3 or 3.0))
            anomaly_id = hashlib.sha256(f"cell:{row['cell_key']}:{row['feature_type']}:{row['window_start']}".encode()).hexdigest()
            connection.execute(
                """INSERT OR IGNORE INTO geo_anomalies (id,country_key,anomaly_type,expected_value,
                   observed_value,anomaly_score,severity,confidence,evidence,status,first_seen_at,last_seen_at,
                   expires_at,method) VALUES (?,'',?,?,?,?,?,?,?,'active',?,?,?,'cell-baseline-v1')""",
                (anomaly_id,f"{row['feature_type']}-density",baseline,observed,score,
                 max(score,float(row["max_severity"] or 0)),float(row["average_confidence"] or .5),
                 json.dumps({"cell_key":row["cell_key"],"feature_type":row["feature_type"]}),
                 now,now,(datetime.now(UTC)+timedelta(days=2)).isoformat(timespec="seconds").replace("+00:00","Z"))
            )
        connection.execute("UPDATE geo_anomalies SET status='expired' WHERE status='active' AND expires_at<?", (now,))

    def _refresh_country_profiles(self, connection, now, limit=30):
        countries = connection.execute(
            """SELECT names.country_name FROM (
                 SELECT country_name FROM geo_features WHERE country_name!=''
                 UNION SELECT location_country_name AS country_name
                   FROM situations WHERE location_country_name!=''
               ) names LEFT JOIN country_profiles profiles
                 ON profiles.country_name=names.country_name
               ORDER BY profiles.updated_at IS NOT NULL,profiles.updated_at,names.country_name
               LIMIT ?""", (limit,)
        ).fetchall()
        for country_row in countries:
            country = country_row[0]
            key = _country_key(country)
            situations = connection.execute(
                """SELECT COUNT(*) total,SUM(status='active') active,SUM(status='contested') contested,
                   AVG(confidence) confidence FROM situations WHERE location_country_name=?""", (country,)
            ).fetchone()
            hazards = connection.execute(
                """SELECT feature_type,COUNT(*) count FROM geo_features
                   WHERE country_name=? AND status='active' AND (expires_at IS NULL OR expires_at>=?)
                   GROUP BY feature_type""", (country,now)
            ).fetchall()
            anomalies = connection.execute(
                "SELECT COUNT(*) FROM geo_anomalies WHERE country_key=? AND status='active'", (key,)
            ).fetchone()[0]
            forecasts = connection.execute(
                """SELECT COUNT(*) FROM forecasts JOIN situations ON situations.id=forecasts.situation_id
                   WHERE situations.location_country_name=? AND forecasts.status='active'""", (country,)
            ).fetchone()[0]
            dimensions = {row["feature_type"]: row["count"] for row in hazards}
            snapshot = {
                "active_situations":int(situations["active"] or 0),
                "contested_situations":int(situations["contested"] or 0),
                "active_hazards":sum(dimensions.values()),"anomaly_count":int(anomalies),
                "forecast_count":int(forecasts),"dimensions":dimensions
            }
            gaps = [name for name in ("earthquake","wildfire","flood","storm") if name not in dimensions]
            connection.execute(
                """INSERT INTO country_profiles (country_key,country_name,active_situations,contested_situations,
                   active_hazards,anomaly_count,forecast_count,average_confidence,dimensions,coverage_gaps,method,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(country_key) DO UPDATE SET
                   country_name=excluded.country_name,active_situations=excluded.active_situations,
                   contested_situations=excluded.contested_situations,active_hazards=excluded.active_hazards,
                   anomaly_count=excluded.anomaly_count,forecast_count=excluded.forecast_count,
                   average_confidence=excluded.average_confidence,dimensions=excluded.dimensions,
                   coverage_gaps=excluded.coverage_gaps,method=excluded.method,updated_at=excluded.updated_at""",
                (key,country,snapshot["active_situations"],snapshot["contested_situations"],
                 snapshot["active_hazards"],snapshot["anomaly_count"],snapshot["forecast_count"],
                 round(float(situations["confidence"] or 0),4),json.dumps(dimensions,separators=(",",":")),
                 json.dumps(gaps,separators=(",",":")),"evidence-rollup-v1",now)
            )
            digest = _hash(snapshot)
            connection.execute(
                "INSERT OR IGNORE INTO country_profile_snapshots (country_key,snapshot,snapshot_hash,observed_at) VALUES (?,?,?,?)",
                (key,json.dumps(snapshot,separators=(",",":")),digest,now)
            )


class GeospatialPredictionFeatures:
    """Freeze provenance-safe geographic inputs at forecast creation time."""

    def __init__(self, store):
        self.store = store

    def snapshot(self, situation_id, cutoff_at=None):
        cutoff_at = _iso(cutoff_at or utc_now())
        with self.store._connect() as connection:
            situation = connection.execute("SELECT * FROM situations WHERE id=?", (situation_id,)).fetchone()
            if not situation:
                return {}, [], _hash({})
            linked = connection.execute(
                """SELECT feature_type,severity,confidence,id,observed_at FROM geo_features
                   WHERE situation_id=? AND observed_at<=?""", (situation_id,cutoff_at)
            ).fetchall()
            nearby = []
            if situation["latitude"] is not None and situation["longitude"] is not None:
                nearby = connection.execute(
                    """SELECT id,feature_type,severity,confidence,centroid_latitude,centroid_longitude,observed_at
                       FROM geo_features WHERE observed_at<=? AND status='active'
                       AND centroid_latitude BETWEEN ? AND ? AND centroid_longitude BETWEEN ? AND ? LIMIT 500""",
                    (cutoff_at,float(situation["latitude"])-5,float(situation["latitude"])+5,
                     float(situation["longitude"])-5,float(situation["longitude"])+5)
                ).fetchall()
            distances = [
                _haversine((float(situation["latitude"]),float(situation["longitude"])),
                           (float(row["centroid_latitude"]),float(row["centroid_longitude"])))
                for row in nearby
            ] if nearby else []
            anomalies = connection.execute(
                """SELECT COUNT(*) count,MAX(severity) max_severity FROM geo_anomalies
                   WHERE status='active' AND (situation_id=? OR country_key=?) AND first_seen_at<=?""",
                (situation_id,_country_key(situation["location_country_name"]),cutoff_at)
            ).fetchone()
        counts = Counter(row["feature_type"] for row in linked)
        features = {
            "linked_hazard_count":len(linked),"linked_hazard_types":dict(counts),
            "maximum_hazard_severity":round(max([float(row["severity"]) for row in linked] or [0]),4),
            "nearby_hazard_count_500km":sum(distance<=500 for distance in distances),
            "nearest_hazard_km":round(min(distances),2) if distances else None,
            "active_geo_anomaly_count":int(anomalies["count"] or 0),
            "maximum_geo_anomaly_severity":round(float(anomalies["max_severity"] or 0),4),
            "country_attributed":bool(situation["location_country_name"]),
            "location_confidence":round(float(situation["location_confidence"] or 0),4)
        }
        feature_ids = sorted({row["id"] for row in linked} | {row["id"] for row in nearby if _haversine(
            (float(situation["latitude"]),float(situation["longitude"])),
            (float(row["centroid_latitude"]),float(row["centroid_longitude"]))) <= 500}) if nearby else sorted({row["id"] for row in linked})
        return features, feature_ids, _hash({"cutoff":cutoff_at,"features":features,"feature_ids":feature_ids})


def _country_key(value):
    return "".join(character for character in str(value or "").lower() if character.isalnum())[:120]
