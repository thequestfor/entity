import json
import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from agent.intelligence.features import (
    DocumentFeatures,
    entity_similarity,
    extract_document_features,
    token_similarity,
)
from agent.intelligence.store import utc_now
from agent.intelligence.embeddings import cosine_similarity


CLUSTERING_METHOD = "provenance-event-cluster-v1"


@dataclass(frozen=True)
class ClusterDecision:
    action: str
    target_situation_id: str | None = None
    score: float = 0.0
    components: dict = field(default_factory=dict)
    vetoes: tuple[str, ...] = ()
    related_document_id: str | None = None
    relationship: str = "independent"


class EventClusterer:
    """Deterministic, auditable event matching with conservative thresholds."""

    def __init__(
        self,
        auto_link_threshold=0.82,
        review_threshold=0.65,
        lookback_days=14,
        max_candidates=200,
        embedding_provider=None
    ):
        self.auto_link_threshold = min(0.99, max(0.5, float(auto_link_threshold)))
        self.review_threshold = min(
            self.auto_link_threshold, max(0.3, float(review_threshold))
        )
        self.lookback_days = max(1, min(90, int(lookback_days)))
        self.max_candidates = max(10, min(1000, int(max_candidates)))
        self.embedding_provider = embedding_provider

    def decide(self, connection, document):
        features = extract_document_features(document)
        self._store_features(connection, document["id"], features)
        document_vector = self._store_embedding(
            connection, document, document["id"]
        )
        candidates = self._candidates(connection, document, features)
        best = ClusterDecision(action="separate")
        for candidate in candidates:
            decision = self._score(
                document, features, candidate, document_vector
            )
            if decision.vetoes:
                continue
            if decision.score > best.score:
                best = decision
        if best.score >= self.auto_link_threshold:
            return ClusterDecision(**{**best.__dict__, "action": "link"})
        if best.score >= self.review_threshold:
            return ClusterDecision(**{**best.__dict__, "action": "review"})
        return ClusterDecision(action="separate", score=best.score)

    def backfill_features(self, store, limit=500):
        """Populate deterministic indexes without changing situation links."""
        with store._connect() as connection:
            rows = connection.execute(
                """
                SELECT documents.*, situation_documents.situation_id
                FROM documents
                JOIN situation_documents
                  ON situation_documents.document_id = documents.id
                LEFT JOIN document_features
                  ON document_features.document_id = documents.id
                WHERE document_features.document_id IS NULL
                ORDER BY documents.retrieved_at DESC LIMIT ?
                """,
                (max(1, min(5000, int(limit))),)
            ).fetchall()
            for row in rows:
                document = dict(row)
                document["metadata"] = store._json_load(
                    document.get("metadata"), {}
                )
                features = extract_document_features(document)
                self._store_features(connection, document["id"], features)
                now = utc_now()
                for entity_key in features.entity_keys:
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO situation_entities (
                            situation_id, entity_key, mention_count, updated_at
                        ) VALUES (?, ?, 1, ?)
                        """,
                        (document["situation_id"], entity_key, now)
                    )
                connection.execute(
                    """
                    UPDATE documents
                    SET reporting_family_key = COALESCE(
                        NULLIF(reporting_family_key, ''),
                        NULLIF(publisher_key, ''), source_id
                    ) WHERE id = ?
                    """,
                    (document["id"],)
                )
        return len(rows)

    def record_link(self, connection, document, situation_id, decision):
        features = extract_document_features(document)
        now = utc_now()
        for entity_key in features.entity_keys:
            connection.execute(
                """
                INSERT INTO situation_entities (
                    situation_id, entity_key, mention_count, updated_at
                ) VALUES (?, ?, 1, ?)
                ON CONFLICT(situation_id, entity_key) DO UPDATE SET
                    mention_count = mention_count + 1,
                    updated_at = excluded.updated_at
                """,
                (situation_id, entity_key, now)
            )

        family_key = document.get("publisher_key") or document.get("source_id")
        if decision.relationship in {"copied", "syndicated"}:
            family_key = f"report:{features.content_fingerprint}"
            if decision.related_document_id:
                connection.execute(
                    """
                    UPDATE documents SET reporting_family_key = ?
                    WHERE id IN (?, ?)
                    """,
                    (
                        family_key, document["id"],
                        decision.related_document_id
                    )
                )
                left, right = sorted((document["id"], decision.related_document_id))
                connection.execute(
                    """
                    INSERT OR IGNORE INTO document_relationships (
                        left_document_id, right_document_id, relationship,
                        score, method, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        left, right, decision.relationship,
                        decision.score, CLUSTERING_METHOD, now
                    )
                )
        connection.execute(
            """
            UPDATE documents SET reporting_family_key = ?
            WHERE id = ? AND reporting_family_key = ''
            """,
            (family_key, document["id"])
        )

        if decision.action == "review" and decision.target_situation_id:
            connection.execute(
                """
                INSERT OR IGNORE INTO situation_merge_candidates (
                    source_situation_id, target_situation_id, score,
                    components, vetoes, decision, method, created_at
                ) VALUES (?, ?, ?, ?, ?, 'review', ?, ?)
                """,
                (
                    situation_id, decision.target_situation_id,
                    decision.score, json.dumps(decision.components),
                    json.dumps(decision.vetoes), CLUSTERING_METHOD, now
                )
            )

    def _store_features(self, connection, document_id, features):
        record = features.as_record()
        now = utc_now()
        connection.execute(
            """
            INSERT INTO document_features (
                document_id, feature_version, normalized_title, occurred_at,
                entity_keys, location_key, lexical_signature,
                content_fingerprint, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(document_id) DO UPDATE SET
                feature_version = excluded.feature_version,
                normalized_title = excluded.normalized_title,
                occurred_at = excluded.occurred_at,
                entity_keys = excluded.entity_keys,
                location_key = excluded.location_key,
                lexical_signature = excluded.lexical_signature,
                content_fingerprint = excluded.content_fingerprint,
                updated_at = excluded.updated_at
            """,
            (
                document_id, record["feature_version"],
                record["normalized_title"], record["occurred_at"],
                record["entity_keys"], record["location_key"],
                record["lexical_signature"], record["content_fingerprint"],
                now, now
            )
        )

    def _candidates(self, connection, document, features):
        occurred = _parse_time(features.occurred_at)
        cutoff = (occurred - timedelta(days=self.lookback_days)).isoformat().replace(
            "+00:00", "Z"
        )
        rows = connection.execute(
            """
            SELECT situations.id AS situation_id, situations.title,
                   situations.category, situations.latitude,
                   situations.longitude, situations.last_seen_at,
                   documents.id AS document_id,
                   documents.title AS document_title,
                   documents.publisher_key,
                   document_features.entity_keys,
                   document_features.lexical_signature,
                   document_features.content_fingerprint,
                   document_features.occurred_at,
                   document_embeddings.vector AS embedding_vector
            FROM situations
            JOIN situation_documents
              ON situation_documents.situation_id = situations.id
            JOIN documents ON documents.id = situation_documents.document_id
            JOIN document_features
              ON document_features.document_id = documents.id
            LEFT JOIN document_embeddings
              ON document_embeddings.document_id = documents.id
             AND document_embeddings.model = ?
            WHERE situations.category = ?
              AND situations.last_seen_at >= ?
              AND situations.status NOT IN ('expired','archived','resolved','merged')
              AND documents.id != ?
            ORDER BY situations.last_seen_at DESC
            LIMIT ?
            """,
            (
                self._embedding_name(),
                document.get("category", "general"), cutoff,
                document["id"], self.max_candidates
            )
        ).fetchall()
        return [dict(row) for row in rows]

    def _score(self, document, features, candidate, document_vector=None):
        candidate_tokens = _json_tuple(candidate.get("lexical_signature"))
        candidate_entities = _json_tuple(candidate.get("entity_keys"))
        lexical = token_similarity(features.lexical_signature, candidate_tokens)
        entities = entity_similarity(features.entity_keys, candidate_entities)
        semantic = cosine_similarity(
            document_vector, _json_vector(candidate.get("embedding_vector"))
        )
        hours = abs(
            (_parse_time(features.occurred_at) - _parse_time(
                candidate.get("occurred_at")
            )).total_seconds()
        ) / 3600.0
        temporal = max(0.0, 1.0 - hours / (24.0 * self.lookback_days))
        distance = _distance_km(
            document.get("latitude"), document.get("longitude"),
            candidate.get("latitude"), candidate.get("longitude")
        )
        geographic = 0.0
        if distance is not None:
            geographic = max(0.0, 1.0 - distance / 750.0)

        exact_copy = (
            features.content_fingerprint
            and features.content_fingerprint == candidate.get("content_fingerprint")
        )
        near_copy = lexical >= 0.9
        relationship = "copied" if exact_copy else (
            "syndicated" if near_copy else "independent"
        )
        components = {
            "lexical": round(lexical, 4),
            "semantic": round(semantic, 4),
            "entities": round(entities, 4),
            "temporal": round(temporal, 4),
            "geographic": round(geographic, 4),
        }
        score = (
            lexical * (0.28 if semantic else 0.38)
            + semantic * (0.20 if semantic else 0.0)
            + entities * 0.27
            + temporal * 0.15 + geographic * 0.20
        )
        if distance is not None and distance <= 50:
            score += 0.18
        if entities >= 0.5:
            score += 0.08
        if lexical >= 0.3 and entities >= 0.5:
            score += 0.05
        if exact_copy:
            score = max(score, 0.98)
        elif near_copy:
            score = max(score, 0.90)

        vetoes = []
        left_office = _nws_office(document.get("title"))
        right_office = _nws_office(candidate.get("document_title"))
        if left_office and right_office and left_office != right_office:
            vetoes.append("different_nws_office")
        if distance is not None and distance > 1500 and entities < 0.5:
            vetoes.append("geographically_incompatible")
        if hours > self.lookback_days * 24:
            vetoes.append("temporally_incompatible")
        return ClusterDecision(
            action="separate",
            target_situation_id=candidate["situation_id"],
            score=round(min(1.0, score), 4),
            components=components,
            vetoes=tuple(vetoes),
            related_document_id=candidate["document_id"],
            relationship=relationship
        )

    def _embedding_name(self):
        provider = self.embedding_provider
        return provider.name if provider and provider.available() else ""

    def _store_embedding(self, connection, document, document_id):
        provider = self.embedding_provider
        if provider is None or not provider.available():
            return None
        existing = connection.execute(
            "SELECT vector FROM document_embeddings WHERE document_id = ? AND model = ?",
            (document_id, provider.name)
        ).fetchone()
        if existing:
            return _json_vector(existing["vector"])
        vector = provider.embed(
            f"{document.get('title', '')}\n{document.get('summary', '')}"
        )
        if not vector:
            return None
        connection.execute(
            """
            INSERT OR REPLACE INTO document_embeddings (
                document_id, model, dimensions, vector, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                document_id, provider.name, len(vector),
                json.dumps(vector), utc_now()
            )
        )
        return vector


def _json_tuple(value):
    try:
        decoded = json.loads(value or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        return ()
    return tuple(str(item) for item in decoded) if isinstance(decoded, list) else ()


def _json_vector(value):
    try:
        decoded = json.loads(value or "[]")
        return tuple(float(item) for item in decoded)
    except (TypeError, ValueError, json.JSONDecodeError):
        return ()


def _parse_time(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return datetime.now(UTC)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _distance_km(lat_a, lon_a, lat_b, lon_b):
    if None in (lat_a, lon_a, lat_b, lon_b):
        return None
    lat_a, lon_a, lat_b, lon_b = map(
        math.radians, map(float, (lat_a, lon_a, lat_b, lon_b))
    )
    dlat = lat_b - lat_a
    dlon = lon_b - lon_a
    value = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat_a) * math.cos(lat_b) * math.sin(dlon / 2) ** 2
    )
    return 6371.0 * 2 * math.atan2(math.sqrt(value), math.sqrt(max(0.0, 1-value)))


def _nws_office(title):
    match = re.search(r"\bby\s+nws\s+(.+)$", str(title or ""), re.I)
    return re.sub(r"\s+", " ", match.group(1)).strip().lower() if match else ""
