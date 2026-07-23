import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from agent.intelligence.store import utc_now


@dataclass(frozen=True)
class ReputationResult:
    outcomes_recorded: int = 0
    publishers_updated: int = 0


class ReputationEngine:
    """Conservatively calibrate publishers from delayed external outcomes."""

    def __init__(
        self,
        store,
        enabled=True,
        maturity_hours=6,
        max_adjustment=0.15,
        confirmation_floor=0.75
    ):
        self.store = store
        self.enabled = bool(enabled)
        self.maturity_hours = max(0.0, float(maturity_hours))
        self.max_adjustment = max(0.0, min(0.3, float(max_adjustment)))
        self.confirmation_floor = max(0.5, min(1.0, float(confirmation_floor)))

    def evaluate(self):
        if not self.enabled:
            return ReputationResult()
        cutoff = (
            datetime.now(UTC) - timedelta(hours=self.maturity_hours)
        ).isoformat(timespec="seconds").replace("+00:00", "Z")
        recorded = 0
        with self.store._connect() as connection:
            # Every public publisher gets a visible, auditable trust profile
            # immediately. Its score remains the configured baseline until an
            # independently checkable outcome becomes available.
            publishers = connection.execute(
                """
                SELECT documents.*, sources.credibility AS baseline_credibility
                FROM documents
                JOIN sources ON sources.id = documents.source_id
                WHERE sources.kind NOT IN ('private_mail', 'prediction_market')
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
                WHERE sources.kind NOT IN ('private_mail', 'prediction_market')
                  AND publisher_outcomes.document_id IS NULL
                  AND COALESCE(documents.published_at,
                               documents.retrieved_at) <= ?
                ORDER BY COALESCE(documents.published_at,
                                  documents.retrieved_at)
                LIMIT 1000
                """,
                (cutoff,)
            ).fetchall()
            for row in candidates:
                document = dict(row)
                outcome = self._outcome(connection, document)
                if outcome is None:
                    continue
                name, reason, corroborators = outcome
                connection.execute(
                    """
                    INSERT INTO publisher_outcomes (
                        document_id, publisher_key, outcome, reason,
                        corroborating_publishers, evaluated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document["id"], document["publisher_key"], name,
                        reason, json.dumps(sorted(corroborators)), utc_now()
                    )
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
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(publisher_key) DO UPDATE SET
                publisher_label = excluded.publisher_label,
                updated_at = excluded.updated_at
            """,
            (
                document["publisher_key"], document["publisher_label"],
                document["source_id"], baseline, baseline, now, now
            )
        )

    def _outcome(self, connection, document):
        observed = document["published_at"] or document["retrieved_at"]
        corroborators = connection.execute(
            """
            SELECT DISTINCT other.publisher_key,
                   COALESCE(other.published_at, other.retrieved_at) AS observed_at
            FROM situation_documents AS own_link
            JOIN situation_documents AS other_link
              ON other_link.situation_id = own_link.situation_id
            JOIN documents AS other ON other.id = other_link.document_id
            JOIN sources AS other_source ON other_source.id = other.source_id
            WHERE own_link.document_id = ?
              AND other.id != ?
              AND other.publisher_key != ?
              AND other.status = 'active'
              AND other_source.kind NOT IN ('private_mail', 'prediction_market')
              AND other_source.credibility >= ?
              AND COALESCE(other.published_at, other.retrieved_at) > ?
            """,
            (
                document["id"], document["id"], document["publisher_key"],
                self.confirmation_floor, observed
            )
        ).fetchall()
        publishers = {row["publisher_key"] for row in corroborators}
        if publishers:
            return (
                "confirmed",
                "Later independent high-baseline evidence joined the situation.",
                publishers
            )
        if self._robustly_contradicted(connection, document):
            return (
                "contradicted",
                "A supported claim was superseded by independently supported evidence.",
                set()
            )
        if document["status"] == "deleted":
            return (
                "deleted_unverified",
                "The captured post was deleted without later high-baseline corroboration.",
                set()
            )
        return None

    def _robustly_contradicted(self, connection, document):
        row = connection.execute(
            """
            SELECT 1
            FROM document_versions AS own_version
            JOIN claim_evidence AS own_evidence
              ON own_evidence.document_version_id = own_version.id
            JOIN claims AS own_claim ON own_claim.id = own_evidence.claim_id
            JOIN claims AS alternative
              ON alternative.situation_id = own_claim.situation_id
             AND alternative.predicate = own_claim.predicate
             AND alternative.normalized_object != own_claim.normalized_object
             AND alternative.status = 'active'
            JOIN claim_evidence AS alternative_evidence
              ON alternative_evidence.claim_id = alternative.id
            JOIN document_versions AS alternative_version
              ON alternative_version.id = alternative_evidence.document_version_id
            JOIN documents AS alternative_document
              ON alternative_document.id = alternative_version.document_id
            JOIN sources AS alternative_source
              ON alternative_source.id = alternative_document.source_id
            WHERE own_version.document_id = ?
              AND own_claim.status = 'superseded'
              AND alternative_document.publisher_key != ?
              AND alternative_source.credibility >= ?
            LIMIT 1
            """,
            (
                document["id"], document["publisher_key"],
                self.confirmation_floor
            )
        ).fetchone()
        return row is not None

    def _recalculate(self, connection):
        rows = connection.execute(
            """
            SELECT reputation.*,
                   SUM(outcomes.outcome = 'confirmed') AS confirmed,
                   SUM(outcomes.outcome = 'contradicted') AS contradicted,
                   SUM(outcomes.outcome = 'deleted_unverified') AS deleted_count,
                   COUNT(outcomes.document_id) AS evaluated
            FROM publisher_reputation AS reputation
            LEFT JOIN publisher_outcomes AS outcomes
              ON outcomes.publisher_key = reputation.publisher_key
            GROUP BY reputation.publisher_key
            """
        ).fetchall()
        updated = 0
        for row in rows:
            baseline = row["baseline_credibility"]
            confirmed = int(row["confirmed"] or 0)
            contradicted = int(row["contradicted"] or 0)
            deleted = int(row["deleted_count"] or 0)
            evaluated = int(row["evaluated"] or 0)
            prior_strength = 20.0
            alpha = baseline * prior_strength + confirmed
            beta = (
                (1.0 - baseline) * prior_strength
                + contradicted * 2.0 + deleted * 0.5
            )
            raw = alpha / max(0.0001, alpha + beta)
            learned = baseline if not evaluated else max(
                baseline - self.max_adjustment,
                min(baseline + self.max_adjustment, raw)
            )
            learned = round(max(0.0, min(1.0, learned)), 4)
            counts_changed = any((
                confirmed != row["confirmed_count"],
                contradicted != row["contradicted_count"],
                deleted != row["deleted_unverified_count"],
                evaluated != row["evaluated_count"]
            ))
            score_changed = abs(learned - row["learned_credibility"]) >= 0.0001
            if not (counts_changed or score_changed):
                continue
            now = utc_now()
            connection.execute(
                """
                UPDATE publisher_reputation
                SET learned_credibility = ?, confirmed_count = ?,
                    contradicted_count = ?, deleted_unverified_count = ?,
                    early_confirmation_count = ?, evaluated_count = ?,
                    last_evaluated_at = ?, updated_at = ?
                WHERE publisher_key = ?
                """,
                (
                    learned, confirmed, contradicted, deleted, confirmed,
                    evaluated, now, now, row["publisher_key"]
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
                    row["publisher_key"], row["learned_credibility"], learned,
                    confirmed, contradicted, deleted, confirmed,
                    "Delayed outcome evidence recalibration", now
                )
            )
            updated += 1
        return updated
