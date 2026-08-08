import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from agent.intelligence.store import utc_now


@dataclass(frozen=True)
class ReputationResult:
    outcomes_recorded: int = 0
    publishers_updated: int = 0


class ReputationEngine:
    """Learn publisher reliability from delayed, independent outcomes."""

    method = "delayed-corroboration-v2"

    def __init__(
        self,
        store,
        enabled=True,
        maturity_hours=6,
        max_adjustment=0.15,
        confirmation_floor=0.75,
        prior_strength=8.0,
        min_evaluated_outcomes=12
    ):
        self.store = store
        self.enabled = bool(enabled)
        self.maturity_hours = max(0.0, float(maturity_hours))
        self.max_adjustment = max(0.0, min(0.3, float(max_adjustment)))
        self.confirmation_floor = max(0.5, min(1.0, float(confirmation_floor)))
        self.prior_strength = max(2.0, min(100.0, float(prior_strength)))
        self.min_evaluated_outcomes = max(
            3, min(100, int(min_evaluated_outcomes))
        )

    def evaluate(self):
        if not self.enabled:
            return ReputationResult()
        now = datetime.now(UTC)
        now_text = _timestamp(now)
        cutoff = _timestamp(now - timedelta(hours=self.maturity_hours))
        recorded = 0
        with self.store._connect() as connection:
            publishers = connection.execute(
                """
                SELECT documents.publisher_key,
                       MAX(documents.publisher_label) AS publisher_label,
                       MAX(documents.source_id) AS source_id,
                       MAX(sources.credibility) AS baseline_credibility
                FROM documents
                JOIN sources ON sources.id = documents.source_id
                WHERE sources.kind NOT IN ('private_mail', 'prediction_market')
                GROUP BY documents.publisher_key
                """
            ).fetchall()
            for row in publishers:
                self._ensure_publisher(connection, dict(row))

            candidates = connection.execute(
                """
                SELECT documents.*, sources.credibility AS baseline_credibility
                FROM documents
                JOIN sources ON sources.id = documents.source_id
                LEFT JOIN publisher_outcomes
                  ON publisher_outcomes.document_id = documents.id
                LEFT JOIN publisher_verification_attempts AS attempts
                  ON attempts.document_id = documents.id
                WHERE sources.kind NOT IN ('private_mail', 'prediction_market')
                  AND publisher_outcomes.document_id IS NULL
                  AND COALESCE(documents.published_at,
                               documents.retrieved_at) <= ?
                  AND (attempts.next_attempt_at IS NULL
                       OR attempts.next_attempt_at <= ?)
                ORDER BY COALESCE(attempts.next_attempt_at,
                                  documents.published_at,
                                  documents.retrieved_at)
                LIMIT 1000
                """,
                (cutoff, now_text)
            ).fetchall()
            for row in candidates:
                document = dict(row)
                outcome = self._outcome(connection, document)
                if outcome is None:
                    self._schedule_retry(connection, document["id"], now)
                    continue
                connection.execute(
                    """
                    INSERT INTO publisher_outcomes (
                        document_id, publisher_key, outcome, reason,
                        corroborating_publishers, evaluated_at,
                        evidence_document_ids, outcome_confidence,
                        was_early, verification_method
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document["id"], document["publisher_key"],
                        outcome["name"], outcome["reason"],
                        json.dumps(sorted(outcome["publishers"])), now_text,
                        json.dumps(sorted(outcome["document_ids"])),
                        outcome["confidence"], int(outcome["was_early"]),
                        self.method
                    )
                )
                connection.execute(
                    "DELETE FROM publisher_verification_attempts WHERE document_id = ?",
                    (document["id"],)
                )
                recorded += 1
            updated = self._recalculate(connection)
        return ReputationResult(recorded, updated)

    def _ensure_publisher(self, connection, document):
        now = utc_now()
        baseline = max(0.0, min(1.0, document["baseline_credibility"]))
        connection.execute(
            """
            INSERT INTO publisher_reputation (
                publisher_key, publisher_label, source_id,
                baseline_credibility, learned_credibility,
                reliability_lower_bound, reliability_upper_bound,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(publisher_key) DO UPDATE SET
                publisher_label = excluded.publisher_label,
                updated_at = excluded.updated_at
            """,
            (
                document["publisher_key"], document["publisher_label"],
                document["source_id"], baseline, baseline,
                max(0.0, baseline - 0.25), min(1.0, baseline + 0.25),
                now, now
            )
        )

    def _outcome(self, connection, document):
        contradicted_by = self._robust_contradictions(connection, document)
        if contradicted_by:
            return {
                "name": "contradicted",
                "reason": (
                    "A specific supported claim was superseded by later, "
                    "independently supported evidence."
                ),
                "publishers": {item["publisher_key"] for item in contradicted_by},
                "document_ids": {item["id"] for item in contradicted_by},
                "confidence": min(0.98, max(
                    item["credibility"] for item in contradicted_by
                )),
                "was_early": False
            }

        corroborators = self._corroborators(connection, document)
        publishers = {item["publisher_key"] for item in corroborators}
        authoritative = [
            item for item in corroborators if item["credibility"] >= 0.95
        ]
        if len(publishers) >= 2 or authoritative:
            observed = _parse_time(
                document["published_at"] or document["retrieved_at"]
            )
            first_confirmation = min(
                _parse_time(item["observed_at"]) for item in corroborators
            )
            was_early = (first_confirmation - observed).total_seconds() >= 300
            confidence = min(
                0.98,
                0.62
                + 0.10 * min(3, len(publishers))
                + 0.12 * int(bool(authoritative))
            )
            return {
                "name": "confirmed",
                "reason": (
                    "Later independent publishers reported materially matching "
                    "facts in the same situation."
                ),
                "publishers": publishers,
                "document_ids": {item["id"] for item in corroborators},
                "confidence": confidence,
                "was_early": was_early
            }

        if document["status"] == "deleted":
            return {
                "name": "deleted_unverified",
                "reason": (
                    "The captured post was deleted without later independent "
                    "corroboration. Deletion is weak negative evidence, not proof "
                    "that the report was false."
                ),
                "publishers": set(),
                "document_ids": set(),
                "confidence": 0.35,
                "was_early": False
            }
        return None

    def _corroborators(self, connection, document):
        observed = document["published_at"] or document["retrieved_at"]
        rows = connection.execute(
            """
            SELECT DISTINCT other.id, other.publisher_key, other.title,
                   other.summary,
                   COALESCE(other.published_at, other.retrieved_at) AS observed_at,
                   COALESCE(other_reputation.learned_credibility,
                            other_source.credibility) AS credibility,
                   EXISTS (
                       SELECT 1
                       FROM document_versions AS own_version
                       JOIN claim_evidence AS own_evidence
                         ON own_evidence.document_version_id = own_version.id
                       JOIN claims AS shared_claim
                         ON shared_claim.id = own_evidence.claim_id
                       JOIN claim_evidence AS other_evidence
                         ON other_evidence.claim_id = shared_claim.id
                       JOIN document_versions AS other_version
                         ON other_version.id = other_evidence.document_version_id
                       WHERE own_version.document_id = ?
                         AND other_version.document_id = other.id
                         AND shared_claim.predicate NOT IN (
                             'event.reported', 'event.category'
                         )
                   ) AS specific_claim_match
            FROM situation_documents AS own_link
            JOIN situation_documents AS other_link
              ON other_link.situation_id = own_link.situation_id
            JOIN documents AS other ON other.id = other_link.document_id
            JOIN sources AS other_source ON other_source.id = other.source_id
            LEFT JOIN publisher_reputation AS other_reputation
              ON other_reputation.publisher_key = other.publisher_key
            WHERE own_link.document_id = ?
              AND other.id != ?
              AND other.publisher_key != ?
              AND other.status = 'active'
              AND other_source.kind NOT IN ('private_mail', 'prediction_market')
              AND COALESCE(json_extract(other.metadata, '$.forwarded'), 0) = 0
              AND COALESCE(other.published_at, other.retrieved_at) > ?
            """,
            (
                document["id"], document["id"], document["id"],
                document["publisher_key"], observed
            )
        ).fetchall()
        original_text = f"{document['title']} {document['summary']}"
        corroborators = []
        for row in rows:
            item = dict(row)
            if float(item["credibility"] or 0.0) < self.confirmation_floor:
                continue
            if (
                not item["specific_claim_match"]
                and _text_similarity(
                    original_text, f"{item['title']} {item['summary']}"
                ) < 0.42
            ):
                continue
            item["credibility"] = float(item["credibility"])
            corroborators.append(item)
        return corroborators

    def _robust_contradictions(self, connection, document):
        rows = connection.execute(
            """
            SELECT DISTINCT alternative_document.id,
                   alternative_document.publisher_key,
                   COALESCE(alternative_reputation.learned_credibility,
                            alternative_source.credibility) AS credibility
            FROM document_versions AS own_version
            JOIN claim_evidence AS own_evidence
              ON own_evidence.document_version_id = own_version.id
            JOIN claims AS own_claim ON own_claim.id = own_evidence.claim_id
            JOIN claims AS alternative
              ON alternative.situation_id = own_claim.situation_id
             AND alternative.predicate = own_claim.predicate
             AND alternative.normalized_object != own_claim.normalized_object
             AND alternative.status IN ('active', 'contested')
            JOIN claim_evidence AS alternative_evidence
              ON alternative_evidence.claim_id = alternative.id
            JOIN document_versions AS alternative_version
              ON alternative_version.id = alternative_evidence.document_version_id
            JOIN documents AS alternative_document
              ON alternative_document.id = alternative_version.document_id
            JOIN sources AS alternative_source
              ON alternative_source.id = alternative_document.source_id
            LEFT JOIN publisher_reputation AS alternative_reputation
              ON alternative_reputation.publisher_key = alternative_document.publisher_key
            WHERE own_version.document_id = ?
              AND own_claim.status IN ('superseded', 'contested')
              AND own_claim.predicate NOT IN ('event.reported', 'event.category')
              AND alternative_document.publisher_key != ?
              AND alternative_evidence.observed_at > own_evidence.observed_at
            """,
            (document["id"], document["publisher_key"])
        ).fetchall()
        return [
            {**dict(row), "credibility": float(row["credibility"] or 0.0)}
            for row in rows
            if float(row["credibility"] or 0.0) >= self.confirmation_floor
        ]

    def _schedule_retry(self, connection, document_id, now):
        row = connection.execute(
            "SELECT attempt_count FROM publisher_verification_attempts WHERE document_id = ?",
            (document_id,)
        ).fetchone()
        attempts = int(row["attempt_count"] or 0) + 1 if row else 1
        delay_hours = min(24 * 7, 6 * (2 ** min(attempts - 1, 5)))
        connection.execute(
            """
            INSERT INTO publisher_verification_attempts (
                document_id, attempt_count, last_attempt_at,
                next_attempt_at, last_reason
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(document_id) DO UPDATE SET
                attempt_count = excluded.attempt_count,
                last_attempt_at = excluded.last_attempt_at,
                next_attempt_at = excluded.next_attempt_at,
                last_reason = excluded.last_reason
            """,
            (
                document_id, attempts, _timestamp(now),
                _timestamp(now + timedelta(hours=delay_hours)),
                "No independently checkable outcome yet."
            )
        )

    def _recalculate(self, connection):
        reputations = connection.execute(
            "SELECT * FROM publisher_reputation"
        ).fetchall()
        updated = 0
        for row in reputations:
            outcomes = connection.execute(
                """
                SELECT outcome, outcome_confidence, was_early
                FROM publisher_outcomes WHERE publisher_key = ?
                """,
                (row["publisher_key"],)
            ).fetchall()
            confirmed = sum(item["outcome"] == "confirmed" for item in outcomes)
            contradicted = sum(
                item["outcome"] == "contradicted" for item in outcomes
            )
            deleted = sum(
                item["outcome"] == "deleted_unverified" for item in outcomes
            )
            early = sum(
                item["outcome"] == "confirmed" and bool(item["was_early"])
                for item in outcomes
            )
            evaluated = len(outcomes)
            if not evaluated:
                continue
            success_weight = sum(
                float(item["outcome_confidence"])
                for item in outcomes if item["outcome"] == "confirmed"
            )
            failure_weight = sum(
                float(item["outcome_confidence"])
                * (1.75 if item["outcome"] == "contradicted" else 0.25)
                for item in outcomes if item["outcome"] != "confirmed"
            )
            baseline = float(row["baseline_credibility"])
            alpha = baseline * self.prior_strength + success_weight
            beta = (
                (1.0 - baseline) * self.prior_strength + failure_weight
            )
            total = max(0.0001, alpha + beta)
            target = alpha / total
            deviation = math.sqrt(
                max(0.0, alpha * beta / (total * total * (total + 1.0)))
            )
            # Corroborated facts are not evidence of neutral framing or broad
            # editorial reliability. Positive matches leave a publisher at its
            # configured baseline until its outcome record is mature. Specific
            # contradictions still lower its weight immediately.
            maturity_locked = (
                evaluated < self.min_evaluated_outcomes
                and not (contradicted or deleted)
            )
            if maturity_locked:
                target = baseline
                lower = round(max(0.0, baseline - 0.25), 4)
                upper = round(min(1.0, baseline + 0.25), 4)
            else:
                lower = round(max(0.0, target - 1.64 * deviation), 4)
                upper = round(min(1.0, target + 1.64 * deviation), 4)
            counts_changed = any((
                confirmed != row["confirmed_count"],
                contradicted != row["contradicted_count"],
                deleted != row["deleted_unverified_count"],
                early != row["early_confirmation_count"],
                evaluated != row["evaluated_count"]
            ))
            previous = float(row["learned_credibility"])
            if maturity_locked:
                learned = round(baseline, 4)
            elif counts_changed:
                new_outcomes = max(1, evaluated - int(row["evaluated_count"]))
                allowed_change = self.max_adjustment * math.sqrt(new_outcomes)
                change = max(
                    -allowed_change,
                    min(allowed_change, target - previous)
                )
                learned = round(max(0.0, min(1.0, previous + change)), 4)
            else:
                learned = previous
            bounds_changed = any((
                abs(lower - float(row["reliability_lower_bound"])) >= 0.0001,
                abs(upper - float(row["reliability_upper_bound"])) >= 0.0001
            ))
            if not (counts_changed or bounds_changed):
                continue
            now = utc_now()
            connection.execute(
                """
                UPDATE publisher_reputation
                SET learned_credibility = ?, reliability_lower_bound = ?,
                    reliability_upper_bound = ?, confirmed_count = ?,
                    contradicted_count = ?, deleted_unverified_count = ?,
                    early_confirmation_count = ?, evaluated_count = ?,
                    last_evaluated_at = ?, updated_at = ?
                WHERE publisher_key = ?
                """,
                (
                    learned, lower, upper, confirmed, contradicted, deleted,
                    early, evaluated, now, now, row["publisher_key"]
                )
            )
            connection.execute(
                """
                INSERT INTO publisher_reputation_history (
                    publisher_key, previous_credibility, learned_credibility,
                    confirmed_count, contradicted_count,
                    deleted_unverified_count, early_confirmation_count,
                    reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["publisher_key"], previous, learned, confirmed,
                    contradicted, deleted, early,
                    (
                        "Baseline retained pending sufficient independent "
                        "outcomes"
                        if maturity_locked else
                        "Independent delayed-outcome Bayesian recalibration"
                    ), now
                )
            )
            self._reweight_evidence(connection, row["publisher_key"], learned)
            updated += 1
        return updated

    def _reweight_evidence(self, connection, publisher_key, learned):
        connection.execute(
            """
            UPDATE claim_evidence SET source_weight = ?
            WHERE document_version_id IN (
                SELECT document_versions.id
                FROM document_versions
                JOIN documents ON documents.id = document_versions.document_id
                WHERE documents.publisher_key = ?
            )
            """,
            (learned, publisher_key)
        )
        connection.execute(
            """
            UPDATE situations SET updated_at = ?
            WHERE id IN (
                SELECT DISTINCT situation_documents.situation_id
                FROM situation_documents
                JOIN documents ON documents.id = situation_documents.document_id
                WHERE documents.publisher_key = ?
            )
            """,
            (utc_now(), publisher_key)
        )


def _timestamp(value):
    return value.astimezone(UTC).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")


def _parse_time(value):
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)


def _text_similarity(left, right):
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / min(
        len(left_tokens), len(right_tokens)
    )


def _tokens(value):
    stop = {
        "about", "after", "again", "against", "from", "have", "into",
        "more", "over", "said", "that", "their", "there", "they", "this",
        "with", "will", "would"
    }
    return {
        token for token in re.findall(r"[a-z0-9]+", str(value).lower())
        if len(token) >= 4 and token not in stop
    }
