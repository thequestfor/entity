"""Bounded projection of retained evidence into the universal world graph."""

import hashlib
import json
from dataclasses import dataclass

from agent.intelligence.store import utc_now


DOCUMENT_LANE = "document-observations-v1"
SITUATION_LANE = "situation-events-v1"
METHOD = "direct-world-graph-projection-v1"


@dataclass(frozen=True)
class WorldGraphResult:
    processed: int = 0
    events: int = 0
    observations: int = 0
    entities: int = 0
    relations: int = 0


class WorldEventGraphEngine:
    """Project stored facts without attempting cross-event semantic fusion."""

    def __init__(self, store, enabled=True, batch_size=100):
        self.store = store
        self.enabled = bool(enabled)
        self.batch_size = max(2, min(500, int(batch_size)))

    def run_batch(self):
        if not self.enabled:
            return WorldGraphResult()
        situation_limit = max(1, self.batch_size // 4)
        document_limit = self.batch_size - situation_limit
        with self.store._connect() as connection:
            now = utc_now()
            situation_result = self._run_situations(
                connection, situation_limit, now
            )
            document_result = self._run_documents(
                connection, document_limit, now
            )
        return WorldGraphResult(
            processed=situation_result.processed + document_result.processed,
            events=situation_result.events + document_result.events,
            observations=document_result.observations,
            entities=situation_result.entities + document_result.entities,
            relations=situation_result.relations + document_result.relations
        )

    def _state(self, connection, lane, now):
        row = connection.execute(
            "SELECT * FROM world_graph_backfill_state WHERE lane=?", (lane,)
        ).fetchone()
        if row:
            return int(row["cursor_id"])
        connection.execute(
            """INSERT INTO world_graph_backfill_state
               (lane,started_at,updated_at) VALUES (?,?,?)""",
            (lane, now, now)
        )
        return 0

    def _finish_lane(self, connection, lane, rows, created, now,
                     processed_count=None):
        processed_count = len(rows) if processed_count is None else int(processed_count)
        if rows:
            connection.execute(
                """UPDATE world_graph_backfill_state SET cursor_id=?,
                   processed=processed+?,created_count=created_count+?,
                   completed=0,completed_at=NULL,last_error='',updated_at=?
                   WHERE lane=?""",
                (rows[-1]["cursor_id"], processed_count, created, now, lane)
            )
        else:
            connection.execute(
                """UPDATE world_graph_backfill_state SET completed=1,
                   processed=processed+?,created_count=created_count+?,
                   completed_at=COALESCE(completed_at,?),updated_at=?
                   WHERE lane=?""", (processed_count, created, now, now, lane)
            )

    def _run_situations(self, connection, limit, now):
        cursor = self._state(connection, SITUATION_LANE, now)
        rows = connection.execute(
            """SELECT versions.id cursor_id,versions.situation_id,
                      situations.title,situations.summary,situations.category,
                      situations.status,situations.confidence,
                      situations.latitude,situations.longitude,
                      situations.location_country_code,
                      situations.location_country_name,
                      situations.location_confidence,
                      situations.first_seen_at,situations.last_seen_at,
                      situations.created_at,situations.updated_at
               FROM situation_versions versions
               JOIN situations ON situations.id=versions.situation_id
               WHERE versions.id>? ORDER BY versions.id LIMIT ?""",
            (cursor, limit)
        ).fetchall()
        events = entities = relations = 0
        for row in rows:
            result = self._upsert_situation_event(connection, dict(row), now)
            events += result[0]
            entities += result[1]
            relations += result[2]
        self._finish_lane(connection, SITUATION_LANE, rows, events, now)
        return WorldGraphResult(
            processed=len(rows), events=events, entities=entities,
            relations=relations
        )

    def _run_documents(self, connection, limit, now):
        cursor = self._state(connection, DOCUMENT_LANE, now)
        recent_limit = min(20, max(1, limit // 5)) if limit > 1 else 0
        historical_limit = limit - recent_limit
        selection = """SELECT versions.id cursor_id,versions.id version_id,
                   versions.title,versions.summary,versions.published_at,
                   versions.captured_at,versions.content_hash,
                   versions.metadata version_metadata,
                   documents.id document_id,documents.source_id,
                   documents.external_id,documents.category,documents.status,
                   documents.latitude,documents.longitude,
                   situation_documents.situation_id,
                   geo_features.id geo_feature_id
                 FROM document_versions versions
                 JOIN documents ON documents.id=versions.document_id
                 JOIN sources ON sources.id=documents.source_id
                 LEFT JOIN situation_documents
                   ON situation_documents.document_id=documents.id
                 LEFT JOIN geo_features ON geo_features.document_id=documents.id
                 WHERE {condition}
                   AND sources.kind NOT IN (
                     'private_mail', 'prediction_market',
                     'weather_forecast', 'infrastructure_reference'
                   )"""
        recent = connection.execute(
            selection.format(
                condition="NOT EXISTS (SELECT 1 FROM world_event_observations observations WHERE observations.document_version_id=versions.id)"
            ) + " ORDER BY versions.id DESC LIMIT ?", (recent_limit,)
        ).fetchall() if recent_limit else []
        historical = connection.execute(
            selection.format(condition="versions.id>?")
            + " ORDER BY versions.id LIMIT ?", (cursor, historical_limit)
        ).fetchall()
        rows = []
        seen = set()
        for row in [*recent, *historical]:
            if row["version_id"] in seen:
                continue
            seen.add(row["version_id"])
            rows.append(row)
        events = observations = entities = relations = 0
        for row in rows:
            values = dict(row)
            event_id = ""
            if values.get("situation_id"):
                situation = connection.execute(
                    "SELECT * FROM situations WHERE id=?",
                    (values["situation_id"],)
                ).fetchone()
                if situation:
                    result = self._upsert_situation_event(
                        connection, dict(situation), now,
                        geo_feature_id=values.get("geo_feature_id")
                    )
                    event_id = _event_id("situation", values["situation_id"])
                    events += result[0]
                    entities += result[1]
                    relations += result[2]
            elif values.get("geo_feature_id"):
                feature = connection.execute(
                    "SELECT * FROM geo_features WHERE id=?",
                    (values["geo_feature_id"],)
                ).fetchone()
                if feature:
                    event_id = self._upsert_feature_event(
                        connection, dict(feature), values["title"], now
                    )
                    events += 1
            observations += self._upsert_observation(
                connection, values, event_id or None, now
            )
            if event_id:
                connection.execute(
                    """UPDATE world_events SET
                       observation_count=(SELECT COUNT(*) FROM world_event_observations WHERE world_event_id=?),
                       source_count=(SELECT COUNT(DISTINCT source_id) FROM world_event_observations WHERE world_event_id=?),
                       updated_at=? WHERE id=?""",
                    (event_id, event_id, now, event_id)
                )
        self._finish_lane(
            connection, DOCUMENT_LANE, historical,
            events + observations, now, processed_count=len(rows)
        )
        return WorldGraphResult(
            processed=len(rows), events=events, observations=observations,
            entities=entities, relations=relations
        )

    def _upsert_situation_event(self, connection, situation, now,
                                geo_feature_id=None):
        situation_id = situation["situation_id"] if "situation_id" in situation else situation["id"]
        event_id = _event_id("situation", situation_id)
        latitude = situation.get("latitude")
        longitude = situation.get("longitude")
        geometry = (
            {"type": "Point", "coordinates": [longitude, latitude]}
            if latitude is not None and longitude is not None else {}
        )
        existed = connection.execute(
            "SELECT 1 FROM world_events WHERE id=?", (event_id,)
        ).fetchone()
        connection.execute(
            """INSERT INTO world_events
               (id,event_type,category,title,status,severity,confidence,latitude,
                longitude,geometry,country_code,country_name,started_at,
                first_seen_at,last_seen_at,situation_id,geo_feature_id,
                properties,method,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET event_type=excluded.event_type,
               category=excluded.category,title=excluded.title,status=excluded.status,
               confidence=excluded.confidence,latitude=excluded.latitude,
               longitude=excluded.longitude,geometry=excluded.geometry,
               country_code=excluded.country_code,country_name=excluded.country_name,
               started_at=excluded.started_at,last_seen_at=excluded.last_seen_at,
               geo_feature_id=COALESCE(excluded.geo_feature_id,world_events.geo_feature_id),
               properties=excluded.properties,updated_at=excluded.updated_at""",
            (event_id,situation.get("category") or "general",
             situation.get("category") or "general",situation.get("title") or "Untitled event",
             situation.get("status") or "active",0.0,
             _bounded(situation.get("confidence"), .5),latitude,longitude,
             _json(geometry),situation.get("location_country_code") or "",
             situation.get("location_country_name") or "",
             situation.get("first_seen_at"),situation.get("first_seen_at") or now,
             situation.get("last_seen_at") or now,situation_id,geo_feature_id,
             _json({"summary": situation.get("summary") or "",
                    "location_confidence": situation.get("location_confidence") or 0}),
             METHOD,situation.get("created_at") or now,now)
        )
        entities = relations = 0
        country = str(situation.get("location_country_name") or "").strip()
        if country:
            entity_id, created = self._upsert_country_entity(
                connection, country,
                situation.get("location_country_code") or "", now
            )
            entities += created
            relations += self._upsert_relation(
                connection, event_id, "located_in", entity_id,
                _bounded(situation.get("location_confidence"), .5), now
            )
        return (0 if existed else 1), entities, relations

    def _upsert_feature_event(self, connection, feature, title, now):
        event_id = _event_id("feature", feature["id"])
        connection.execute(
            """INSERT INTO world_events
               (id,event_type,category,title,status,severity,confidence,latitude,
                longitude,geometry,country_code,country_name,started_at,
                first_seen_at,last_seen_at,geo_feature_id,properties,method,
                created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET status=excluded.status,
               severity=excluded.severity,confidence=excluded.confidence,
               latitude=excluded.latitude,longitude=excluded.longitude,
               geometry=excluded.geometry,country_code=excluded.country_code,
               country_name=excluded.country_name,last_seen_at=excluded.last_seen_at,
               properties=excluded.properties,updated_at=excluded.updated_at""",
            (event_id,feature["feature_type"],feature["feature_type"],title,
             feature["status"],_bounded(feature["severity"],0),
             _bounded(feature["confidence"],.5),feature["centroid_latitude"],
             feature["centroid_longitude"],feature["geometry"],
             feature["country_code"],feature["country_name"],feature["started_at"],
             feature["created_at"],feature["observed_at"],feature["id"],
             feature["properties"],METHOD,feature["created_at"],now)
        )
        return event_id

    def _upsert_observation(self, connection, row, event_id, now):
        observation_id = hashlib.sha256(
            f"world-observation:{row['version_id']}".encode()
        ).hexdigest()
        metadata = _load_json(row.get("version_metadata"), {})
        geometry = metadata.get("geometry") if isinstance(metadata.get("geometry"), dict) else {}
        existed = connection.execute(
            "SELECT 1 FROM world_event_observations WHERE id=?",
            (observation_id,)
        ).fetchone()
        connection.execute(
            """INSERT INTO world_event_observations
               (id,world_event_id,document_version_id,document_id,source_id,
                external_id,observation_kind,occurred_at,published_at,captured_at,
                latitude,longitude,geometry,payload_hash,properties,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
               world_event_id=COALESCE(excluded.world_event_id,world_event_observations.world_event_id),
               properties=excluded.properties""",
            (observation_id,event_id,row["version_id"],row["document_id"],
             row["source_id"],row["external_id"],row["category"],
             metadata.get("onset") or row.get("published_at"),row.get("published_at"),
             row["captured_at"],row.get("latitude"),row.get("longitude"),
             _json(geometry),row["content_hash"],
             _json({"title":row.get("title") or "","summary":row.get("summary") or "",
                    "metadata":metadata,"document_status":row.get("status") or "active"}),now)
        )
        return 0 if existed else 1

    def _upsert_country_entity(self, connection, name, code, now):
        entity_id = _entity_id("country", code or name)
        existed = connection.execute(
            "SELECT 1 FROM world_entities WHERE id=?", (entity_id,)
        ).fetchone()
        connection.execute(
            """INSERT INTO world_entities
               (id,entity_type,canonical_name,country_code,identifiers,properties,
                confidence,first_seen_at,last_seen_at,method,created_at,updated_at)
               VALUES (?, 'country',?,?,?,?,1.0,?,?,?, ?,?)
               ON CONFLICT(id) DO UPDATE SET canonical_name=excluded.canonical_name,
               country_code=excluded.country_code,last_seen_at=excluded.last_seen_at,
               updated_at=excluded.updated_at""",
            (entity_id,name,str(code).upper()[:3],
             _json({"country_code":str(code).upper()[:3]}),"{}",now,now,
             "direct-country-attribution-v1",now,now)
        )
        normalized = _normalize(name)
        connection.execute(
            """INSERT OR IGNORE INTO world_entity_aliases
               (entity_id,alias,normalized_alias,confidence,created_at)
               VALUES (?,?,?,?,?)""", (entity_id,name,normalized,1.0,now)
        )
        return entity_id, 0 if existed else 1

    def _upsert_relation(self, connection, event_id, predicate, entity_id,
                         confidence, now):
        relation_id = hashlib.sha256(
            f"event:{event_id}:{predicate}:entity:{entity_id}:{METHOD}".encode()
        ).hexdigest()
        existed = connection.execute(
            "SELECT 1 FROM world_event_relations WHERE id=?", (relation_id,)
        ).fetchone()
        connection.execute(
            """INSERT INTO world_event_relations
               (id,subject_kind,subject_id,predicate,object_kind,object_id,
                confidence,causal_status,evidence_count,evidence,status,method,
                created_at,updated_at)
               VALUES (?,'event',?,?,'entity',?,?,'noncausal',0,'[]','active',?,?,?)
               ON CONFLICT(id) DO UPDATE SET confidence=excluded.confidence,
               updated_at=excluded.updated_at""",
            (relation_id,event_id,predicate,entity_id,confidence,METHOD,now,now)
        )
        return 0 if existed else 1


def _event_id(kind, identifier):
    return hashlib.sha256(f"world-event:{kind}:{identifier}".encode()).hexdigest()


def _entity_id(kind, identifier):
    return hashlib.sha256(
        f"world-entity:{kind}:{_normalize(identifier)}".encode()
    ).hexdigest()


def _normalize(value):
    return "".join(character for character in str(value or "").lower() if character.isalnum())[:200]


def _bounded(value, default):
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _load_json(value, default):
    try:
        return json.loads(value or "")
    except (TypeError, ValueError):
        return default
