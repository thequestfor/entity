"""Resumable, bounded historical claim typing and integrity review."""

import argparse
import json
import re
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv

from agent.intelligence.claim_extraction import (
    EXTRACTION_VERSION,
    HybridClaimExtractor,
    classify_existing_claim
)
from agent.intelligence.config import IntelligenceConfig
from agent.intelligence.store import IntelligenceStore, utc_now


BACKFILL_NAME = "historical-claim-epistemics"
DOCUMENT_BACKFILL_NAME = "historical-prose-claims"
BACKFILL_VERSION = EXTRACTION_VERSION


@dataclass(frozen=True)
class BackfillResult:
    processed: int = 0
    updated: int = 0
    integrity_warnings: int = 0
    completed: bool = False
    situation_ids: tuple = ()


class EpistemicBackfill:
    def __init__(self, store, enabled=True, batch_size=25):
        self.store = store
        self.enabled = bool(enabled)
        self.batch_size = max(1, min(100, int(batch_size)))
        # Historical work is deliberately local/deterministic even when the
        # optional model extractor is enabled for new evidence.
        self.extractor = HybridClaimExtractor(
            model_enabled=False, max_claims=50
        )

    def run_batch(self, refresh=None):
        if not self.enabled:
            return BackfillResult()
        try:
            return self._run_batch(refresh=refresh)
        except Exception as exc:
            self._record_error(exc)
            raise

    def _run_batch(self, refresh=None):
        claim_result = self._run_claim_batch(refresh=refresh)
        if not claim_result.completed:
            return claim_result
        return self._run_document_batch(refresh=refresh)

    def _run_claim_batch(self, refresh=None):
        now = utc_now()
        with self.store._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            state = self._state(connection, now)
            if state["completed"]:
                remaining = connection.execute(
                    "SELECT 1 FROM claims WHERE extraction_version != ? LIMIT 1",
                    (BACKFILL_VERSION,)
                ).fetchone()
                if remaining is None:
                    return BackfillResult(completed=True)
                connection.execute(
                    "UPDATE epistemic_backfill_state SET completed = 0, "
                    "cursor_rowid = 0, completed_at = NULL, updated_at = ? "
                    "WHERE name = ?",
                    (now, BACKFILL_NAME)
                )
                state = connection.execute(
                    "SELECT * FROM epistemic_backfill_state WHERE name = ?",
                    (BACKFILL_NAME,)
                ).fetchone()
            rows = connection.execute(
                """
                SELECT claims.rowid AS claim_rowid, claims.*
                FROM claims
                WHERE claims.rowid > ? AND extraction_version != ?
                ORDER BY claims.rowid ASC
                LIMIT ?
                """,
                (state["cursor_rowid"], BACKFILL_VERSION, self.batch_size)
            ).fetchall()
            if not rows:
                connection.execute(
                    """
                    UPDATE epistemic_backfill_state
                    SET completed = 1, completed_at = ?, updated_at = ?, last_error = ''
                    WHERE name = ?
                    """,
                    (now, now, BACKFILL_NAME)
                )
                return BackfillResult(completed=True)

            situation_ids = set()
            for row in rows:
                candidate = classify_existing_claim(
                    row["predicate"], row["object"], row["topic"]
                )
                connection.execute(
                    """
                    UPDATE claims SET
                      claim_type = ?, verifiability = ?, attribution = ?, topic = ?,
                      attributed_to = ?, endorsement = ?, extraction_confidence = ?,
                      extraction_method = ?, extraction_version = ?, precision = ?,
                      evidence_role = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        candidate.claim_type, candidate.verifiability,
                        candidate.attribution, candidate.topic,
                        candidate.attributed_to, candidate.endorsement,
                        candidate.extraction_confidence,
                        candidate.extraction_method, candidate.extraction_version,
                        candidate.precision, candidate.evidence_role, now, row["id"]
                    )
                )
                situation_ids.add(row["situation_id"])

            warnings = 0
            for situation_id in sorted(situation_ids):
                if refresh is not None:
                    refresh(connection, situation_id)
                warnings += self._review_integrity(connection, situation_id, now)

            last_rowid = rows[-1]["claim_rowid"]
            connection.execute(
                """
                UPDATE epistemic_backfill_state SET
                  cursor_rowid = ?, processed = processed + ?, updated = updated + ?,
                  integrity_warnings = integrity_warnings + ?, updated_at = ?,
                  last_error = ''
                WHERE name = ?
                """,
                (last_rowid, len(rows), len(rows), warnings, now, BACKFILL_NAME)
            )
        return BackfillResult(
            len(rows), len(rows), warnings, False, tuple(sorted(situation_ids))
        )

    def _run_document_batch(self, refresh=None):
        now = utc_now()
        with self.store._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            state = self._document_state(connection, now)
            if state["completed"]:
                remaining = self._pending_document_exists(connection)
                if not remaining:
                    return BackfillResult(completed=True)
                connection.execute(
                    "UPDATE epistemic_backfill_state SET completed = 0, "
                    "cursor_rowid = 0, completed_at = NULL, updated_at = ? "
                    "WHERE name = ?",
                    (now, DOCUMENT_BACKFILL_NAME)
                )
                state = connection.execute(
                    "SELECT * FROM epistemic_backfill_state WHERE name = ?",
                    (DOCUMENT_BACKFILL_NAME,)
                ).fetchone()
            rows = connection.execute(
                """
                SELECT versions.id AS document_version_id,
                       versions.title, versions.summary, versions.content,
                       versions.metadata, versions.published_at,
                       documents.id AS document_id, documents.category,
                       documents.retrieved_at, analysis.situation_id,
                       COALESCE(reputation.learned_credibility,
                                sources.credibility) AS source_credibility
                FROM document_analysis AS analysis
                JOIN document_versions AS versions
                  ON versions.id = analysis.document_version_id
                JOIN documents ON documents.id = analysis.document_id
                JOIN sources ON sources.id = documents.source_id
                LEFT JOIN publisher_reputation AS reputation
                  ON reputation.publisher_key = documents.publisher_key
                LEFT JOIN claim_extraction_attempts AS attempts
                  ON attempts.document_version_id = versions.id
                 AND attempts.method = 'hybrid'
                 AND attempts.version = ?
                WHERE versions.id > ? AND attempts.id IS NULL
                  AND sources.kind NOT IN ('private_mail', 'prediction_market')
                ORDER BY versions.id ASC LIMIT ?
                """,
                (BACKFILL_VERSION, state["cursor_rowid"], self.batch_size)
            ).fetchall()
            if not rows:
                connection.execute(
                    """
                    UPDATE epistemic_backfill_state
                    SET completed = 1, completed_at = ?, updated_at = ?, last_error = ''
                    WHERE name = ?
                    """,
                    (now, now, DOCUMENT_BACKFILL_NAME)
                )
                return BackfillResult(completed=True)

            created = 0
            situation_ids = set()
            for row in rows:
                document = dict(row)
                document["metadata"] = self.store._json_load(
                    document.get("metadata"), {}
                )
                prose = [
                    claim for claim in self.extractor.extract(document)
                    if claim.attribution not in {"source_metadata", "source_report"}
                ]
                for candidate in prose:
                    normalized = _normalize_claim_value(candidate.value)
                    existing = connection.execute(
                        """
                        SELECT id FROM claims
                        WHERE situation_id = ? AND subject = 'situation'
                          AND predicate = ? AND normalized_object = ?
                        """,
                        (row["situation_id"], candidate.predicate, normalized)
                    ).fetchone()
                    if existing:
                        claim_id = existing["id"]
                    else:
                        claim_id = str(uuid4())
                        seen_at = row["published_at"] or row["retrieved_at"]
                        connection.execute(
                            """
                            INSERT INTO claims (
                              id, situation_id, subject, predicate, object,
                              normalized_object, first_seen_at, last_seen_at,
                              created_at, updated_at, claim_type, verifiability,
                              attribution, topic, attributed_to, endorsement,
                              extraction_confidence, extraction_method,
                              extraction_version, precision, evidence_role
                            ) VALUES (
                              ?, ?, 'situation', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                              ?, ?, ?, ?, ?, ?, ?
                            )
                            """,
                            (
                                claim_id, row["situation_id"], candidate.predicate,
                                candidate.value, normalized, seen_at, seen_at, now,
                                now, candidate.claim_type, candidate.verifiability,
                                candidate.attribution, candidate.topic,
                                candidate.attributed_to, candidate.endorsement,
                                candidate.extraction_confidence,
                                candidate.extraction_method,
                                candidate.extraction_version, candidate.precision,
                                candidate.evidence_role
                            )
                        )
                        created += 1
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO claim_evidence (
                          claim_id, document_version_id, stance, source_weight,
                          excerpt, observed_at
                        ) VALUES (?, ?, 'supports', ?, ?, ?)
                        """,
                        (
                            claim_id, row["document_version_id"],
                            max(0.0, min(1.0, row["source_credibility"])),
                            candidate.excerpt[:500],
                            row["published_at"] or row["retrieved_at"]
                        )
                    )
                connection.execute(
                    """
                    INSERT INTO claim_extraction_attempts (
                      document_version_id, method, version, outcome,
                      claims_extracted, created_at
                    ) VALUES (?, 'hybrid', ?, 'success', ?, ?)
                    """,
                    (row["document_version_id"], BACKFILL_VERSION, len(prose), now)
                )
                situation_ids.add(row["situation_id"])

            warnings = 0
            for situation_id in sorted(situation_ids):
                if refresh is not None:
                    refresh(connection, situation_id)
                warnings += self._review_integrity(connection, situation_id, now)
            connection.execute(
                """
                UPDATE epistemic_backfill_state SET
                  cursor_rowid = ?, processed = processed + ?, updated = updated + ?,
                  integrity_warnings = integrity_warnings + ?, updated_at = ?,
                  last_error = '' WHERE name = ?
                """,
                (rows[-1]["document_version_id"], len(rows), created, warnings,
                 now, DOCUMENT_BACKFILL_NAME)
            )
        return BackfillResult(
            len(rows), created, warnings, False, tuple(sorted(situation_ids))
        )

    def _document_state(self, connection, now):
        state = connection.execute(
            "SELECT * FROM epistemic_backfill_state WHERE name = ?",
            (DOCUMENT_BACKFILL_NAME,)
        ).fetchone()
        if state is None:
            connection.execute(
                "INSERT INTO epistemic_backfill_state "
                "(name, version, started_at, updated_at) VALUES (?, ?, ?, ?)",
                (DOCUMENT_BACKFILL_NAME, BACKFILL_VERSION, now, now)
            )
        elif state["version"] != BACKFILL_VERSION:
            connection.execute(
                """
                UPDATE epistemic_backfill_state SET version = ?, cursor_rowid = 0,
                  processed = 0, updated = 0, integrity_warnings = 0,
                  completed = 0, last_error = '', started_at = ?, updated_at = ?,
                  completed_at = NULL WHERE name = ?
                """,
                (BACKFILL_VERSION, now, now, DOCUMENT_BACKFILL_NAME)
            )
        return connection.execute(
            "SELECT * FROM epistemic_backfill_state WHERE name = ?",
            (DOCUMENT_BACKFILL_NAME,)
        ).fetchone()

    def _pending_document_exists(self, connection):
        return connection.execute(
            """
            SELECT 1 FROM document_analysis AS analysis
            LEFT JOIN claim_extraction_attempts AS attempts
              ON attempts.document_version_id = analysis.document_version_id
             AND attempts.method = 'hybrid' AND attempts.version = ?
            WHERE attempts.id IS NULL LIMIT 1
            """,
            (BACKFILL_VERSION,)
        ).fetchone() is not None

    def _state(self, connection, now):
        state = connection.execute(
            "SELECT * FROM epistemic_backfill_state WHERE name = ?",
            (BACKFILL_NAME,)
        ).fetchone()
        if state is None:
            connection.execute(
                """
                INSERT INTO epistemic_backfill_state (
                  name, version, started_at, updated_at
                ) VALUES (?, ?, ?, ?)
                """,
                (BACKFILL_NAME, BACKFILL_VERSION, now, now)
            )
        elif state["version"] != BACKFILL_VERSION:
            connection.execute(
                """
                UPDATE epistemic_backfill_state SET
                  version = ?, cursor_rowid = 0, processed = 0, updated = 0,
                  integrity_warnings = 0, completed = 0, last_error = '',
                  started_at = ?, updated_at = ?, completed_at = NULL
                WHERE name = ?
                """,
                (BACKFILL_VERSION, now, now, BACKFILL_NAME)
            )
        return connection.execute(
            "SELECT * FROM epistemic_backfill_state WHERE name = ?",
            (BACKFILL_NAME,)
        ).fetchone()

    def _review_integrity(self, connection, situation_id, now):
        row = connection.execute(
            """
            SELECT situations.category,
                   MIN(COALESCE(documents.published_at, documents.retrieved_at)) AS earliest,
                   MAX(COALESCE(documents.published_at, documents.retrieved_at)) AS latest,
                   MAX(documents.latitude) - MIN(documents.latitude) AS latitude_span,
                   MAX(documents.longitude) - MIN(documents.longitude) AS longitude_span,
                   COUNT(DISTINCT documents.source_id) AS source_count,
                   COUNT(DISTINCT documents.id) AS document_count
            FROM situations
            JOIN situation_documents ON situation_documents.situation_id = situations.id
            JOIN documents ON documents.id = situation_documents.document_id
            WHERE situations.id = ?
            GROUP BY situations.id
            """,
            (situation_id,)
        ).fetchone()
        if row is None:
            return 0
        flags = []
        if row["latitude_span"] is not None and (
            abs(float(row["latitude_span"])) > 8.0
            or abs(float(row["longitude_span"] or 0.0)) > 12.0
        ):
            flags.append(("wide_geography", "review", {
                "latitude_span": round(float(row["latitude_span"]), 3),
                "longitude_span": round(float(row["longitude_span"] or 0.0), 3)
            }))
        transient = row["category"] not in {
            "economic-indicator", "traditional-news", "software-vulnerability"
        }
        if transient and row["earliest"] and row["latest"]:
            span = connection.execute(
                "SELECT julianday(?) - julianday(?)",
                (row["latest"], row["earliest"])
            ).fetchone()[0]
            if span is not None and float(span) > 21:
                flags.append(("long_evidence_span", "review", {
                    "days": round(float(span), 2),
                    "documents": row["document_count"]
                }))
        contested = connection.execute(
            "SELECT COUNT(*) FROM claims WHERE situation_id = ? AND status = 'contested'",
            (situation_id,)
        ).fetchone()[0]
        if contested:
            flags.append(("incompatible_claims", "review", {
                "contested_claims": contested,
                "sources": row["source_count"]
            }))
        for flag_type, severity, details in flags:
            connection.execute(
                """
                INSERT INTO situation_integrity_flags (
                  situation_id, flag_type, severity, details, method,
                  status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'review', ?, ?)
                ON CONFLICT(situation_id, flag_type, method) DO UPDATE SET
                  severity = excluded.severity, details = excluded.details,
                  updated_at = excluded.updated_at
                """,
                (situation_id, flag_type, severity, self.store._json(details),
                 "epistemic-integrity-v1", now, now)
            )
        return len(flags)

    def _record_error(self, exc):
        try:
            with self.store._connect() as connection:
                connection.execute(
                    "UPDATE epistemic_backfill_state SET last_error = ?, updated_at = ? "
                    "WHERE name IN (?, ?)",
                    (
                        str(exc)[:500], utc_now(), BACKFILL_NAME,
                        DOCUMENT_BACKFILL_NAME
                    )
                )
        except Exception:
            pass


