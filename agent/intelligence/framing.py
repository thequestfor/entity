"""Source-blind semantic framing observations and event-level comparisons."""

import hashlib
import json
from dataclasses import dataclass

from agent.intelligence.store import utc_now


METHOD = "semantic-framing-v2"
COMPARISON_METHOD = "event-framing-comparison-v2"
SCHEDULER = "semantic-framing"
EVENT_READY_SCHEDULER = "semantic-framing-event-ready"
DIMENSIONS = {
    "loaded_language", "emotional_intensity", "agency_assignment",
    "agency_omission", "attribution_balance", "source_diversity",
    "certainty_inflation", "fact_interpretation_separation",
    "headline_body_divergence", "unequal_evidentiary_standard",
    "unsupported_characterization",
}


@dataclass(frozen=True)
class FramingResult:
    processed: int = 0
    completed: int = 0
    needs_model: int = 0
    rejected: int = 0
    model_calls: int = 0


class SemanticFramingEngine:
    def __init__(self, store, router=None, enabled=True, batch_size=5,
                 model_calls_per_cycle=4, fresh_router=None,
                 fresh_window_minutes=30, event_ready_per_cycle=2):
        self.store = store
        self.router = router
        self.fresh_router = fresh_router
        self.enabled = bool(enabled)
        self.batch_size = max(1, min(25, int(batch_size)))
        self.model_calls_per_cycle = max(0, min(10, int(model_calls_per_cycle)))
        self.fresh_window_minutes = max(
            5, min(1440, int(fresh_window_minutes))
        )
        self.event_ready_per_cycle = max(
            0, min(self.batch_size, self.model_calls_per_cycle,
                   int(event_ready_per_cycle))
        )

    def run_batch(self):
        if not self.enabled:
            return FramingResult()
        capacity = self.batch_size
        if self.router or self.fresh_router:
            capacity = min(capacity, self.model_calls_per_cycle)
        if capacity <= 0:
            return FramingResult()
        with self.store._connect() as connection:
            rows = connection.execute(
                """WITH eligible AS (
                     SELECT capture.*,
                            documents.retrieved_at,
                            COALESCE(NULLIF(documents.publisher_key,''),
                                     capture.source_id) publisher_key,
                            CASE WHEN julianday(documents.retrieved_at)>=
                              julianday('now',?) THEN 1 ELSE 0 END is_fresh,
                            EXISTS (
                              SELECT 1
                              FROM world_event_observations own_observation
                              JOIN world_event_memberships own_membership
                                ON own_membership.observation_id=own_observation.id
                               AND own_membership.active=1
                              JOIN world_events event
                                ON event.id=own_membership.world_event_id
                               AND event.status='active'
                              JOIN world_event_memberships peer_membership
                                ON peer_membership.world_event_id=event.id
                               AND peer_membership.active=1
                              JOIN world_event_observations peer_observation
                                ON peer_observation.id=peer_membership.observation_id
                               AND peer_observation.status='active'
                              JOIN documents peer_document
                                ON peer_document.id=peer_observation.document_id
                              JOIN document_versions peer_version
                                ON peer_version.id=peer_observation.document_version_id
                              JOIN sources peer_source
                                ON peer_source.id=peer_observation.source_id
                              LEFT JOIN source_policies peer_policy
                                ON peer_policy.source_id=peer_observation.source_id
                              LEFT JOIN article_content_captures peer_capture
                                ON peer_capture.document_version_id=
                                   peer_observation.document_version_id
                               AND peer_capture.status='complete'
                              LEFT JOIN article_framing_assessments peer_assessment
                                ON peer_assessment.article_capture_id=peer_capture.id
                               AND peer_assessment.status='complete'
                              WHERE own_observation.document_version_id=
                                    capture.document_version_id
                              GROUP BY event.id
                              HAVING COUNT(DISTINCT peer_document.publisher_key)>=2
                                 AND COUNT(DISTINCT COALESCE(
                                   NULLIF(peer_document.reporting_family_key,''),
                                   NULLIF(peer_document.publisher_key,''),
                                   peer_document.source_id))>=2
                                 AND COUNT(DISTINCT peer_assessment.publisher_key)<2
                                 AND COUNT(DISTINCT CASE WHEN
                                   peer_assessment.status='complete' OR
                                   (peer_capture.status='complete' AND
                                    peer_capture.word_count>=80) OR
                                   (peer_capture.id IS NULL AND
                                    (peer_policy.article_acquisition_mode=
                                      'publisher-page' OR
                                     (peer_version.metadata LIKE
                                       '%publisher_feed_full_content%' AND
                                      length(peer_version.content)>=500)) AND
                                    COALESCE(peer_source.last_error,'')='')
                                   THEN peer_document.publisher_key END)>=2
                                 AND SUM(CASE WHEN peer_assessment.publisher_key=
                                      documents.publisher_key THEN 1 ELSE 0 END)=0
                            ) is_event_ready,
                            CASE
                              WHEN julianday(documents.retrieved_at)>=
                                julianday('now',?) THEN 0
                              WHEN assessment.status='needs-model'
                               AND assessment.input_hash=capture.content_hash
                                THEN 1
                              WHEN assessment.article_capture_id IS NOT NULL
                               AND assessment.input_hash!=capture.content_hash
                                THEN 2
                              ELSE 3
                            END work_priority,
                            CASE
                              WHEN assessment.status='needs-model'
                               AND assessment.input_hash=capture.content_hash
                                THEN assessment.updated_at
                              ELSE capture.captured_at
                            END work_time
                     FROM article_content_captures capture
                     JOIN documents ON documents.id=capture.document_id
                     LEFT JOIN article_framing_assessments assessment
                       ON assessment.article_capture_id=capture.id
                     WHERE capture.status='complete' AND capture.word_count>=80
                       AND (assessment.article_capture_id IS NULL OR
                            assessment.input_hash!=capture.content_hash OR
                            (assessment.status='needs-model' AND
                             julianday(assessment.updated_at)<
                               julianday('now','-6 hours')))
                   ), ranked AS (
                     SELECT eligible.*,
                            ROW_NUMBER() OVER (
                              PARTITION BY publisher_key
                              ORDER BY is_fresh DESC,is_event_ready DESC,
                                       work_priority,work_time,id
                            ) publisher_rank
                     FROM eligible
                   ) SELECT * FROM ranked WHERE publisher_rank<=?
                     ORDER BY publisher_key,publisher_rank""",
                (
                    f"-{self.fresh_window_minutes} minutes",
                    f"-{self.fresh_window_minutes} minutes", capacity,
                ),
            ).fetchall()
        buckets = {}
        for raw in rows:
            capture = dict(raw)
            buckets.setdefault(capture["publisher_key"], []).append(capture)
        publishers = _rotated_keys(
            buckets, self.store.scheduler_cursor(SCHEDULER)
        )
        ready_publishers = _rotated_keys(
            buckets, self.store.scheduler_cursor(EVENT_READY_SCHEDULER)
        )
        selected, seen = [], set()

        def take(predicate, maximum, publisher_order=publishers,
                 one_per_publisher=False):
            lane = {publisher: [capture for capture in buckets[publisher]
                                if predicate(capture)]
                    for publisher in publisher_order}
            depth = max((len(bucket) for bucket in lane.values()), default=0)
            for rank in range(min(depth, 1) if one_per_publisher else depth):
                for publisher in publisher_order:
                    bucket = lane[publisher]
                    if rank >= len(bucket) or bucket[rank]["id"] in seen:
                        continue
                    seen.add(bucket[rank]["id"])
                    selected.append(bucket[rank])
                    if len(selected) >= maximum:
                        return

        if any(capture["is_fresh"] for capture in rows):
            take(lambda capture: bool(capture["is_fresh"]), 1)
        take(lambda capture: bool(capture.get("is_event_ready")), min(
            capacity, len(selected) + self.event_ready_per_cycle
        ), ready_publishers, one_per_publisher=True)
        take(lambda capture: True, capacity)
        processed = completed = needs_model = rejected = calls = 0
        for capture in selected:
            if (
                (self.router or self.fresh_router)
                and calls >= self.model_calls_per_cycle
            ):
                break
            router = (
                self.fresh_router
                if capture["is_fresh"] and self.fresh_router is not None
                else self.router
            )
            if router is not None and not self._model_budget_available(router):
                continue
            processed += 1
            if router is None:
                self._store(capture, [], "needs-model")
                needs_model += 1
                self.store.advance_scheduler_cursor(
                    SCHEDULER, capture["publisher_key"]
                )
                if capture.get("is_event_ready"):
                    self.store.advance_scheduler_cursor(
                        EVENT_READY_SCHEDULER, capture["publisher_key"]
                    )
                continue
            calls += 1
            try:
                payload = router.generate_json(
                    _prompt(capture["title"], capture["normalized_text"]),
                    user_input="Analyze this source-blind article capture.",
                    routing="world_understanding",
                    _budget_operation=(
                        "semantic-framing-v2-fresh"
                        if capture["is_fresh"] else "semantic-framing-v2"
                    ),
                )
            except Exception:
                self.store.advance_scheduler_cursor(
                    SCHEDULER, capture["publisher_key"]
                )
                if not self._model_budget_available(router):
                    continue
                self._store(capture, [], "needs-model")
                needs_model += 1
                if capture.get("is_event_ready"):
                    self.store.advance_scheduler_cursor(
                        EVENT_READY_SCHEDULER, capture["publisher_key"]
                    )
                continue
            observations = _validate(payload, capture["normalized_text"])
            if not observations:
                self._store(capture, [], "no-supported-signals")
                rejected += 1
            else:
                self._store(capture, observations, "complete")
                completed += 1
            self.store.advance_scheduler_cursor(
                SCHEDULER, capture["publisher_key"]
            )
            if capture.get("is_event_ready"):
                self.store.advance_scheduler_cursor(
                    EVENT_READY_SCHEDULER, capture["publisher_key"]
                )
        return FramingResult(processed, completed, needs_model, rejected, calls)

    def _model_budget_available(self, router=None):
        available = getattr(router if router is not None else self.router,
                            "budget_available", None)
        if not callable(available):
            return True
        try:
            return bool(available())
        except Exception:
            return True

    def _store(self, capture, observations, status):
        now = utc_now()
        scores = {}
        for item in observations:
            scores.setdefault(item["dimension"], []).append(item["strength"])
        aggregate = {
            key: round(sum(values) / len(values), 4)
            for key, values in scores.items()
        }
        confidence = (
            sum(item["confidence"] for item in observations) / len(observations)
            if observations else 0.0
        )
        with self.store._connect() as connection:
            for item in observations:
                connection.execute(
                    """INSERT OR IGNORE INTO article_framing_observations (
                         article_capture_id,document_id,publisher_key,dimension,
                         direction,strength,confidence,evidence_span,evidence_start,
                         evidence_end,explanation,method,model,input_hash,
                         evidence_cutoff_at,created_at
                       ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (capture["id"], capture["document_id"], capture["publisher_key"],
                     item["dimension"], item["direction"], item["strength"],
                     item["confidence"], item["evidence"], item["start"],
                     item["end"], item["explanation"], METHOD,
                     _provider(self.router), capture["content_hash"],
                     capture["captured_at"], now),
                )
            connection.execute(
                """INSERT INTO article_framing_assessments (
                     article_capture_id,publisher_key,dimension_scores,
                     evidence_count,confidence,status,method,input_hash,updated_at
                   ) VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(article_capture_id) DO UPDATE SET
                     dimension_scores=excluded.dimension_scores,
                     evidence_count=excluded.evidence_count,
                     confidence=excluded.confidence,status=excluded.status,
                     method=excluded.method,input_hash=excluded.input_hash,
                     updated_at=excluded.updated_at""",
                (capture["id"], capture["publisher_key"], _json(aggregate),
                 len(observations), round(confidence, 4), status, METHOD,
                 capture["content_hash"], now),
            )


class EventFramingComparisonEngine:
    def __init__(self, store, enabled=True, batch_size=20, clock=None):
        self.store = store
        self.enabled = bool(enabled)
        self.batch_size = max(1, min(100, int(batch_size)))
        self.clock = clock or utc_now

    def run_batch(self):
        if not self.enabled:
            return {"events": 0, "comparisons": 0, "coverage_windows": 0}
        now = self.clock()
        comparisons = 0
        with self.store._connect() as connection:
            events = connection.execute(
                """SELECT event.id,MIN(observation.captured_at) eligible_since
                   FROM world_events event
                   JOIN world_event_memberships membership
                     ON membership.world_event_id=event.id AND membership.active=1
                   JOIN world_event_observations observation
                     ON observation.id=membership.observation_id
                    AND observation.status='active'
                   JOIN documents ON documents.id=observation.document_id
                   JOIN sources ON sources.id=observation.source_id
                   JOIN article_content_captures capture
                     ON capture.document_version_id=observation.document_version_id
                    AND capture.status='complete'
                   JOIN article_framing_assessments assessment
                     ON assessment.article_capture_id=capture.id
                    AND assessment.status='complete'
                   WHERE event.status='active'
                     AND COALESCE(sources.last_error,'')=''
                   GROUP BY event.id
                   HAVING COUNT(DISTINCT documents.publisher_key)>=2
                      AND COUNT(DISTINCT COALESCE(
                            NULLIF(documents.reporting_family_key,''),
                            NULLIF(documents.publisher_key,''),documents.source_id
                          ))>=2
                   ORDER BY eligible_since,event.id LIMIT ?""",
                (min(2000, self.batch_size * 20),),
            ).fetchall()
            for event in events:
                rows = connection.execute(
                    """SELECT DISTINCT documents.publisher_key,
                          COALESCE(NULLIF(documents.reporting_family_key,''),
                                   NULLIF(documents.publisher_key,''),
                                   documents.source_id) family_key,
                          assessment.dimension_scores,assessment.confidence,
                          assessment.method assessment_method,
                          assessment.input_hash assessment_input_hash,
                          capture.content_hash,capture.captured_at,
                          versions.membership_hash
                       FROM world_event_memberships membership
                       JOIN world_event_observations observation
                         ON observation.id=membership.observation_id
                       JOIN documents ON documents.id=observation.document_id
                       JOIN sources ON sources.id=observation.source_id
                       JOIN article_content_captures capture
                         ON capture.document_version_id=observation.document_version_id
                        AND capture.status='complete'
                       JOIN article_framing_assessments assessment
                         ON assessment.article_capture_id=capture.id
                       JOIN world_events event ON event.id=membership.world_event_id
                       LEFT JOIN world_event_versions versions
                         ON versions.id=event.current_version_id
                       WHERE membership.world_event_id=? AND membership.active=1
                         AND observation.status='active'
                         AND assessment.status='complete'
                         AND COALESCE(sources.last_error,'')=''
                       ORDER BY capture.captured_at,capture.content_hash""",
                    (event["id"],),
                ).fetchall()
                publishers = {}
                families = set()
                evidence = []
                for row in rows:
                    publishers.setdefault(row["publisher_key"], []).append(
                        self.store._json_load(row["dimension_scores"], {})
                    )
                    families.add(row["family_key"])
                    evidence.append({
                        "publisher": row["publisher_key"],
                        "family": row["family_key"],
                        "content_hash": row["content_hash"],
                        "assessment_hash": row["assessment_input_hash"],
                        "assessment_method": row["assessment_method"],
                        "membership_hash": row["membership_hash"] or "",
                    })
                if len(publishers) < 2 or len(families) < 2:
                    continue
                dimensions = {
                    publisher: _average_vectors(vectors)
                    for publisher, vectors in publishers.items()
                }
                cutoff = max(row["captured_at"] for row in rows)
                raw = {"event": event["id"], "publishers": sorted(publishers),
                       "families": sorted(families), "evidence": sorted(
                           evidence, key=lambda item: _json(item)
                       ),
                       "dimensions": dimensions, "cutoff": cutoff,
                       "method": COMPARISON_METHOD}
                input_hash = hashlib.sha256(_json(raw).encode()).hexdigest()
                exists = connection.execute(
                    """SELECT 1 FROM event_publisher_comparisons
                       WHERE world_event_id=? AND method=? AND input_hash=?""",
                    (event["id"], COMPARISON_METHOD, input_hash),
                ).fetchone()
                if exists:
                    continue
                inserted = connection.execute(
                    """INSERT OR IGNORE INTO event_publisher_comparisons (
                         world_event_id,publisher_keys,shared_claims,divergent_claims,
                         framing_dimensions,source_count,evidence_cutoff_at,status,
                         method,input_hash,created_at
                       ) VALUES (?,?, '[]','[]',?,?,?,?,?,?,?)""",
                    (event["id"], _json(sorted(publishers)), _json(dimensions),
                     len(publishers), cutoff, "shadow", COMPARISON_METHOD,
                     input_hash, now),
                ).rowcount
                comparisons += int(inserted > 0)
                if comparisons >= self.batch_size:
                    break
        windows = self._coverage(now)
        return {"events": len(events), "comparisons": comparisons,
                "coverage_windows": windows}

    def _coverage(self, now):
        with self.store._connect() as connection:
            rows = connection.execute(
                """SELECT documents.publisher_key,documents.category topic,
                          COUNT(DISTINCT documents.id) documents,
                          COUNT(DISTINCT capture.document_id) captured,
                          MAX(sources.last_error='') source_healthy
                   FROM documents
                   JOIN sources ON sources.id=documents.source_id
                   LEFT JOIN article_content_captures capture
                     ON capture.document_id=documents.id AND capture.status='complete'
                   WHERE sources.kind='traditional_news'
                     AND julianday(documents.retrieved_at)>=julianday(?,'-7 days')
                   GROUP BY documents.publisher_key,documents.category"""
                , (now,)
            ).fetchall()
            window_start = connection.execute(
                "SELECT datetime(?,'-7 days')", (now,)
            ).fetchone()[0] + "Z"
            for row in rows:
                coverage = float(row["captured"] or 0) / max(1, int(row["documents"]))
                status = "eligible" if row["source_healthy"] and coverage >= .8 else "unknown"
                raw = [row["publisher_key"], row["topic"], row["documents"],
                       row["captured"], row["source_healthy"], round(coverage, 4)]
                input_hash = hashlib.sha256(_json(raw).encode()).hexdigest()
                connection.execute(
                    """INSERT INTO publisher_coverage_windows (
                         publisher_key,topic,window_start,window_end,
                         eligible_event_count,covered_event_count,peer_event_count,
                         source_healthy,acquisition_coverage,selection_signal,status,
                         method,input_hash,updated_at
                       ) VALUES (?,?,?,?,0,0,0,?,?,NULL,?,?,?,?)
                       ON CONFLICT(publisher_key,topic,window_start,window_end)
                       DO UPDATE SET source_healthy=excluded.source_healthy,
                         acquisition_coverage=excluded.acquisition_coverage,
                         selection_signal=NULL,status=excluded.status,
                         input_hash=excluded.input_hash,updated_at=excluded.updated_at""",
                    (row["publisher_key"], row["topic"], window_start, now,
                     int(bool(row["source_healthy"])), round(coverage, 4), status,
                     "coverage-prerequisite-v1", input_hash, now),
                )
        return len(rows)


def _prompt(title, text):
    return f"""Analyze observable framing in this publisher-blind article.
Do not infer ideology, motive, truth, or publisher identity. Return JSON with
observations (maximum 20). Each observation requires dimension, direction,
strength 0..1, confidence 0..1, evidence copied exactly from ARTICLE, and a
neutral explanation. Allowed dimensions: {', '.join(sorted(DIMENSIONS))}.
Reject claims unsupported by a literal span.

HEADLINE:
{str(title or '')[:500]}

ARTICLE:
{str(text or '')[:30000]}"""


def _validate(payload, text):
    rows = payload.get("observations") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    result = []
    for raw in rows[:20]:
        if not isinstance(raw, dict):
            continue
        dimension = str(raw.get("dimension") or "").strip().lower()
        evidence = str(raw.get("evidence") or "").strip()
        if dimension not in DIMENSIONS or len(evidence) < 3:
            continue
        start = text.find(evidence)
        if start < 0:
            continue
        try:
            strength = max(0.0, min(1.0, float(raw.get("strength"))))
            confidence = max(0.0, min(.95, float(raw.get("confidence"))))
        except (TypeError, ValueError):
            continue
        result.append({
            "dimension": dimension,
            "direction": str(raw.get("direction") or "present")[:80],
            "strength": strength, "confidence": confidence,
            "evidence": evidence, "start": start, "end": start + len(evidence),
            "explanation": str(raw.get("explanation") or "")[:500],
        })
    return result


def _average_vectors(vectors):
    values = {}
    for vector in vectors:
        for key, value in vector.items():
            values.setdefault(key, []).append(float(value))
    return {key: round(sum(items) / len(items), 4)
            for key, items in values.items()}


def _provider(router):
    value = getattr(router, "provider_name", None)
    try:
        return str(value() if callable(value) else value or "")[:120]
    except Exception:
        return ""


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _rotated_keys(buckets, cursor):
    keys = sorted(buckets)
    if not keys or not cursor:
        return keys
    for index, key in enumerate(keys):
        if key > cursor:
            return keys[index:] + keys[:index]
    return keys
