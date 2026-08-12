"""Deterministic, auditable fusion of observations into canonical events."""

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from agent.intelligence.store import utc_now


METHOD = "deterministic-event-fusion-v3"
FEATURE_VERSION = "event-fusion-features-v3"
LANE = "world-event-observations-v3"
READINESS_SCHEDULER = "event-fusion-comparison-ready-v3"
EXCLUDED_SOURCE_KINDS = {
    "private_mail", "prediction_market", "weather_forecast",
    "infrastructure_reference",
}
COMPATIBLE_FAMILIES = (
    frozenset(("conflict", "news")),
    frozenset(("emergency", "news")),
    frozenset(("hazard", "news")),
    frozenset(("health", "news")),
)
IDENTIFIER_KEYS = {
    "event_id", "eventid", "alert_id", "episode_id", "incident_id",
    "usgs_id", "gdacs_event_id", "activation_id", "acled_event_id",
}


@dataclass(frozen=True)
class FusionResult:
    processed: int = 0
    linked: int = 0
    created: int = 0
    reviews: int = 0
    versions: int = 0


class EventFusionEngine:
    """Fuse eligible projected observations without changing source evidence."""

    def __init__(self, store, enabled=True, batch_size=100,
                 auto_link_threshold=0.82, review_threshold=0.65,
                 max_candidates=100, lookback_days=14, clock=None,
                 comparison_ready_per_cycle=20, recent_per_cycle=20):
        self.store = store
        self.enabled = bool(enabled)
        self.batch_size = max(1, min(500, int(batch_size)))
        self.auto_link_threshold = max(.55, min(.99, float(auto_link_threshold)))
        self.review_threshold = max(.3, min(
            self.auto_link_threshold, float(review_threshold)
        ))
        self.max_candidates = max(5, min(500, int(max_candidates)))
        self.lookback_days = max(1, min(90, int(lookback_days)))
        self.clock = clock or utc_now
        self.comparison_ready_per_cycle = max(
            0, min(self.batch_size, int(comparison_ready_per_cycle))
        )
        self.recent_per_cycle = max(
            0, min(self.batch_size, int(recent_per_cycle))
        )

    def run_batch(self):
        if not self.enabled:
            return FusionResult()
        now = self.clock()
        with self.store._connect() as connection:
            self._state(connection, now)
            selection = """SELECT observations.*,versions.id version_id,
                       COALESCE(json_extract(observations.properties,'$.title'),documents.title) document_title,
                       COALESCE(json_extract(observations.properties,'$.summary'),documents.summary) document_summary,
                       documents.category document_category,documents.publisher_key,
                       documents.reporting_family_key,documents.status document_status,
                       sources.kind source_kind,sources.credibility source_credibility,
                       policies.evidence_role,policies.independence_family,
                       policies.policy_version,features.entity_keys,
                       features.lexical_signature,features.normalized_title,
                       features.occurred_at feature_occurred_at
                   FROM world_event_observations observations
                   JOIN document_versions versions
                     ON versions.id=observations.document_version_id
                   JOIN documents ON documents.id=observations.document_id
                   JOIN sources ON sources.id=observations.source_id
                   LEFT JOIN source_policies policies
                     ON policies.source_id=observations.source_id
                   LEFT JOIN document_features features
                     ON features.document_id=observations.document_id
                   WHERE {condition}
                     AND sources.kind NOT IN (
                       'private_mail','prediction_market','weather_forecast',
                       'infrastructure_reference'
                     )"""
            unprocessed = "NOT EXISTS (SELECT 1 FROM world_event_fusion_decisions decisions WHERE decisions.observation_id=observations.id AND decisions.method=?)"
            ready_limit = self.comparison_ready_per_cycle
            ready = connection.execute(
                "WITH eligible AS (" + selection.format(condition=unprocessed + """
                  AND EXISTS (
                    SELECT 1 FROM article_content_captures captures
                    JOIN article_framing_assessments assessments
                      ON assessments.article_capture_id=captures.id
                    WHERE captures.document_version_id=observations.document_version_id
                      AND captures.status='complete'
                      AND assessments.status='complete'
                  )""") + """), ranked AS (
                    SELECT eligible.*,ROW_NUMBER() OVER (
                      PARTITION BY COALESCE(NULLIF(publisher_key,''),source_id)
                      ORDER BY captured_at,id
                    ) publisher_rank FROM eligible
                  ) SELECT * FROM ranked WHERE publisher_rank<=?
                    ORDER BY publisher_key,publisher_rank LIMIT ?""",
                (METHOD, ready_limit,
                 min(5000, max(ready_limit * 100, ready_limit))),
            ).fetchall() if ready_limit else []
            recent_limit = self.recent_per_cycle
            recent = connection.execute(
                selection.format(condition=unprocessed)
                + " ORDER BY observations.captured_at DESC,observations.id DESC LIMIT ?",
                (METHOD, recent_limit),
            ).fetchall() if recent_limit else []
            oldest = connection.execute(
                selection.format(condition=unprocessed)
                + " ORDER BY observations.captured_at,observations.id LIMIT ?",
                (METHOD, self.batch_size),
            ).fetchall()
            rows, seen = [], set()
            def add(items, maximum):
                for raw in items:
                    if len(rows) >= maximum:
                        break
                    if raw["id"] not in seen:
                        seen.add(raw["id"])
                        rows.append(dict(raw))

            add(ready, min(self.batch_size, len(ready)))
            remaining = self.batch_size - len(rows)
            recent_reserve = min(recent_limit, remaining)
            add(oldest, self.batch_size - recent_reserve)
            add(recent, self.batch_size)
            add(oldest, self.batch_size)
            if ready:
                _advance_scheduler_cursor(
                    connection, READINESS_SCHEDULER,
                    ready[-1]["publisher_key"] or ready[-1]["source_id"], now,
                )

            linked = created = reviews = versions = 0
            for row in rows:
                outcome = self._process(connection, row, now)
                linked += outcome[0]
                created += outcome[1]
                reviews += outcome[2]
                versions += outcome[3]
            if rows:
                connection.execute(
                    """UPDATE world_event_fusion_state SET cursor_version_id=?,
                       processed=processed+?,linked=linked+?,created=created+?,
                       reviews=reviews+?,completed=0,completed_at=NULL,
                       last_error='',updated_at=? WHERE lane=?""",
                    (0, len(rows), linked, created,
                     reviews, now, LANE),
                )
            else:
                connection.execute(
                    """UPDATE world_event_fusion_state SET processed=processed+?,
                       linked=linked+?,created=created+?,reviews=reviews+?,
                       completed=1,completed_at=COALESCE(completed_at,?),
                       last_error='',updated_at=? WHERE lane=?""",
                    (len(rows), linked, created, reviews, now, now, LANE),
                )
        return FusionResult(len(rows), linked, created, reviews, versions)

    def _state(self, connection, now):
        row = connection.execute(
            "SELECT cursor_version_id FROM world_event_fusion_state WHERE lane=?",
            (LANE,),
        ).fetchone()
        if row:
            return int(row[0])
        connection.execute(
            "INSERT INTO world_event_fusion_state (lane,started_at,updated_at) VALUES (?,?,?)",
            (LANE, now, now),
        )
        return 0

    def _process(self, connection, observation, now):
        current_row = connection.execute(
            """SELECT world_event_id FROM world_event_memberships
               WHERE observation_id=? AND active=1""",
            (observation["id"],),
        ).fetchone()
        current_event = self._resolve_alias(
            connection, current_row[0] if current_row else ""
        )
        predecessor_id, predecessor_event = self._annotate_observation(
            connection, observation
        )
        if predecessor_event:
            event = connection.execute(
                "SELECT * FROM world_events WHERE id=?", (predecessor_event,)
            ).fetchone()
            scored = [{
                "event": dict(event), "score": 1.0,
                "components": {"document_revision": 1.0}, "vetoes": [],
            }] if event else []
        else:
            candidates = self._candidates(connection, observation)
            scored = [self._score(observation, candidate) for candidate in candidates]
        if current_event:
            scored = [
                item for item in scored
                if self._resolve_alias(connection, item["event"]["id"]) != current_event
            ]
        usable = [item for item in scored if not item["vetoes"]]
        best = sorted(
            usable, key=lambda item: (-item["score"], item["event"]["id"])
        )[0] if usable else None

        if best and best["score"] >= self.auto_link_threshold:
            outcome, target = "link", best["event"]["id"]
        elif best and best["score"] >= self.review_threshold:
            outcome, target = "review", best["event"]["id"]
        elif current_event:
            outcome, target = "retain", current_event
        else:
            outcome, target = "create", self._seed_event(
                connection, observation, now
            )

        chosen_decision = None
        for item in scored:
            candidate_id = item["event"]["id"]
            candidate_outcome = outcome if best and candidate_id == best["event"]["id"] else "reject"
            chosen = target if candidate_outcome in {"link", "review"} else ""
            decision_id = self._decision(
                connection, observation["id"], candidate_id, chosen,
                candidate_outcome, item["score"], item["components"],
                item["vetoes"], observation["captured_at"], now,
            )
            if candidate_outcome == outcome:
                chosen_decision = decision_id
        if chosen_decision is None:
            chosen_decision = self._decision(
                connection, observation["id"],
                current_event if outcome == "retain" else "", target, outcome, 0,
                {}, [], observation["captured_at"], now,
            )

        if outcome == "review":
            review_id = _hash("fusion-review", observation["id"], target, METHOD)
            connection.execute(
                """INSERT OR IGNORE INTO world_event_fusion_reviews
                   (id,observation_id,candidate_event_id,decision_id,score,
                    rationale,created_at) VALUES (?,?,?,?,?,?,?)""",
                (review_id, observation["id"], target, chosen_decision,
                 best["score"], _json({"components": best["components"],
                 "vetoes": best["vetoes"]}), now),
            )
            return 0, 0, 1, 0

        if outcome == "retain":
            return 0, 0, 0, 0

        source_event = current_event
        self._membership(
            connection, observation["id"], target, chosen_decision,
            outcome, now,
        )
        if predecessor_id:
            connection.execute(
                """UPDATE world_event_memberships SET active=0,valid_until=?
                   WHERE observation_id=? AND active=1""",
                (now, predecessor_id),
            )
        original = source_event or self._resolve_alias(
            connection, observation.get("world_event_id") or ""
        )
        if original and original != target:
            count = connection.execute(
                "SELECT COUNT(*) FROM world_event_memberships WHERE world_event_id=? AND active=1",
                (original,),
            ).fetchone()[0]
            if count == 0:
                self._alias(connection, original, target, "fused-seed", now)
            else:
                self._recompute(connection, original, now, "link-source")
        version = self._recompute(connection, target, now, outcome)
        return int(outcome == "link"), int(outcome == "create"), 0, version

    def _annotate_observation(self, connection, observation):
        family = (observation.get("reporting_family_key")
                  or observation.get("publisher_key")
                  or observation.get("independence_family")
                  or observation["source_id"])
        predecessor = connection.execute(
            """SELECT prior.id FROM world_event_observations prior
               WHERE prior.document_id=? AND prior.document_version_id<?
               ORDER BY prior.document_version_id DESC LIMIT 1""",
            (observation["document_id"], observation["document_version_id"]),
        ).fetchone()
        predecessor_membership = connection.execute(
            """SELECT world_event_id FROM world_event_memberships
               WHERE observation_id=? AND active=1""",
            (predecessor[0],),
        ).fetchone() if predecessor else None
        connection.execute(
            """UPDATE world_event_observations SET reporting_family_key=?,
               source_policy_version=?,predecessor_observation_id=?,
               status=CASE WHEN ? IN ('deleted','closed') THEN 'corrected'
                           ELSE status END WHERE id=?""",
            (str(family)[:300], observation.get("policy_version") or "",
             predecessor[0] if predecessor else None,
             observation.get("document_status"), observation["id"]),
        )
        if predecessor:
            connection.execute(
                "UPDATE world_event_observations SET status='superseded' WHERE id=? AND status='active'",
                (predecessor[0],),
            )
        return (
            predecessor[0] if predecessor else "",
            predecessor_membership[0] if predecessor_membership else "",
        )

    def _candidates(self, connection, observation):
        occurred = _time(observation.get("feature_occurred_at")
                         or observation.get("occurred_at")
                         or observation.get("published_at")
                         or observation["captured_at"])
        rows = connection.execute(
            """SELECT events.* FROM world_events events
               WHERE events.status NOT IN ('merged','archived')
                 AND EXISTS (SELECT 1 FROM world_event_memberships memberships
                             WHERE memberships.world_event_id=events.id
                               AND memberships.active=1)
                 AND julianday(?) - julianday(COALESCE(events.started_at,
                     events.first_seen_at)) BETWEEN -1 AND ?
               ORDER BY events.last_seen_at DESC,events.id LIMIT ?""",
            (occurred, self.lookback_days, self.max_candidates),
        ).fetchall()
        blocked = set()
        if observation.get("world_event_id"):
            original = self._resolve_alias(connection, observation["world_event_id"])
            constraints = connection.execute(
                """SELECT left_event_id,right_event_id FROM world_event_fusion_constraints
                   WHERE active=1 AND (left_event_id=? OR right_event_id=?)""",
                (original, original),
            ).fetchall()
            for item in constraints:
                blocked.add(item["right_event_id"] if item["left_event_id"] == original else item["left_event_id"])
        return [dict(row) for row in rows if row["id"] not in blocked]

    def _score(self, observation, event):
        left_category = observation.get("document_category") or observation.get("observation_kind") or "general"
        right_category = event.get("category") or event.get("event_type") or "general"
        left_family, right_family = _category_family(left_category), _category_family(right_category)
        compatible = left_family == right_family or frozenset((left_family, right_family)) in COMPATIBLE_FAMILIES
        vetoes = [] if compatible else ["incompatible_category"]
        occurred = _parse_time(observation.get("feature_occurred_at") or observation.get("occurred_at") or observation.get("published_at") or observation["captured_at"])
        event_time = _parse_time(event.get("started_at") or event.get("first_seen_at"))
        hours = abs((occurred - event_time).total_seconds()) / 3600
        temporal = max(0.0, 1.0 - hours / (self.lookback_days * 24))
        if hours > self.lookback_days * 24:
            vetoes.append("temporally_incompatible")
        distance = _distance_km(
            observation.get("latitude"), observation.get("longitude"),
            event.get("latitude"), event.get("longitude"),
        )
        geographic = 0.35 if distance is None else max(0.0, 1.0 - distance / 750)
        if distance is not None and distance > _maximum_distance(left_family):
            vetoes.append("geographically_incompatible")
        if left_family == "hazard" and "earthquake" in str(left_category).lower():
            if hours > 6:
                vetoes.append("distinct_earthquake_time")
            if distance is not None and distance > 75:
                vetoes.append("distinct_earthquake_epicenter")
        left_identifiers = _observation_identifiers(observation)
        right_identifiers = _json_load(event.get("properties"), {}).get(
            "event_identifiers", {}
        )
        shared_identifier_keys = set(left_identifiers) & set(right_identifiers)
        identifier = 0.0
        for key in shared_identifier_keys:
            known = set(str(value) for value in right_identifiers.get(key, []))
            if left_identifiers[key] in known:
                identifier = 1.0
            elif known:
                vetoes.append("conflicting_authoritative_identifier")
        left_tokens = _tokens(observation.get("normalized_title") or observation.get("document_title"))
        right_tokens = _tokens(event.get("title"))
        lexical = len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))
        event_entities = _json_load(event.get("properties"), {}).get("entity_keys", [])
        left_entities = set(_json_load(observation.get("entity_keys"), []))
        right_entities = set(str(value) for value in event_entities)
        entities = len(left_entities & right_entities) / max(1, len(left_entities | right_entities)) if left_entities or right_entities else 0
        category = 1.0 if left_family == right_family else .65
        score = lexical * .27 + temporal * .20 + geographic * .22 + entities * .11 + category * .10 + identifier * .10
        if distance is not None and distance <= 50:
            score += .08
        components = {
            "category": round(category, 4), "temporal": round(temporal, 4),
            "geographic": round(geographic, 4), "lexical": round(lexical, 4),
            "entities": round(entities, 4),
            "identifier": identifier,
            "distance_km": round(distance, 3) if distance is not None else None,
            "hours": round(hours, 3),
        }
        return {"event": event, "score": round(min(1, score), 4),
                "components": components, "vetoes": vetoes}

    def _seed_event(self, connection, observation, now):
        original = self._resolve_alias(
            connection, observation.get("world_event_id") or ""
        )
        if original:
            return original
        event_id = _hash("canonical-event", observation["id"])
        occurred = _time(observation.get("feature_occurred_at")
                         or observation.get("occurred_at")
                         or observation.get("published_at")
                         or observation["captured_at"])
        geometry = _json_load(observation.get("geometry"), {})
        category = observation.get("document_category") or observation.get("observation_kind") or "general"
        connection.execute(
            """INSERT OR IGNORE INTO world_events
               (id,event_type,category,title,status,severity,confidence,latitude,
                longitude,geometry,started_at,first_seen_at,last_seen_at,
                properties,method,created_at,updated_at)
               VALUES (?,?,?,?, 'active',0,?,?,?,?,?,?,?,?,?,?,?)""",
            (event_id, category, category,
             observation.get("document_title") or "Untitled event", .5,
             observation.get("latitude"), observation.get("longitude"),
             _json(geometry), occurred, observation["captured_at"],
             observation["captured_at"], "{}", METHOD, now, now),
        )
        return event_id

    def _decision(self, connection, observation_id, candidate_id, chosen_id,
                  outcome, score, components, vetoes, cutoff, now):
        decision_id = _hash("fusion-decision", observation_id, candidate_id,
                            METHOD, FEATURE_VERSION)
        connection.execute(
            """INSERT OR IGNORE INTO world_event_fusion_decisions
               (id,observation_id,candidate_event_id,chosen_event_id,outcome,
                score,components,vetoes,cutoff_at,feature_version,method,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (decision_id, observation_id, candidate_id, chosen_id, outcome,
             score, _json(components), _json(vetoes), cutoff,
             FEATURE_VERSION, METHOD, now),
        )
        return decision_id

    def _membership(self, connection, observation_id, event_id, decision_id,
                    action, now):
        current = connection.execute(
            "SELECT * FROM world_event_memberships WHERE observation_id=? AND active=1",
            (observation_id,),
        ).fetchone()
        if current and current["world_event_id"] == event_id:
            return current["id"]
        if current:
            connection.execute(
                "UPDATE world_event_memberships SET active=0,valid_until=? WHERE id=?",
                (now, current["id"]),
            )
        member_id = _hash("event-membership", observation_id, event_id,
                          decision_id or "", now)
        connection.execute(
            """INSERT INTO world_event_memberships
               (id,observation_id,world_event_id,decision_id,action,method,
                valid_from,created_at) VALUES (?,?,?,?,?,?,?,?)""",
            (member_id, observation_id, event_id, decision_id, action,
             METHOD, now, now),
        )
        connection.execute(
            "UPDATE world_event_observations SET world_event_id=? WHERE id=?",
            (event_id, observation_id),
        )
        return member_id

    def _recompute(self, connection, event_id, now, reason):
        rows = connection.execute(
            """SELECT observations.*,
                      COALESCE(json_extract(observations.properties,'$.title'),documents.title) document_title,
                      documents.category document_category,
                      COALESCE(assessment.effective_credibility,
                               reputation.learned_credibility,
                               sources.credibility) credibility,
                      policies.evidence_role
               FROM world_event_memberships memberships
               JOIN world_event_observations observations
                 ON observations.id=memberships.observation_id
               JOIN documents ON documents.id=observations.document_id
               JOIN sources ON sources.id=observations.source_id
               LEFT JOIN publisher_reputation reputation
                 ON reputation.publisher_key=documents.publisher_key
               LEFT JOIN publisher_assessments assessment
                 ON assessment.publisher_key=documents.publisher_key
                AND assessment.scope_kind='global'
                AND assessment.scope_value=''
               LEFT JOIN source_policies policies ON policies.source_id=sources.id
               WHERE memberships.world_event_id=? AND memberships.active=1
                 AND observations.status='active'
               ORDER BY observations.captured_at,observations.id""",
            (event_id,),
        ).fetchall()
        if not rows:
            return 0
        values = [dict(row) for row in rows]
        families = {row["reporting_family_key"] or row["source_id"] for row in values}
        sources = {row["source_id"] for row in values}
        latitudes = [float(row["latitude"]) for row in values if row["latitude"] is not None]
        longitudes = [float(row["longitude"]) for row in values if row["longitude"] is not None]
        location = (latitudes[-1], longitudes[-1]) if latitudes and longitudes else (None, None)
        confidence = min(.98, .42 + .14 * len(families) + .04 * min(4, len(values)))
        title = sorted(values, key=lambda row: (
            -float(row.get("credibility") or 0), row["captured_at"], row["id"]
        ))[0]["document_title"]
        categories = [row["document_category"] for row in values]
        category = max(sorted(set(categories)), key=categories.count)
        started = min(_time(row.get("occurred_at") or row.get("published_at") or row["captured_at"]) for row in values)
        last_seen = max(row["captured_at"] for row in values)
        properties = {
            "fusion_method": METHOD,
            "entity_keys": sorted(set().union(*[
                set(_json_load(row.get("properties"), {}).get("entity_keys", []))
                for row in values
            ])),
            "event_identifiers": _combined_identifiers(values),
        }
        freshness = "current" if (
            _parse_time(now) - _parse_time(last_seen)
        ).total_seconds() <= 172800 else "stale"
        snapshot = {
            "id": event_id, "title": title, "category": category,
            "status": "active", "confidence": round(confidence, 4),
            "latitude": location[0], "longitude": location[1],
            "started_at": started, "last_seen_at": last_seen,
            "observation_count": len(values), "source_count": len(sources),
            "independent_family_count": len(families),
            "freshness": freshness, "properties": properties,
        }
        membership_ids = [row["id"] for row in connection.execute(
            "SELECT id FROM world_event_memberships WHERE world_event_id=? AND active=1 ORDER BY observation_id",
            (event_id,),
        ).fetchall()]
        membership_hash = _hash(*membership_ids)
        version_hash = _hash(_json(snapshot), membership_hash, METHOD)
        inserted = connection.execute(
            """INSERT OR IGNORE INTO world_event_versions
               (world_event_id,version_hash,membership_hash,snapshot,cutoff_at,
                method,reason,created_at) VALUES (?,?,?,?,?,?,?,?)""",
            (event_id, version_hash, membership_hash, _json(snapshot),
             last_seen, METHOD, reason, now),
        ).rowcount
        version = connection.execute(
            "SELECT id FROM world_event_versions WHERE world_event_id=? AND version_hash=?",
            (event_id, version_hash),
        ).fetchone()[0]
        connection.execute(
            """UPDATE world_events SET title=?,event_type=?,category=?,status='active',
               confidence=?,latitude=?,longitude=?,started_at=?,last_seen_at=?,
               observation_count=?,source_count=?,independent_family_count=?,
               freshness=?,properties=?,method=?,current_version_id=?,
               updated_at=? WHERE id=?""",
            (title, category, category, confidence, location[0], location[1],
             started, last_seen, len(values), len(sources), len(families),
             freshness, _json(properties), METHOD, version, now, event_id),
        )
        return int(inserted > 0)

    def resolve_review(self, review_id, resolution, rationale=""):
        """Resolve a pending review as link or separate with a reversible audit."""
        resolution = str(resolution).strip().lower()
        if resolution not in {"link", "separate"}:
            raise ValueError("review resolution must be link or separate")
        now = self.clock()
        with self.store._connect() as connection:
            review = connection.execute(
                "SELECT * FROM world_event_fusion_reviews WHERE id=? AND status='pending'",
                (str(review_id),),
            ).fetchone()
            if not review:
                raise ValueError("pending fusion review was not found")
            observation = connection.execute(
                "SELECT * FROM world_event_observations WHERE id=?",
                (review["observation_id"],),
            ).fetchone()
            if not observation:
                raise ValueError("review observation was not found")
            current = connection.execute(
                "SELECT world_event_id FROM world_event_memberships WHERE observation_id=? AND active=1",
                (review["observation_id"],),
            ).fetchone()
            before = {review["observation_id"]: current[0]} if current else {}
            if resolution == "link":
                target = self._resolve_alias(connection, review["candidate_event_id"])
            else:
                values = dict(observation)
                properties = _json_load(values.get("properties"), {})
                values["document_title"] = properties.get("title") or "Reviewed event"
                values["document_category"] = values.get("observation_kind") or "general"
                values["feature_occurred_at"] = values.get("occurred_at")
                values["world_event_id"] = ""
                target = self._seed_event(connection, values, now)
            operation_id = _hash("fusion-operation", "review", review_id, resolution, now)
            self._membership(
                connection, review["observation_id"], target,
                review["decision_id"], "review-" + resolution, now,
            )
            after = {review["observation_id"]: target}
            self._operation(connection, operation_id, "review-" + resolution,
                            before, after, rationale, now)
            if resolution == "separate":
                self._constraint(connection, target,
                                 review["candidate_event_id"], operation_id, now)
            connection.execute(
                """UPDATE world_event_fusion_reviews SET status=?,resolved_at=?,
                   resolution_operation_id=? WHERE id=?""",
                ("linked" if resolution == "link" else "separate", now,
                 operation_id, review_id),
            )
            self._recompute(connection, target, now, "review-" + resolution)
            return operation_id, target

    def reattribute_observation(self, observation_id, target_event_id,
                                rationale=""):
        now = self.clock()
        with self.store._connect() as connection:
            target = self._resolve_alias(connection, target_event_id)
            current = connection.execute(
                "SELECT world_event_id FROM world_event_memberships WHERE observation_id=? AND active=1",
                (observation_id,),
            ).fetchone()
            if not target or not current:
                raise ValueError("observation membership or target event was not found")
            source = current[0]
            if source == target:
                raise ValueError("observation is already assigned to target event")
            before = {observation_id: source}
            operation_id = _hash("fusion-operation", "reattribute",
                                 observation_id, target, now)
            self._membership(connection, observation_id, target, None,
                             "reattribute", now)
            self._operation(connection, operation_id, "reattribute", before,
                            {observation_id: target}, rationale, now)
            self._constraint(connection, source, target, operation_id, now)
            self._recompute(connection, source, now, "reattribute")
            self._recompute(connection, target, now, "reattribute")
            return operation_id

    def merge_events(self, left_event_id, right_event_id, rationale=""):
        now = self.clock()
        with self.store._connect() as connection:
            left = self._resolve_alias(connection, left_event_id)
            right = self._resolve_alias(connection, right_event_id)
            if not left or not right or left == right:
                raise ValueError("merge requires two distinct existing events")
            records = connection.execute(
                "SELECT id,created_at FROM world_events WHERE id IN (?,?)",
                (left, right),
            ).fetchall()
            if len(records) != 2:
                raise ValueError("merge event was not found")
            winner, loser = sorted(records, key=lambda row: (row["created_at"], row["id"]))
            before = self._membership_snapshot(connection, (left, right))
            operation_id = _hash("fusion-operation", "merge", left, right, now)
            for observation_id, event_id in before.items():
                if event_id == loser["id"]:
                    self._membership(connection, observation_id, winner["id"], None, "merge", now)
            self._alias(connection, loser["id"], winner["id"], "merge", now, operation_id)
            after = self._membership_snapshot(connection, (left, right))
            self._operation(connection, operation_id, "merge", before, after, rationale, now)
            self._recompute(connection, winner["id"], now, "merge")
            return operation_id

    def split_event(self, event_id, observation_ids, rationale=""):
        selected = sorted(set(str(value) for value in observation_ids if value))
        if not selected:
            raise ValueError("split requires observations")
        now = self.clock()
        with self.store._connect() as connection:
            source = self._resolve_alias(connection, event_id)
            before = self._membership_snapshot(connection, (source,))
            if any(before.get(value) != source for value in selected):
                raise ValueError("split observation is not an active event member")
            target = _hash("canonical-event-split", source, *selected)
            seed = connection.execute(
                "SELECT * FROM world_event_observations WHERE id=?", (selected[0],)
            ).fetchone()
            if not seed:
                raise ValueError("split observation was not found")
            values = dict(seed)
            values["document_title"] = _json_load(values.get("properties"), {}).get("title") or "Split event"
            values["document_category"] = values.get("observation_kind") or "general"
            values["feature_occurred_at"] = values.get("occurred_at")
            values["world_event_id"] = ""
            created = self._seed_event_with_id(connection, values, target, now)
            operation_id = _hash("fusion-operation", "split", source, target, now)
            for observation_id in selected:
                self._membership(connection, observation_id, created, None, "split", now)
            after = self._membership_snapshot(connection, (source, created))
            self._operation(connection, operation_id, "split", before, after, rationale, now)
            self._constraint(connection, source, created, operation_id, now)
            self._recompute(connection, source, now, "split")
            self._recompute(connection, created, now, "split")
            return operation_id, created

    def rollback_operation(self, operation_id):
        now = self.clock()
        with self.store._connect() as connection:
            row = connection.execute(
                "SELECT * FROM world_event_operations WHERE id=? AND status='applied'",
                (operation_id,),
            ).fetchone()
            if not row:
                raise ValueError("applied fusion operation was not found")
            before = _json_load(row["before_snapshot"], {})
            after = _json_load(row["after_snapshot"], {})
            affected = set(before.values()) | set(after.values())
            for observation_id in set(after) - set(before):
                connection.execute(
                    """UPDATE world_event_memberships SET active=0,valid_until=?
                       WHERE observation_id=? AND active=1""",
                    (now, observation_id),
                )
            for observation_id, event_id in before.items():
                self._membership(connection, observation_id, event_id, None, "rollback", now)
            connection.execute(
                "UPDATE world_event_operations SET status='reversed',reversed_at=? WHERE id=?",
                (now, operation_id),
            )
            connection.execute(
                "UPDATE world_event_aliases SET status='reversed',updated_at=? WHERE operation_id=?",
                (now, operation_id),
            )
            connection.execute(
                "UPDATE world_event_fusion_constraints SET active=0 WHERE operation_id=?",
                (operation_id,),
            )
            for event_id in affected:
                active = connection.execute(
                    "SELECT COUNT(*) FROM world_event_memberships WHERE world_event_id=? AND active=1",
                    (event_id,),
                ).fetchone()[0]
                if active:
                    self._recompute(connection, event_id, now, "rollback")
                else:
                    connection.execute(
                        "UPDATE world_events SET status='merged',updated_at=? WHERE id=?",
                        (now, event_id),
                    )
            return len(before)

    def _seed_event_with_id(self, connection, observation, event_id, now):
        occurred = _time(observation.get("feature_occurred_at") or observation.get("occurred_at") or observation["captured_at"])
        connection.execute(
            """INSERT OR IGNORE INTO world_events
               (id,event_type,category,title,status,severity,confidence,latitude,
                longitude,geometry,started_at,first_seen_at,last_seen_at,
                properties,method,created_at,updated_at)
               VALUES (?,?,?,?, 'active',0,.5,?,?,?,?,?,?,'{}',?,?,?)""",
            (event_id, observation.get("document_category") or "general",
             observation.get("document_category") or "general",
             observation.get("document_title") or "Untitled event",
             observation.get("latitude"), observation.get("longitude"),
             observation.get("geometry") or "{}", occurred,
             observation["captured_at"], observation["captured_at"],
             METHOD, now, now),
        )
        return event_id

    def _membership_snapshot(self, connection, event_ids):
        placeholders = ",".join("?" for _ in event_ids)
        rows = connection.execute(
            f"SELECT observation_id,world_event_id FROM world_event_memberships WHERE active=1 AND world_event_id IN ({placeholders}) ORDER BY observation_id",
            tuple(event_ids),
        ).fetchall()
        return {row["observation_id"]: row["world_event_id"] for row in rows}

    def _operation(self, connection, operation_id, kind, before, after,
                   rationale, now):
        connection.execute(
            """INSERT INTO world_event_operations
               (id,operation_type,before_snapshot,after_snapshot,rationale,
                method,created_at) VALUES (?,?,?,?,?,?,?)""",
            (operation_id, kind, _json(before), _json(after),
             str(rationale)[:1000], METHOD, now),
        )

    def _constraint(self, connection, left, right, operation_id, now):
        left, right = sorted((left, right))
        connection.execute(
            """INSERT OR REPLACE INTO world_event_fusion_constraints
               (left_event_id,right_event_id,constraint_type,operation_id,
                active,created_at) VALUES (?,?,'separate',?,1,?)""",
            (left, right, operation_id, now),
        )

    def _alias(self, connection, alias, canonical, reason, now,
               operation_id=None):
        if alias == canonical:
            return
        connection.execute(
            """INSERT INTO world_event_aliases
               (alias_event_id,canonical_event_id,operation_id,reason,
                created_at,updated_at) VALUES (?,?,?,?,?,?)
               ON CONFLICT(alias_event_id) DO UPDATE SET
               canonical_event_id=excluded.canonical_event_id,
               operation_id=excluded.operation_id,status='active',
               reason=excluded.reason,updated_at=excluded.updated_at""",
            (alias, canonical, operation_id, reason, now, now),
        )
        connection.execute(
            "UPDATE world_events SET status='merged',updated_at=? WHERE id=?",
            (now, alias),
        )

    def _resolve_alias(self, connection, event_id):
        current, seen = str(event_id or ""), set()
        while current and current not in seen:
            seen.add(current)
            row = connection.execute(
                "SELECT canonical_event_id FROM world_event_aliases WHERE alias_event_id=? AND status='active'",
                (current,),
            ).fetchone()
            if not row:
                exists = connection.execute(
                    "SELECT 1 FROM world_events WHERE id=?", (current,)
                ).fetchone()
                return current if exists else ""
            current = row[0]
        return ""


def _hash(*values):
    return hashlib.sha256(":".join(str(value) for value in values).encode()).hexdigest()


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _json_load(value, default):
    try:
        return json.loads(value or "")
    except (TypeError, ValueError):
        return default


def _tokens(value):
    return set(re.findall(r"[a-z0-9]{3,}", str(value or "").lower()))


def _observation_identifiers(observation):
    properties = _json_load(observation.get("properties"), {})
    metadata = properties.get("metadata") if isinstance(
        properties.get("metadata"), dict
    ) else {}
    source_id = str(observation.get("source_id") or "")
    identifiers = {}
    for key, value in metadata.items():
        normalized = str(key).strip().lower()
        if normalized not in IDENTIFIER_KEYS or value in (None, ""):
            continue
        if isinstance(value, (str, int, float)):
            identifiers[f"{source_id}:{normalized}"] = str(value)[:200]
    return identifiers


def _combined_identifiers(observations):
    combined = {}
    for observation in observations:
        for key, value in _observation_identifiers(observation).items():
            combined.setdefault(key, set()).add(value)
    return {
        key: sorted(values) for key, values in sorted(combined.items())
    }


def _time(value):
    parsed = _parse_time(value)
    return parsed.isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_time(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return datetime.now(UTC)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _category_family(value):
    text = str(value or "").lower()
    if any(token in text for token in ("earthquake", "flood", "storm", "fire", "volcano", "hazard")):
        return "hazard"
    if any(token in text for token in ("conflict", "battle", "violence", "protest")):
        return "conflict"
    if any(token in text for token in ("outbreak", "health", "disease")):
        return "health"
    if any(token in text for token in ("emergency", "humanitarian", "disaster")):
        return "emergency"
    if any(token in text for token in ("news", "social", "report")):
        return "news"
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-") or "general"


def _maximum_distance(family):
    return {"hazard": 250, "conflict": 300, "emergency": 500}.get(family, 1000)


def _distance_km(lat_a, lon_a, lat_b, lon_b):
    if None in (lat_a, lon_a, lat_b, lon_b):
        return None
    try:
        lat_a, lon_a, lat_b, lon_b = map(math.radians, map(float, (lat_a, lon_a, lat_b, lon_b)))
    except (TypeError, ValueError):
        return None
    delta_lat, delta_lon = lat_b - lat_a, lon_b - lon_a
    value = math.sin(delta_lat / 2) ** 2 + math.cos(lat_a) * math.cos(lat_b) * math.sin(delta_lon / 2) ** 2
    return 6371 * 2 * math.atan2(math.sqrt(value), math.sqrt(max(0, 1 - value)))


def _advance_scheduler_cursor(connection, engine, rotation_key, now):
    connection.execute(
        """INSERT INTO intelligence_scheduler_state (
             engine,last_rotation_key,updated_at
           ) VALUES (?,?,?)
           ON CONFLICT(engine) DO UPDATE SET
             last_rotation_key=excluded.last_rotation_key,
             updated_at=excluded.updated_at""",
        (str(engine)[:120], str(rotation_key or "")[:300], now),
    )
