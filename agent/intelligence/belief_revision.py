"""Deterministic claim graph, truth maintenance, and scoped reliability."""

import hashlib
import json
import math
from dataclasses import dataclass
from uuid import uuid4

from agent.intelligence.store import utc_now
from agent.intelligence.topic_taxonomy import normalize_topic, TOPIC_ALIASES
from agent.intelligence.verification import VerificationPlanner


SINGLE_VALUE = {
    "event.alert_level", "event.closed", "event.location", "event.status",
    "seismic.magnitude", "seismic.tsunami"
}
AUTHORITATIVE_KINDS = {
    "earthquake", "weather", "cybersecurity", "public-health",
    "government", "official", "economic-indicator", "natural_hazard",
    "weather_alert", "public_health", "economic_indicator", "space_weather"
}


@dataclass(frozen=True)
class BeliefRevisionResult:
    claims_processed: int = 0
    relations_created: int = 0
    claims_resolved: int = 0
    verification_tasks_created: int = 0
    reliability_cells_updated: int = 0


class BeliefRevisionEngine:
    method = "truth-maintenance-v1"
    backfill_name = "belief-revision-v1"

    def __init__(self, store, enabled=True, batch_size=50, prior_strength=8.0,
                 min_positive_outcomes=12):
        self.store = store
        self.enabled = bool(enabled)
        self.batch_size = max(1, min(200, int(batch_size)))
        self.prior_strength = max(2.0, min(100.0, float(prior_strength)))
        self.min_positive_outcomes = max(3, int(min_positive_outcomes))
        self.verification = VerificationPlanner(store, batch_size=batch_size)

    def run_batch(self):
        if not self.enabled:
            return BeliefRevisionResult()
        now = utc_now()
        with self.store._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._ensure_publishers(connection, now)
            state = self._state(connection, now)
            rows = connection.execute(
                """
                SELECT rowid AS claim_rowid, * FROM claims
                WHERE rowid > ? AND extraction_version = 'hybrid-claims-v1'
                ORDER BY rowid LIMIT ?
                """,
                (state["cursor_rowid"], self.batch_size)
            ).fetchall()
            if not rows:
                connection.execute(
                    "UPDATE epistemic_backfill_state SET completed=1, "
                    "completed_at=?, updated_at=? WHERE name=?",
                    (now, now, self.backfill_name)
                )
                return BeliefRevisionResult()
            situations = {row["situation_id"] for row in rows}
            relation_count = resolved = 0
            touched_claims = set()
            for situation_id in situations:
                relation_count += self._build_relations(
                    connection, situation_id, now
                )
                for claim in connection.execute(
                    "SELECT * FROM claims WHERE situation_id = ? "
                    "AND extraction_version = 'hybrid-claims-v1'",
                    (situation_id,)
                ):
                    touched_claims.add(claim["id"])
                    resolved += self._resolve_claim(connection, claim, now)
            tasks = self.verification.plan(connection, touched_claims)
            cells = self._recalculate_reliability(connection, now)
            if int(state["processed"] or 0) % 500 == 0:
                self._refresh_content_profiles(connection, now)
            connection.execute(
                """
                UPDATE epistemic_backfill_state SET cursor_rowid=?,
                  processed=processed+?, updated=updated+?, updated_at=?,
                  completed=0, completed_at=NULL, last_error=''
                WHERE name=?
                """,
                (rows[-1]["claim_rowid"], len(rows), resolved, now,
                 self.backfill_name)
            )
        return BeliefRevisionResult(
            len(rows), relation_count, resolved, tasks, cells
        )

    def apply_verification_results(self, limit=100):
        """Apply each decisive verifier result exactly once, with provenance."""
        if not self.enabled:
            return 0
        now = utc_now()
        applied = 0
        with self.store._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT results.*,versions.document_id
                FROM claim_verification_results results
                LEFT JOIN document_versions versions
                  ON versions.id=results.document_version_id
                LEFT JOIN claim_verification_applications applications
                  ON applications.result_id=results.id
                WHERE applications.result_id IS NULL
                ORDER BY results.id LIMIT ?
                """, (max(1, min(500, int(limit))),)
            ).fetchall()
            for result in rows:
                claim = connection.execute(
                    "SELECT * FROM claims WHERE id=?", (result["claim_id"],)
                ).fetchone()
                if not claim:
                    continue
                status = {
                    "supports": "corroborated",
                    "refutes": "refuted",
                    "mixed": "disputed",
                    "revises": "superseded"
                }.get(result["result"], "unverified")
                confidence = max(0.0, min(.99, float(result["confidence"] or 0)))
                previous = claim["truth_status"]
                previous_confidence = float(claim["resolution_confidence"] or 0)
                established_conflict = (
                    {previous, status} == {"corroborated", "refuted"}
                    and confidence <= previous_confidence + .1
                )
                if established_conflict:
                    status = "disputed"
                    confidence = min(.7, max(confidence, previous_confidence))
                if status != "unverified":
                    digest = hashlib.sha256(
                        f"verification-result:{result['id']}".encode()
                    ).hexdigest()
                    connection.execute(
                        "UPDATE claims SET truth_status=?,status=CASE WHEN ?="
                        "'superseded' THEN 'superseded' ELSE status END,"
                        "resolution_confidence=?,last_resolved_at=?,"
                        "resolver_version=?,updated_at=? WHERE id=?",
                        (status, status, round(confidence, 4), now,
                         "verification-result-v1", now, claim["id"])
                    )
                    if status == "superseded":
                        self._materialize_revision(
                            connection, claim, result, confidence, now
                        )
                    connection.execute(
                        """
                        INSERT INTO claim_resolution_history (
                          claim_id,previous_status,truth_status,confidence,
                          evidence_document_ids,reason,method,input_snapshot_hash,
                          created_at
                        ) VALUES (?,?,?,?,?,?,?,?,?)
                        """,
                        (claim["id"], previous, status, round(confidence, 4),
                         self.store._json(
                             [result["document_id"]]
                             if result["document_id"] else []
                         ), result["reason"], "verification-result-v1",
                         digest, now)
                    )
                    self._record_verified_publisher_outcomes(
                        connection, claim, result, status, confidence, now
                    )
                connection.execute(
                    """
                    INSERT INTO claim_verification_applications (
                      result_id,claim_id,applied_status,previous_status,
                      confidence,method,applied_at
                    ) VALUES (?,?,?,?,?,?,?)
                    """,
                    (result["id"], claim["id"], status, previous,
                     round(confidence, 4), "verification-result-v1", now)
                )
                applied += 1
            if applied:
                self._recalculate_reliability(connection, now)
        return applied

    def _materialize_revision(self, connection, claim, result, confidence, now):
        try:
            observed = json.loads(result["observed_value"] or "{}")
        except (TypeError, ValueError):
            observed = {}
        key = {
            "seismic.magnitude":"magnitude", "event.status":"status",
            "event.alert_level":"alert_level", "economic.value":"value",
            "cyber.known_exploited":"known_exploited"
        }.get(claim["predicate"])
        value = observed.get(key) if key else None
        if value is None:
            return
        object_value = str(value)
        normalized = object_value.strip().lower()
        connection.execute(
            """
            INSERT OR IGNORE INTO claims (
              id,situation_id,subject,predicate,object,normalized_object,status,
              confidence,first_seen_at,last_seen_at,created_at,updated_at,
              claim_type,verifiability,attribution,topic,attributed_to,
              endorsement,extraction_confidence,extraction_method,
              extraction_version,precision,evidence_role,truth_status,
              resolution_confidence,core_importance,last_resolved_at,
              resolver_version
            ) VALUES (?,?,?,?,?,?,'active',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (str(uuid4()),claim["situation_id"],claim["subject"],
             claim["predicate"],object_value,normalized,round(confidence,4),
             now,now,now,now,claim["claim_type"],claim["verifiability"],
             "authoritative_revision",claim["topic"],claim["attributed_to"],
             "asserts",round(confidence,4),"authoritative-verification",
             "typed-verification-v1",claim["precision"],"primary",
             "corroborated",round(confidence,4),claim["core_importance"],now,
             "verification-result-v1")
        )

    def _record_verified_publisher_outcomes(self, connection, claim, result,
                                            status, confidence, now):
        if status not in {"corroborated", "refuted"}:
            return
        evidence = connection.execute(
            """
            SELECT DISTINCT documents.publisher_key,documents.id AS document_id,
              evidence.document_version_id
            FROM claim_evidence evidence
            JOIN document_versions versions
              ON versions.id=evidence.document_version_id
            JOIN documents ON documents.id=versions.document_id
            JOIN sources ON sources.id=documents.source_id
            WHERE evidence.claim_id=? AND evidence.stance='supports'
              AND sources.kind NOT IN ('private_mail','prediction_market')
            """, (claim["id"],)
        ).fetchall()
        for item in evidence:
            # A publisher never earns an accuracy outcome from its own document.
            if item["document_version_id"] == result["document_version_id"]:
                continue
            connection.execute(
                """
                INSERT OR IGNORE INTO publisher_claim_outcomes (
                  publisher_key,claim_id,topic,claim_type,outcome,confidence,
                  evidence_document_ids,method,evaluated_at
                ) VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (item["publisher_key"], claim["id"],
                 normalize_topic(claim["topic"]), claim["claim_type"],
                 "confirmed" if status == "corroborated" else "refuted",
                 round(confidence, 4),
                 self.store._json(
                     [result["document_id"]]
                     if result["document_id"] else []
                 ), "verification-result-v1", now)
            )

    def _ensure_publishers(self, connection, now):
        connection.execute(
            """
            INSERT OR IGNORE INTO publisher_reputation (
              publisher_key,publisher_label,source_id,baseline_credibility,
              learned_credibility,reliability_lower_bound,
              reliability_upper_bound,created_at,updated_at
            )
            SELECT documents.publisher_key,MAX(documents.publisher_label),
              MAX(documents.source_id),MAX(sources.credibility),
              MAX(sources.credibility),0.0,1.0,?,?
            FROM documents JOIN sources ON sources.id=documents.source_id
            WHERE documents.publisher_key!=''
              AND sources.kind NOT IN ('private_mail','prediction_market')
            GROUP BY documents.publisher_key
            """, (now, now)
        )

    def _state(self, connection, now):
        row = connection.execute(
            "SELECT * FROM epistemic_backfill_state WHERE name=?",
            (self.backfill_name,)
        ).fetchone()
        if row is None:
            connection.execute(
                "INSERT INTO epistemic_backfill_state "
                "(name,version,started_at,updated_at) VALUES (?,?,?,?)",
                (self.backfill_name, self.method, now, now)
            )
        elif row["version"] != self.method:
            connection.execute(
                "UPDATE epistemic_backfill_state SET version=?,cursor_rowid=0,"
                "processed=0,updated=0,completed=0,started_at=?,updated_at=?,"
                "completed_at=NULL,last_error='' WHERE name=?",
                (self.method, now, now, self.backfill_name)
            )
        elif row["completed"]:
            remaining = connection.execute(
                "SELECT 1 FROM claims WHERE rowid>? AND extraction_version="
                "'hybrid-claims-v1' LIMIT 1", (row["cursor_rowid"],)
            ).fetchone()
            if remaining:
                connection.execute(
                    "UPDATE epistemic_backfill_state SET completed=0," 
                    "completed_at=NULL,updated_at=? WHERE name=?",
                    (now, self.backfill_name)
                )
        return connection.execute(
            "SELECT * FROM epistemic_backfill_state WHERE name=?",
            (self.backfill_name,)
        ).fetchone()

    def _build_relations(self, connection, situation_id, now):
        claims = connection.execute(
            "SELECT * FROM claims WHERE situation_id=? AND status!='superseded'",
            (situation_id,)
        ).fetchall()
        created = 0
        for left in claims:
            for right in claims:
                if left["id"] >= right["id"]:
                    continue
                relation = None
                confidence = 0.85
                if (
                    left["predicate"] == right["predicate"]
                    and left["normalized_object"] != right["normalized_object"]
                    and left["predicate"] in SINGLE_VALUE
                ):
                    relation = "contradicts"
                elif (
                    left["predicate"] == right["predicate"]
                    and left["normalized_object"] == right["normalized_object"]
                ):
                    relation = "supports"
                    confidence = 0.95
                if relation is None:
                    continue
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO claim_relations (
                      left_claim_id,right_claim_id,relationship,confidence,
                      method,created_at,updated_at
                    ) VALUES (?,?,?,?,?,?,?)
                    """,
                    (left["id"], right["id"], relation, confidence,
                     self.method, now, now)
                )
                created += int(cursor.rowcount > 0)
        return created

    def _resolve_claim(self, connection, claim, now):
        evidence = connection.execute(
            """
            SELECT documents.id AS document_id, documents.publisher_key,
                   COALESCE(NULLIF(documents.reporting_family_key,''),
                            NULLIF(documents.publisher_key,''),documents.source_id)
                     AS family_key,
                   sources.kind AS source_kind, claim_evidence.source_weight
            FROM claim_evidence
            JOIN document_versions ON document_versions.id=claim_evidence.document_version_id
            JOIN documents ON documents.id=document_versions.document_id
            JOIN sources ON sources.id=documents.source_id
            WHERE claim_evidence.claim_id=? AND claim_evidence.stance='supports'
            """, (claim["id"],)
        ).fetchall()
        family_weights = {}
        authoritative = False
        for item in evidence:
            family_weights[item["family_key"]] = max(
                family_weights.get(item["family_key"], 0.0),
                float(item["source_weight"] or 0.0)
            )
            authoritative |= item["source_kind"] in AUTHORITATIVE_KINDS
        contrary = connection.execute(
            """
            SELECT CASE WHEN left_claim_id=? THEN right_claim_id ELSE left_claim_id END id
            FROM claim_relations WHERE relationship='contradicts'
              AND (left_claim_id=? OR right_claim_id=?)
            """, (claim["id"], claim["id"], claim["id"])
        ).fetchall()
        contrary_ids = [row["id"] for row in contrary]
        old = claim["truth_status"]
        status = "unverified"
        confidence = min(0.98, 1.0 - math.prod(
            1.0 - min(0.95, weight * 0.75)
            for weight in family_weights.values()
        )) if family_weights else 0.0
        factual = claim["claim_type"] not in {
            "causal_claim", "interpretation", "prediction"
        }
        if factual and (authoritative or len(family_weights) >= 2):
            status = "corroborated"
        if contrary_ids:
            other = connection.execute(
                "SELECT MAX(resolution_confidence) FROM claims WHERE id IN (%s)"
                % ",".join("?" for _ in contrary_ids), contrary_ids
            ).fetchone()[0]
            if other and float(other) >= max(0.7, confidence):
                status, confidence = "refuted", float(other)
            elif status == "corroborated":
                status, confidence = "disputed", min(confidence, 0.65)
        if not factual and len(family_weights) >= 2:
            status = "disputed" if contrary_ids else "indeterminate"
            confidence = min(confidence, 0.55)
        confidence = round(max(0.0, min(0.99, confidence)), 4)
        if status == old and abs(confidence-float(claim["resolution_confidence"] or 0)) < .0001:
            return 0
        snapshot = {
            "claim": claim["id"], "families": sorted(family_weights),
            "contrary": sorted(contrary_ids), "authoritative": authoritative
        }
        digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
        connection.execute(
            "UPDATE claims SET truth_status=?,resolution_confidence=?,"
            "last_resolved_at=?,resolver_version=?,updated_at=? WHERE id=?",
            (status, confidence, now, self.method, now, claim["id"])
        )
        connection.execute(
            """
            INSERT INTO claim_resolution_history (
              claim_id,previous_status,truth_status,confidence,
              contradicting_claim_ids,evidence_document_ids,reason,method,
              input_snapshot_hash,created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (claim["id"], old, status, confidence, self.store._json(contrary_ids),
             self.store._json([row["document_id"] for row in evidence]),
             "Independent-family deterministic truth maintenance.", self.method,
             digest, now)
        )
        if status in {"corroborated", "refuted"}:
            self._record_publisher_outcomes(connection, claim, evidence, status,
                                            confidence, now)
        return 1

    def _record_publisher_outcomes(self, connection, claim, evidence, status,
                                   confidence, now):
        families = {row["family_key"] for row in evidence}
        for item in evidence:
            # Leave-one-family-out: a positive result needs another independent
            # family or an authoritative verifier.
            others = families - {item["family_key"]}
            if status == "corroborated" and not others:
                continue
            outcome = "confirmed" if status == "corroborated" else "refuted"
            connection.execute(
                """
                INSERT OR IGNORE INTO publisher_claim_outcomes (
                  publisher_key,claim_id,topic,claim_type,outcome,confidence,
                  evidence_document_ids,method,evaluated_at
                ) VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (item["publisher_key"], claim["id"],
                 normalize_topic(claim["topic"]), claim["claim_type"], outcome,
                 confidence, self.store._json([row["document_id"] for row in evidence
                                               if row["family_key"] != item["family_key"]]),
                 self.method, now)
            )

    def _recalculate_reliability(self, connection, now):
        groups = connection.execute(
            """
            SELECT outcomes.publisher_key,outcomes.topic,outcomes.claim_type,
              reputation.baseline_credibility AS baseline,
              SUM(outcomes.outcome='confirmed') confirmed,
              SUM(outcomes.outcome='refuted') refuted,
              SUM(outcomes.outcome='mixed') mixed,
              SUM(CASE WHEN outcomes.outcome='confirmed' THEN outcomes.confidence ELSE 0 END) success_weight,
              SUM(CASE WHEN outcomes.outcome='refuted' THEN outcomes.confidence ELSE 0 END) failure_weight,
              COUNT(*) evaluated
            FROM publisher_claim_outcomes outcomes
            JOIN publisher_reputation reputation USING(publisher_key)
            GROUP BY outcomes.publisher_key,outcomes.topic,outcomes.claim_type
            """
        ).fetchall()
        updated = 0
        for row in groups:
            baseline = float(row["baseline"])
            alpha = baseline*self.prior_strength + float(row["success_weight"] or 0)
            beta = (1-baseline)*self.prior_strength + float(row["failure_weight"] or 0)*1.5
            mean = alpha/(alpha+beta)
            variance = alpha*beta/((alpha+beta)**2*(alpha+beta+1))
            deviation = math.sqrt(max(0.0, variance))
            learned = baseline if row["evaluated"] < self.min_positive_outcomes and not row["refuted"] else mean
            learned = max(baseline-0.2, min(baseline+0.2, learned))
            previous = connection.execute(
                "SELECT learned_reliability FROM publisher_reliability_cells "
                "WHERE publisher_key=? AND topic=? AND claim_type=?",
                (row["publisher_key"], row["topic"], row["claim_type"])
            ).fetchone()
            connection.execute(
                """
                INSERT INTO publisher_reliability_cells (
                  publisher_key,topic,claim_type,baseline,alpha,beta,
                  learned_reliability,reliability_lower_bound,reliability_upper_bound,
                  confirmed_count,refuted_count,mixed_count,evaluated_count,method,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(publisher_key,topic,claim_type) DO UPDATE SET
                  alpha=excluded.alpha,beta=excluded.beta,
                  learned_reliability=excluded.learned_reliability,
                  reliability_lower_bound=excluded.reliability_lower_bound,
                  reliability_upper_bound=excluded.reliability_upper_bound,
                  confirmed_count=excluded.confirmed_count,
                  refuted_count=excluded.refuted_count,mixed_count=excluded.mixed_count,
                  evaluated_count=excluded.evaluated_count,method=excluded.method,
                  updated_at=excluded.updated_at
                """,
                (row["publisher_key"],row["topic"],row["claim_type"],baseline,
                 alpha,beta,round(learned,4),round(max(0,mean-1.64*deviation),4),
                 round(min(1,mean+1.64*deviation),4),row["confirmed"],row["refuted"],
                 row["mixed"],row["evaluated"],"topic-type-beta-v1",now)
            )
            if previous is None or abs(float(previous[0])-learned) >= .0001:
                updated += 1
            gate = connection.execute(
                "SELECT status FROM intelligence_feature_gates "
                "WHERE feature='topic_reliability'"
            ).fetchone()
            if gate and gate["status"] == "active":
                topic_values = [row["topic"]] + [
                    raw for raw, normalized in TOPIC_ALIASES.items()
                    if normalized == row["topic"]
                ]
                connection.execute(
                    """
                    UPDATE claim_evidence SET source_weight=?
                    WHERE document_version_id IN (
                      SELECT versions.id FROM document_versions versions
                      JOIN documents ON documents.id=versions.document_id
                      WHERE documents.publisher_key=?
                    ) AND claim_id IN (SELECT id FROM claims WHERE topic IN (%s)
                      AND claim_type=?)
                    """ % ",".join("?" for _ in topic_values),
                    (round(learned,4),row["publisher_key"],*topic_values,
                     row["claim_type"])
                )
        return updated

    def _refresh_content_profiles(self, connection, now):
        rows = connection.execute(
            """
            SELECT documents.publisher_key,COUNT(DISTINCT claims.id) samples,
              AVG(claims.claim_type IN ('direct_fact','quantitative_fact')) direct_share,
              AVG(claims.claim_type='attributed_assertion') attributed_share,
              AVG(claims.claim_type='interpretation') interpretation_share,
              AVG(claims.claim_type='causal_claim') causal_share,
              AVG(claims.evidence_role='primary') primary_share,
              AVG(EXISTS(SELECT 1 FROM document_relationships r
                         WHERE (r.left_document_id=documents.id OR r.right_document_id=documents.id)
                           AND r.relationship IN ('copied','syndicated'))) syndicated_share
            FROM documents
            JOIN document_versions versions ON versions.document_id=documents.id
            JOIN claim_evidence evidence ON evidence.document_version_id=versions.id
            JOIN claims ON claims.id=evidence.claim_id
            GROUP BY documents.publisher_key
            """
        ).fetchall()
        for row in rows:
            connection.execute(
                """
                INSERT INTO publisher_content_profiles VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(publisher_key) DO UPDATE SET
                  direct_fact_share=excluded.direct_fact_share,
                  attributed_claim_share=excluded.attributed_claim_share,
                  interpretation_share=excluded.interpretation_share,
                  causal_claim_share=excluded.causal_claim_share,
                  primary_evidence_share=excluded.primary_evidence_share,
                  syndication_share=excluded.syndication_share,
                  sample_count=excluded.sample_count,method=excluded.method,
                  updated_at=excluded.updated_at
                """,
                (row["publisher_key"],row["direct_share"] or 0,
                 row["attributed_share"] or 0,row["interpretation_share"] or 0,
                 row["causal_share"] or 0,row["primary_share"] or 0,
                 row["syndicated_share"] or 0,row["samples"],
                 "content-mix-v1",now)
            )
