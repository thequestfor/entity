"""Conservative, auditable publisher assessment derived from resolved claims."""

import hashlib
import json
import math

from agent.intelligence.store import utc_now


METHOD = "independent-outcome-assessment-v2"


class PublisherAssessmentEngine:
    """Unify configured priors and independently checkable factual outcomes."""

    def __init__(self, store, prior_strength=8.0, min_positive_outcomes=12,
                 max_adjustment=0.15):
        self.store = store
        self.prior_strength = max(2.0, min(100.0, float(prior_strength)))
        self.min_positive_outcomes = max(3, min(100, int(min_positive_outcomes)))
        self.max_adjustment = max(0.0, min(0.3, float(max_adjustment)))

    def refresh(self):
        now = utc_now()
        changed = 0
        with self.store._connect() as connection:
            publishers = connection.execute(
                """SELECT reputation.publisher_key,reputation.baseline_credibility,
                          profiles.attribution_quality,
                          profiles.revision_discipline,
                          profiles.independence_confidence,
                          profiles.timeliness_score,
                          profiles.framing_signal AS observed_framing,
                          priors.framing_signal AS framing_prior,
                          priors.affiliation,priors.rationale
                   FROM publisher_reputation reputation
                   LEFT JOIN publisher_epistemic_profiles profiles
                     ON profiles.publisher_key=reputation.publisher_key
                   LEFT JOIN publisher_profile_priors priors
                     ON priors.publisher_key=reputation.publisher_key
                   ORDER BY reputation.publisher_key"""
            ).fetchall()
            for publisher in publishers:
                outcome = connection.execute(
                    """SELECT
                         COALESCE(SUM(outcome='confirmed'),0) confirmed,
                         COALESCE(SUM(outcome='refuted'),0) refuted,
                         COALESCE(SUM(outcome='mixed'),0) mixed,
                         COUNT(*) samples,
                         GROUP_CONCAT(id) outcome_ids,
                         COALESCE(SUM(CASE WHEN outcome='confirmed' THEN
                           confidence*outcome_weight ELSE 0 END),0) success_weight,
                         COALESCE(SUM(CASE WHEN outcome='refuted' THEN
                           confidence*outcome_weight ELSE 0 END),0) failure_weight
                       FROM publisher_claim_outcomes
                       WHERE publisher_key=? AND (
                         independent_family_count>0 OR
                         evidence_basis LIKE 'authoritative%'
                       )""",
                    (publisher["publisher_key"],),
                ).fetchone()
                assessment = self._assessment(dict(publisher), dict(outcome), now)
                previous = connection.execute(
                    """SELECT input_hash FROM publisher_assessments
                       WHERE publisher_key=? AND scope_kind='global'
                         AND scope_value=''""",
                    (publisher["publisher_key"],),
                ).fetchone()
                self._store(connection, assessment)
                assessment_changed = bool(
                    not previous
                    or previous["input_hash"] != assessment["input_hash"]
                )
                if assessment_changed:
                    connection.execute(
                        """UPDATE claim_evidence SET source_weight=?
                           WHERE document_version_id IN (
                             SELECT versions.id FROM document_versions versions
                             JOIN documents ON documents.id=versions.document_id
                             WHERE documents.publisher_key=?
                           )""",
                        (assessment["effective"], publisher["publisher_key"]),
                    )
                changed += int(assessment_changed)
                topics = connection.execute(
                    """SELECT topic,
                         COALESCE(SUM(outcome='confirmed'),0) confirmed,
                         COALESCE(SUM(outcome='refuted'),0) refuted,
                         COALESCE(SUM(outcome='mixed'),0) mixed,
                         COUNT(*) samples,
                         GROUP_CONCAT(id) outcome_ids,
                         COALESCE(SUM(CASE WHEN outcome='confirmed' THEN
                           confidence*outcome_weight ELSE 0 END),0) success_weight,
                         COALESCE(SUM(CASE WHEN outcome='refuted' THEN
                           confidence*outcome_weight ELSE 0 END),0) failure_weight
                       FROM publisher_claim_outcomes
                       WHERE publisher_key=? AND topic!='' AND (
                         independent_family_count>0 OR
                         evidence_basis LIKE 'authoritative%')
                       GROUP BY topic""",
                    (publisher["publisher_key"],),
                ).fetchall()
                for topic in topics:
                    scoped = self._assessment(
                        dict(publisher), dict(topic), now,
                        scope_kind="topic", scope_value=str(topic["topic"]),
                    )
                    self._store(connection, scoped)
        return changed

    def _assessment(self, publisher, outcome, now, scope_kind="global",
                    scope_value=""):
        baseline = float(publisher["baseline_credibility"])
        success = float(outcome["success_weight"] or 0)
        failure = float(outcome["failure_weight"] or 0)
        alpha = baseline * self.prior_strength + success
        beta = (1.0 - baseline) * self.prior_strength + failure * 1.5
        total = max(0.0001, alpha + beta)
        estimate = alpha / total
        deviation = math.sqrt(max(
            0.0, alpha * beta / (total * total * (total + 1.0))
        ))
        samples = int(outcome["samples"] or 0)
        refuted = int(outcome["refuted"] or 0)
        mature = samples >= self.min_positive_outcomes
        if not mature and not refuted:
            effective = baseline
            status = "provisional"
        else:
            effective = max(
                baseline - self.max_adjustment,
                min(baseline + self.max_adjustment, estimate),
            )
            status = "mature" if mature else "contradiction-responsive"
        framing_prior = float(publisher.get("framing_prior") or 0)
        observed_framing = float(publisher.get("observed_framing") or 0)
        framing = max(framing_prior, observed_framing)
        raw = {
            "publisher_key": publisher["publisher_key"],
            "scope_kind": scope_kind,
            "scope_value": scope_value,
            "baseline": round(baseline, 4),
            "estimate": round(estimate, 4),
            "effective": round(effective, 4),
            "lower": round(max(0.0, estimate - 1.64 * deviation), 4),
            "upper": round(min(1.0, estimate + 1.64 * deviation), 4),
            "confirmed": int(outcome["confirmed"] or 0),
            "refuted": refuted,
            "mixed": int(outcome["mixed"] or 0),
            "samples": samples,
            "outcome_ids": [
                int(value) for value in str(outcome.get("outcome_ids") or "").split(",")
                if value.isdigit()
            ],
            "attribution": round(float(publisher.get("attribution_quality") or .5), 4),
            "revision": round(float(publisher.get("revision_discipline") or .5), 4),
            "independence": round(float(publisher.get("independence_confidence") or .5), 4),
            "timeliness": round(float(publisher.get("timeliness_score") or .5), 4),
            "framing_prior": round(framing_prior, 4),
            "observed_framing": round(observed_framing, 4),
            "framing": round(framing, 4),
            "affiliation": str(publisher.get("affiliation") or "")[:120],
            "rationale": str(publisher.get("rationale") or "")[:500],
            "maturity": status,
        }
        fingerprint = hashlib.sha256(
            json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return {**raw, "input_hash": fingerprint, "updated_at": now}

    def _store(self, connection, item):
        values = (
            item["publisher_key"], item["scope_kind"], item["scope_value"], item["baseline"],
            item["estimate"], item["effective"], item["lower"], item["upper"],
            item["confirmed"], item["refuted"], item["mixed"], item["samples"],
            item["attribution"], item["revision"], item["independence"],
            item["timeliness"],
            item["framing_prior"], item["observed_framing"], item["framing"],
            item["affiliation"], item["rationale"], item["maturity"], METHOD,
            item["input_hash"], item["updated_at"],
        )
        connection.execute(
            """INSERT INTO publisher_assessments (
                 publisher_key,scope_kind,scope_value,baseline_credibility,
                 evidence_estimate,effective_credibility,reliability_lower_bound,
                 reliability_upper_bound,confirmed_count,refuted_count,mixed_count,
                 factual_samples,attribution_quality,revision_discipline,
                 independence_confidence,timeliness_score,framing_prior,observed_framing,
                 framing_signal,affiliation,rationale,maturity_status,method,
                 input_hash,updated_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(publisher_key,scope_kind,scope_value) DO UPDATE SET
                 baseline_credibility=excluded.baseline_credibility,
                 evidence_estimate=excluded.evidence_estimate,
                 effective_credibility=excluded.effective_credibility,
                 reliability_lower_bound=excluded.reliability_lower_bound,
                 reliability_upper_bound=excluded.reliability_upper_bound,
                 confirmed_count=excluded.confirmed_count,
                 refuted_count=excluded.refuted_count,mixed_count=excluded.mixed_count,
                 factual_samples=excluded.factual_samples,
                 attribution_quality=excluded.attribution_quality,
                 revision_discipline=excluded.revision_discipline,
                 independence_confidence=excluded.independence_confidence,
                 timeliness_score=excluded.timeliness_score,
                 framing_prior=excluded.framing_prior,
                 observed_framing=excluded.observed_framing,
                 framing_signal=excluded.framing_signal,
                 affiliation=excluded.affiliation,rationale=excluded.rationale,
                 maturity_status=excluded.maturity_status,method=excluded.method,
                 input_hash=excluded.input_hash,updated_at=excluded.updated_at""",
            values,
        )
        connection.execute(
            """INSERT OR IGNORE INTO publisher_assessment_history (
                 publisher_key,scope_kind,scope_value,baseline_credibility,
                 evidence_estimate,effective_credibility,reliability_lower_bound,
                 reliability_upper_bound,confirmed_count,refuted_count,mixed_count,
                 factual_samples,framing_signal,maturity_status,method,input_hash,
                 reason,created_at,attribution_quality,revision_discipline,
                 independence_confidence,timeliness_score,observed_framing
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                item["publisher_key"], item["scope_kind"], item["scope_value"], item["baseline"],
                item["estimate"], item["effective"], item["lower"], item["upper"],
                item["confirmed"], item["refuted"], item["mixed"], item["samples"],
                item["framing"], item["maturity"], METHOD, item["input_hash"],
                "Independent outcomes changed the auditable assessment input.",
                item["updated_at"], item["attribution"], item["revision"],
                item["independence"], item["timeliness"], item["observed_framing"],
            ),
        )
        for dimension, value in (
            ("factual_accuracy", item["estimate"]),
            ("attribution_quality", item["attribution"]),
            ("revision_discipline", item["revision"]),
            ("independence", item["independence"]),
            ("timeliness", item["timeliness"]),
            ("framing", item["framing"]),
        ):
            dimension_hash = hashlib.sha256(
                f'{item["input_hash"]}:{dimension}:{value}'.encode()
            ).hexdigest()
            connection.execute(
                """INSERT OR IGNORE INTO publisher_dimension_observations (
                     publisher_key,dimension,scope_kind,scope_value,value,
                     sample_count,evidence_basis,evidence_ids,method,input_hash,
                     evidence_cutoff_at,created_at
                   ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (item["publisher_key"], dimension, item["scope_kind"],
                 item["scope_value"], value, item["samples"],
                 "independent resolved outcomes and versioned content metrics",
                 json.dumps(item["outcome_ids"], separators=(",", ":")),
                 METHOD, dimension_hash, item["updated_at"],
                 item["updated_at"]),
            )