def dry_run(database_path, limit=250):
    source_path = Path(database_path)
    with tempfile.TemporaryDirectory(prefix="entity-epistemic-dry-run-") as temp:
        copy_path = Path(temp) / "intelligence.db"
        with sqlite3.connect(source_path) as source, sqlite3.connect(copy_path) as copy:
            source.backup(copy)
        store = IntelligenceStore(copy_path)
        backfill = EpistemicBackfill(store, batch_size=min(100, max(1, limit)))
        processed = updated = warnings = 0
        while processed < limit:
            result = backfill.run_batch()
            processed += result.processed
            updated += result.updated
            warnings += result.integrity_warnings
            if result.completed or not result.processed:
                break
        return {
            "mode": "dry-run", "version": BACKFILL_VERSION,
            "processed": processed, "updated": updated,
            "integrity_warnings": warnings, "live_database_modified": False
        }


def main():
    parser = argparse.ArgumentParser(
        description="Test historical epistemic backfill on a disposable DB copy."
    )
    parser.add_argument("--limit", type=int, default=250)
    args = parser.parse_args()
    load_dotenv(".env")
    config = IntelligenceConfig.from_env()
    print(json.dumps(dry_run(config.database_path, args.limit), indent=2))


def _normalize_claim_value(value):
    text = re.sub(r"\s+", " ", str(value or "")).strip().lower()
    return re.sub(r"[^a-z0-9.+-]+", "-", text).strip("-") or "unknown"


if __name__ == "__main__":
    main()
