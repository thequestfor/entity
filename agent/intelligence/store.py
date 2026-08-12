import hashlib
import json
import re
import sqlite3
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

from agent.intelligence.models import IngestResult, SourceItem


DEFAULT_DB = Path("agent/world_intelligence.db")
MIGRATIONS = Path(__file__).with_name("migrations")
TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "source"
}
VOLATILE_METADATA_KEYS = {
    "author_public_metrics",
    "forwards",
    "liquidity",
    "post_public_metrics",
    "views",
    "volume",
    "volume_24h"
}


def utc_now():
    return datetime.now(UTC).isoformat(timespec="seconds").replace(
        "+00:00",
        "Z"
    )


class _ClosingConnection(sqlite3.Connection):
    """Commit or roll back, then always release the database descriptor."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class IntelligenceStore:
    def __init__(self, path=DEFAULT_DB, migrations=MIGRATIONS, clock=None,
                 document_id_factory=None):
        self.path = Path(path)
        self.migrations = Path(migrations)
        self.clock = clock or utc_now
        self.document_id_factory = document_id_factory
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def _connect(self):
        connection = sqlite3.connect(
            self.path, timeout=30, factory=_ClosingConnection
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _migrate(self):
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at TEXT NOT NULL
                )
                """
            )
            applied = {
                row["version"]
                for row in connection.execute(
                    "SELECT version FROM schema_migrations"
                )
            }

        for migration in sorted(self.migrations.glob("[0-9][0-9][0-9]_*.sql")):
            version = int(migration.name.split("_", 1)[0])

            if version in applied:
                continue

            script = migration.read_text(encoding="utf-8")
            name = migration.name.replace("'", "''")
            applied_at = utc_now().replace("'", "''")

            with self._connect() as connection:
                connection.executescript(
                    "BEGIN IMMEDIATE;\n"
                    + script
                    + "\n"
                    + (
                        "INSERT INTO schema_migrations "
                        "(version, name, applied_at) VALUES "
                        f"({version}, '{name}', '{applied_at}');\n"
                    )
                    + "COMMIT;"
                )

    def register_source(
        self,
        source_id,
        name,
        kind,
        base_url="",
        credibility=0.5,
        enabled=True,
        poll_seconds=900
    ):
        now = utc_now()

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sources (
                    id, name, kind, base_url, credibility, enabled,
                    poll_seconds, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    kind = excluded.kind,
                    base_url = excluded.base_url,
                    credibility = excluded.credibility,
                    enabled = excluded.enabled,
                    poll_seconds = excluded.poll_seconds,
                    updated_at = excluded.updated_at
                """,
                (
                    source_id,
                    name,
                    kind,
                    base_url,
                    max(0.0, min(1.0, float(credibility))),
                    1 if enabled else 0,
                    max(1, int(poll_seconds)),
                    now,
                    now
                )
            )
            connection.execute(
                """
                INSERT INTO source_cursors (source_id, cursor, updated_at)
                VALUES (?, '{}', ?)
                ON CONFLICT(source_id) DO NOTHING
                """,
                (source_id, now)
            )

    def source_cursor(self, source_id):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT cursor FROM source_cursors WHERE source_id = ?",
                (source_id,)
            ).fetchone()

        if not row:
            return {}

        return self._json_load(row["cursor"], {})

    def register_source_policy(self, source_id, policy):
        now = utc_now()
        snapshot = policy.snapshot()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO source_policies
                   (source_id,access_class,authority_class,evidence_role,
                    license_name,license_url,attribution,usage_scope,
                    credentials_required,geographic_coverage,expected_latency,
                    independence_family,allowed_hosts,caveats,retention_days,
                    policy_version,reviewed_at,created_at,updated_at,
                    article_acquisition_mode,article_hosts,article_max_bytes,
                    article_requests_per_cycle,article_excerpt_display)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(source_id) DO UPDATE SET
                   access_class=excluded.access_class,
                   authority_class=excluded.authority_class,
                   evidence_role=excluded.evidence_role,
                   license_name=excluded.license_name,
                   license_url=excluded.license_url,
                   attribution=excluded.attribution,usage_scope=excluded.usage_scope,
                   credentials_required=excluded.credentials_required,
                   geographic_coverage=excluded.geographic_coverage,
                   expected_latency=excluded.expected_latency,
                   independence_family=excluded.independence_family,
                   allowed_hosts=excluded.allowed_hosts,caveats=excluded.caveats,
                   retention_days=excluded.retention_days,
                   policy_version=excluded.policy_version,
                   reviewed_at=excluded.reviewed_at,updated_at=excluded.updated_at,
                   article_acquisition_mode=excluded.article_acquisition_mode,
                   article_hosts=excluded.article_hosts,
                   article_max_bytes=excluded.article_max_bytes,
                   article_requests_per_cycle=excluded.article_requests_per_cycle,
                   article_excerpt_display=excluded.article_excerpt_display""",
                (source_id,snapshot["access_class"],snapshot["authority_class"],
                 snapshot["evidence_role"],snapshot["license_name"],
                 snapshot["license_url"],snapshot["attribution"],
                 snapshot["usage_scope"],int(snapshot["credentials_required"]),
                 snapshot["geographic_coverage"],snapshot["expected_latency"],
                 snapshot["independence_family"],self._json(snapshot["allowed_hosts"]),
                 self._json(snapshot["caveats"]),snapshot["retention_days"],
                 snapshot["policy_version"],snapshot["reviewed_at"],now,now)
                 + (snapshot["article_acquisition_mode"],
                    self._json(snapshot["article_hosts"]),
                    int(snapshot["article_max_bytes"]),
                    int(snapshot["article_requests_per_cycle"]),
                    int(snapshot["article_excerpt_display"]))
            )
            connection.execute(
                """INSERT INTO source_contract_audits
                   (source_id,outcome,violations,contract_snapshot,checked_at)
                   VALUES (?,'valid','[]',?,?)""",
                (source_id,self._json(snapshot),now)
            )

    def list_source_policies(self):
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT policies.*,sources.name,sources.kind,sources.enabled,
                          sources.last_success_at,sources.last_error
                   FROM source_policies policies
                   JOIN sources ON sources.id=policies.source_id
                   ORDER BY sources.enabled DESC,sources.name"""
            ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["allowed_hosts"] = self._json_load(item.get("allowed_hosts"), [])
            item["article_hosts"] = self._json_load(item.get("article_hosts"), [])
            item["caveats"] = self._json_load(item.get("caveats"), [])
            item["credentials_required"] = bool(item["credentials_required"])
            item["article_excerpt_display"] = bool(item["article_excerpt_display"])
            output.append(item)
        return output

    def source_due(self, source_id, now=None):
        now = now or datetime.now(UTC)

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT sources.enabled, sources.poll_seconds,
                       source_cursors.last_polled_at
                FROM sources
                JOIN source_cursors ON source_cursors.source_id = sources.id
                WHERE sources.id = ?
                """,
                (source_id,)
            ).fetchone()

        if not row or not row["enabled"]:
            return False

        if not row["last_polled_at"]:
            return True

        try:
            last = datetime.fromisoformat(
                row["last_polled_at"].replace("Z", "+00:00")
            )
        except ValueError:
            return True

        return (now - last).total_seconds() >= row["poll_seconds"]

    def begin_collector_run(self, source_id):
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO collector_runs (source_id, started_at)
                VALUES (?, ?)
                """,
                (source_id, utc_now())
            )
            return cursor.lastrowid

    def finish_collector_run(
        self,
        run_id,
        source_id,
        cursor,
        fetched_count,
        result=None,
        error=None
    ):
        now = utc_now()
        result = result or IngestResult()
        outcome = "failed" if error else "succeeded"

        with self._connect() as connection:
            connection.execute(
                """
                UPDATE collector_runs
                SET finished_at = ?, outcome = ?, fetched_count = ?,
                    inserted_count = ?, updated_count = ?,
                    duplicate_count = ?, error = ?
                WHERE id = ?
                """,
                (
                    now,
                    outcome,
                    fetched_count,
                    result.inserted,
                    result.updated,
                    result.duplicates,
                    str(error or ""),
                    run_id
                )
            )
            connection.execute(
                """
                UPDATE source_cursors
                SET cursor = ?, last_polled_at = ?, updated_at = ?
                WHERE source_id = ?
                """,
                (self._json(cursor or {}), now, now, source_id)
            )

            if error:
                connection.execute(
                    """
                    UPDATE sources
                    SET last_error_at = ?, last_error = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (now, str(error)[:2000], now, source_id)
                )
            else:
                connection.execute(
                    """
                    UPDATE sources
                    SET last_success_at = ?, last_error = '', updated_at = ?
                    WHERE id = ?
                    """,
                    (now, now, source_id)
                )

    def ingest_items(self, source_id, items):
        inserted = 0
        updated = 0
        duplicates = 0
        now = utc_now()

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")

            for item in items:
                outcome = self._ingest_item(connection, source_id, item, now)

                if outcome == "inserted":
                    inserted += 1
                elif outcome == "updated":
                    updated += 1
                else:
                    duplicates += 1

            result = IngestResult(inserted, updated, duplicates)

            if result.changed:
                connection.execute(
                    """
                    INSERT INTO intelligence_outbox (
                        event_type, priority, payload, created_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        "intelligence_documents_ingested",
                        2,
                        self._json(
                            {
                                "source_id": source_id,
                                "inserted": inserted,
                                "updated": updated
                            }
                        ),
                        now
                    )
                )

            connection.execute(
                """
                INSERT INTO access_audit (
                    source_id, action, target, details, created_at
                ) VALUES (?, 'ingest', ?, ?, ?)
                """,
                (
                    source_id,
                    f"{len(items)} documents",
                    self._json(
                        {
                            "inserted": inserted,
                            "updated": updated,
                            "duplicates": duplicates
                        }
                    ),
                    now
                )
            )

        return result

    def ingest_replay_item(self, source_id, item, captured_at):
        """Import one ordered replay item without touching collector state."""
        captured_at = normalize_timestamp(captured_at)
        if not captured_at:
            raise ValueError("Replay evidence requires a capture timestamp.")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            return self._ingest_item(connection, source_id, item, captured_at)

    def _ingest_item(self, connection, source_id, item, now):
        if not isinstance(item, SourceItem):
            raise TypeError("Intelligence items must be SourceItem instances.")

        canonical_url = canonicalize_url(item.url)
        canonical_seed = f"{source_id}:{canonical_url or item.external_id}"
        canonical_key = hashlib.sha256(
            canonical_seed.encode("utf-8")
        ).hexdigest()
        metadata = self._json(item.metadata or {})
        publisher_key, publisher_label = publisher_identity(
            source_id, item.metadata or {}
        )
        content_hash = document_hash(item)
        status = _document_status(item.status)
        existing = connection.execute(
            "SELECT * FROM documents WHERE canonical_key = ?",
            (canonical_key,)
        ).fetchone()

        if existing and existing["content_hash"] == content_hash:
            return "duplicate"

        if existing:
            document_id = existing["id"]
            version = connection.execute(
                """
                SELECT COALESCE(MAX(version), 0) + 1 AS next_version
                FROM document_versions
                WHERE document_id = ?
                """,
                (document_id,)
            ).fetchone()["next_version"]
            connection.execute(
                """
                UPDATE documents
                SET source_id = ?, external_id = ?, title = ?, url = ?,
                    canonical_url = ?, summary = ?, content = ?, category = ?,
                    published_at = ?, retrieved_at = ?, latitude = ?,
                    longitude = ?, content_hash = ?, metadata = ?,
                    status = ?, publisher_key = ?, publisher_label = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    source_id,
                    item.external_id,
                    clean_text(item.title),
                    item.url,
                    canonical_url,
                    clean_text(item.summary),
                    clean_text(item.content),
                    clean_category(item.category),
                    normalize_timestamp(item.published_at),
                    now,
                    item.latitude,
                    item.longitude,
                    content_hash,
                    metadata,
                    status,
                    publisher_key,
                    publisher_label,
                    now,
                    document_id
                )
            )
            outcome = "updated"
        else:
            document_id = (
                str(self.document_id_factory(source_id, canonical_key, item))
                if self.document_id_factory is not None else str(uuid4())
            )
            version = 1
            connection.execute(
                """
                INSERT INTO documents (
                    id, canonical_key, source_id, external_id, title, url,
                    canonical_url, summary, content, category, published_at,
                    retrieved_at, latitude, longitude, content_hash, metadata,
                    status, publisher_key, publisher_label, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    canonical_key,
                    source_id,
                    item.external_id,
                    clean_text(item.title),
                    item.url,
                    canonical_url,
                    clean_text(item.summary),
                    clean_text(item.content),
                    clean_category(item.category),
                    normalize_timestamp(item.published_at),
                    now,
                    item.latitude,
                    item.longitude,
                    content_hash,
                    metadata,
                    status,
                    publisher_key,
                    publisher_label,
                    now,
                    now
                )
            )
            outcome = "inserted"

        connection.execute(
            """
            INSERT INTO document_versions (
                document_id, version, title, summary, content, published_at,
                content_hash, metadata, captured_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document_id,
                version,
                clean_text(item.title),
                clean_text(item.summary),
                clean_text(item.content),
                normalize_timestamp(item.published_at),
                content_hash,
                metadata,
                now
            )
        )
        return outcome

    def overview(self):
        with self._connect() as connection:
            counts = connection.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM documents) AS documents,
                    (SELECT COUNT(*) FROM sources WHERE enabled = 1) AS sources,
                    (SELECT COUNT(*) FROM sources WHERE last_error != '') AS unhealthy,
                    (SELECT COUNT(*) FROM collector_runs) AS collector_runs,
                    (SELECT COUNT(*) FROM situations) AS situations,
                    (SELECT COUNT(*) FROM claims
                     WHERE status != 'superseded') AS claims,
                    (SELECT COUNT(*) FROM claims
                     WHERE status = 'contested') AS contested_claims,
                    (SELECT COUNT(*) FROM situation_merge_candidates
                     WHERE decision = 'review') AS cluster_reviews,
                    (SELECT COUNT(*) FROM document_relationships
                     WHERE relationship IN ('copied','syndicated'))
                     AS dependent_reports,
                    (SELECT COUNT(*) FROM claims
                     WHERE extraction_version = 'hybrid-claims-v1')
                     AS epistemically_typed_claims,
                    (SELECT COALESCE(SUM(processed), 0)
                     FROM epistemic_backfill_state
                     WHERE name IN ('historical-claim-epistemics',
                                    'historical-prose-claims'))
                     AS epistemic_backfill_processed,
                    (SELECT CASE WHEN COUNT(*) = 2 AND MIN(completed) = 1
                                 THEN 1 ELSE 0 END
                     FROM epistemic_backfill_state
                     WHERE name IN ('historical-claim-epistemics',
                                    'historical-prose-claims'))
                     AS epistemic_backfill_complete,
                    (SELECT COUNT(*) FROM situation_integrity_flags
                     WHERE status = 'review') AS integrity_reviews,
                    (SELECT COUNT(*) FROM claims
                     WHERE truth_status = 'corroborated') AS corroborated_claims,
                    (SELECT COUNT(*) FROM claims
                     WHERE truth_status IN ('disputed','refuted')) AS disputed_truth_claims,
                    (SELECT COUNT(*) FROM claim_verification_tasks
                     WHERE status = 'pending') AS verification_tasks,
                    (SELECT COUNT(*) FROM claim_verification_tasks
                     WHERE status = 'deferred') AS deferred_verification_tasks,
                    (SELECT COUNT(*) FROM claim_verification_results)
                     AS verification_results,
                    (SELECT COUNT(*) FROM verification_targets
                     WHERE target_status='ready') AS ready_verification_targets,
                    (SELECT COUNT(*) FROM verification_observations)
                     AS verification_observations,
                    (SELECT COUNT(*) FROM claim_groundings)
                     AS claim_groundings,
                    (SELECT COUNT(*) FROM verification_targets
                     WHERE target_status='unresolvable')
                     AS unresolvable_verification_targets,
                    (SELECT COUNT(*) FROM ensemble_training_runs)
                     AS ensemble_training_runs,
                    (SELECT COUNT(*) FROM forecast_model_versions
                     WHERE status='shadow') AS shadow_ensemble_models,
                    (SELECT COUNT(*) FROM intelligence_gaps
                     WHERE status = 'open') AS intelligence_gaps,
                    ((SELECT COUNT(*) FROM active_acquisition_attempts) +
                     (SELECT COUNT(*) FROM verification_acquisition_attempts))
                     AS acquisition_attempts,
                    (SELECT COUNT(*) FROM forecasts
                     WHERE status='active' AND shadow=1)
                     AS active_shadow_forecasts,
                    (SELECT COUNT(*) FROM intelligence_feature_gates
                     WHERE status = 'blocked') AS blocked_feature_gates,
                    (SELECT COUNT(*) FROM intelligence_reasoning_jobs
                     WHERE status = 'pending') AS pending_reasoning_jobs
                """
            ).fetchone()
            categories = connection.execute(
                """
                SELECT category, COUNT(*) AS count
                FROM documents
                GROUP BY category
                ORDER BY count DESC, category
                """
            ).fetchall()
            latest = connection.execute(
                "SELECT MAX(retrieved_at) AS latest FROM documents"
            ).fetchone()["latest"]

        result = dict(counts)
        result["epistemic_backfill_processed"] = (
            result["epistemic_backfill_processed"] or 0
        )
        result["epistemic_backfill_complete"] = (
            result["epistemic_backfill_complete"] or 0
        )
        return {
            **result,
            "latest_retrieved_at": latest,
            "categories": [dict(row) for row in categories]
        }

    def clustering_overview(self):
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                  (SELECT COUNT(*) FROM document_features) AS featured_documents,
                  (SELECT COUNT(*) FROM document_relationships
                   WHERE relationship = 'copied') AS copied_relationships,
                  (SELECT COUNT(*) FROM document_relationships
                   WHERE relationship = 'syndicated') AS syndicated_relationships,
                  (SELECT COUNT(*) FROM situation_merge_candidates
                   WHERE decision = 'review') AS review_candidates,
                  (SELECT COUNT(*) FROM situations
                   WHERE status = 'merged') AS merged_situations
                """
            ).fetchone()
        return dict(row)

    def list_merge_candidates(self, limit=100, decision="review"):
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT situation_merge_candidates.*,
                       source.title AS source_title,
                       target.title AS target_title
                FROM situation_merge_candidates
                JOIN situations AS source
                  ON source.id = source_situation_id
                JOIN situations AS target
                  ON target.id = target_situation_id
                WHERE situation_merge_candidates.decision = ?
                ORDER BY score DESC, created_at DESC LIMIT ?
                """,
                (str(decision), max(1, min(1000, int(limit))))
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["components"] = self._json_load(item.get("components"), {})
            item["vetoes"] = self._json_load(item.get("vetoes"), [])
            items.append(item)
        return items

    def list_documents(self, limit=50, category=None):
        limit = max(1, min(200, int(limit)))
        query = """
            SELECT documents.*, sources.name AS source_name,
                   sources.credibility AS source_credibility
            FROM documents
            JOIN sources ON sources.id = documents.source_id
        """
        params = []

        if category:
            query += " WHERE documents.category = ?"
            params.append(clean_category(category))

        query += " ORDER BY COALESCE(published_at, retrieved_at) DESC LIMIT ?"
        params.append(limit)

        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()

        return [self._document_from_row(row) for row in rows]

    def list_sources(self):
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT sources.*,
                       source_cursors.last_polled_at,
                       COUNT(documents.id) AS document_count
                FROM sources
                LEFT JOIN source_cursors
                  ON source_cursors.source_id = sources.id
                LEFT JOIN documents ON documents.source_id = sources.id
                GROUP BY sources.id
                ORDER BY sources.name
                """
            ).fetchall()

        return [self._source_from_row(row) for row in rows]

    def list_publisher_reputations(self, limit=200):
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT publisher_reputation.*,
                       assessments.evidence_estimate,
                       assessments.effective_credibility,
                       assessments.reliability_lower_bound
                         AS assessment_lower_bound,
                       assessments.reliability_upper_bound
                         AS assessment_upper_bound,
                       assessments.confirmed_count AS assessment_confirmed_count,
                       assessments.refuted_count AS assessment_refuted_count,
                       assessments.mixed_count AS assessment_mixed_count,
                       assessments.factual_samples AS assessment_factual_samples,
                       assessments.maturity_status,
                       assessments.framing_signal AS assessment_framing_signal,
                       assessments.observed_framing,
                       assessments.timeliness_score AS assessment_timeliness_score,
                       assessments.method AS assessment_method,
                       assessments.updated_at AS assessment_updated_at,
                       profiles.factual_accuracy,
                       profiles.attribution_quality,
                       profiles.revision_discipline,
                       profiles.independence_confidence,
                       profiles.framing_signal,
                       profiles.timeliness_score,
                       profiles.timeliness_samples,
                       profiles.factual_samples,
                       priors.framing_signal AS framing_prior,
                       priors.affiliation,
                       priors.rationale AS profile_rationale,
                       priors.configured_by AS profile_configured_by,
                       (SELECT outcome FROM publisher_outcomes
                        WHERE publisher_key = publisher_reputation.publisher_key
                        ORDER BY evaluated_at DESC LIMIT 1) AS latest_outcome,
                       (SELECT reason FROM publisher_outcomes
                        WHERE publisher_key = publisher_reputation.publisher_key
                        ORDER BY evaluated_at DESC LIMIT 1) AS latest_outcome_reason,
                       (SELECT evaluated_at FROM publisher_outcomes
                        WHERE publisher_key = publisher_reputation.publisher_key
                        ORDER BY evaluated_at DESC LIMIT 1) AS latest_outcome_at
                FROM publisher_reputation
                LEFT JOIN publisher_assessments assessments
                  ON assessments.publisher_key=publisher_reputation.publisher_key
                 AND assessments.scope_kind='global'
                 AND assessments.scope_value=''
                LEFT JOIN publisher_epistemic_profiles profiles
                  ON profiles.publisher_key=publisher_reputation.publisher_key
                LEFT JOIN publisher_profile_priors priors
                  ON priors.publisher_key=publisher_reputation.publisher_key
                ORDER BY COALESCE(assessments.factual_samples,0) DESC,
                         COALESCE(assessments.effective_credibility,
                                  learned_credibility) DESC,
                         publisher_label
                LIMIT ?
                """,
                (max(1, min(1000, int(limit))),)
            ).fetchall()
        return [dict(row) for row in rows]

    def publisher_audit(self, publisher_key, limit=100):
        publisher_key = str(publisher_key or "")[:300]
        limit = max(1, min(500, int(limit)))
        with self._connect() as connection:
            assessments = connection.execute(
                """SELECT * FROM publisher_assessments WHERE publisher_key=?
                   ORDER BY scope_kind,scope_value""", (publisher_key,)
            ).fetchall()
            history = connection.execute(
                """SELECT * FROM publisher_assessment_history
                   WHERE publisher_key=? ORDER BY created_at DESC,id DESC LIMIT ?""",
                (publisher_key, limit),
            ).fetchall()
            dimensions = connection.execute(
                """SELECT * FROM publisher_dimension_observations
                   WHERE publisher_key=? ORDER BY created_at DESC,id DESC LIMIT ?""",
                (publisher_key, limit),
            ).fetchall()
            families = connection.execute(
                """SELECT reporting_family_key,COUNT(*) document_count,
                          MIN(published_at) first_reported_at,
                          MAX(published_at) latest_reported_at
                   FROM documents WHERE publisher_key=?
                     AND reporting_family_key!=''
                   GROUP BY reporting_family_key
                   ORDER BY latest_reported_at DESC LIMIT ?""",
                (publisher_key, limit),
            ).fetchall()
        return {
            "publisher_key": publisher_key,
            "assessments": [dict(row) for row in assessments],
            "history": [dict(row) for row in history],
            "dimensions": [
                {**dict(row), "evidence_ids": self._json_load(row["evidence_ids"], [])}
                for row in dimensions
            ],
            "outcomes": self.list_publisher_outcomes(publisher_key, limit),
            "reliability_cells": self.list_reliability_cells(publisher_key, limit),
            "reporting_families": [dict(row) for row in families],
        }

    def reporting_family_audit(self, family_key, limit=100):
        family_key = str(family_key or "")[:300]
        limit = max(1, min(500, int(limit)))
        with self._connect() as connection:
            documents = connection.execute(
                """SELECT id,publisher_key,publisher_label,title,url,published_at,
                          retrieved_at,status
                   FROM documents WHERE reporting_family_key=?
                   ORDER BY published_at,retrieved_at LIMIT ?""",
                (family_key, limit),
            ).fetchall()
            relationships = connection.execute(
                """SELECT * FROM document_relationships
                   WHERE left_document_id IN (
                     SELECT id FROM documents WHERE reporting_family_key=?) OR
                         right_document_id IN (
                     SELECT id FROM documents WHERE reporting_family_key=?)
                   ORDER BY created_at LIMIT ?""",
                (family_key, family_key, limit),
            ).fetchall()
        return {"reporting_family_key": family_key,
                "documents": [dict(row) for row in documents],
                "relationships": [dict(row) for row in relationships]}

    def list_enrichment_queue(self, status=None, limit=100):
        allowed = {
            "needs-model", "media-unavailable", "media-derived-pending",
            "unresolved-location", "unresolved", "all",
        }
        status = str(status or "unresolved")
        if status not in allowed:
            status = "all"
        query = """SELECT enrichment.document_id,enrichment.document_version_id,
                    enrichment.status,enrichment.detected_language,
                    enrichment.location_label,enrichment.country_name,
                    enrichment.updated_at,documents.publisher_key,
                    documents.publisher_label,documents.title,documents.url
                 FROM document_enrichments enrichment
                 JOIN documents ON documents.id=enrichment.document_id"""
        params = []
        if status == "unresolved":
            query += " WHERE enrichment.status!='complete'"
        elif status == "unresolved-location":
            query += " WHERE enrichment.location_label=''"
        elif status != "all":
            query += " WHERE enrichment.status=?"
            params.append(status)
        query += " ORDER BY enrichment.updated_at DESC LIMIT ?"
        params.append(max(1, min(500, int(limit))))
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def media_derivation_overview(self, limit=100):
        with self._connect() as connection:
            totals = connection.execute(
                """SELECT COUNT(*) total,
                   COALESCE(SUM(status='complete'),0) complete,
                   COALESCE(SUM(status='unavailable'),0) unavailable,
                   COALESCE(SUM(status='failed'),0) failed
                   FROM public_media_derivations"""
            ).fetchone()
            recent = connection.execute(
                """SELECT derivation.*,documents.publisher_key,documents.title,
                          documents.url
                   FROM public_media_derivations derivation
                   JOIN documents ON documents.id=derivation.document_id
                   ORDER BY derivation.updated_at DESC,derivation.id DESC LIMIT ?""",
                (max(1, min(500, int(limit))),),
            ).fetchall()
            state = connection.execute(
                "SELECT * FROM public_media_derivation_state WHERE lane=?",
                ("public-media-versions-v1",),
            ).fetchone()
        return {"totals": dict(totals), "recent": [dict(row) for row in recent],
                "state": dict(state) if state else {}}

    def reasoning_budget_overview(self):
        now = datetime.now(UTC)
        hour = now.strftime("%Y-%m-%dT%H:00:00Z")
        day = now.strftime("%Y-%m-%dT00:00:00Z")
        next_hour = (now.replace(minute=0, second=0, microsecond=0)
                     + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        next_day = (now.replace(hour=0, minute=0, second=0, microsecond=0)
                    + timedelta(days=1)).isoformat().replace("+00:00", "Z")
        with self._connect() as connection:
            policies = connection.execute(
                "SELECT * FROM intelligence_budget_lane_policies ORDER BY lane"
            ).fetchall()
            usage = connection.execute(
                """SELECT bucket_type,bucket_start,model_calls,
                          estimated_input_tokens,estimated_output_tokens
                   FROM intelligence_budget_usage
                   WHERE (bucket_type='hour' AND bucket_start=?) OR
                         (bucket_type='day' AND bucket_start=?)
                   ORDER BY bucket_type""", (hour, day)
            ).fetchall()
            lanes = connection.execute(
                """SELECT bucket_type,bucket_start,lane,model_calls,
                          estimated_input_tokens,estimated_output_tokens
                   FROM intelligence_budget_lane_usage
                   WHERE (bucket_type='hour' AND bucket_start=?) OR
                         (bucket_type='day' AND bucket_start=?)
                   ORDER BY bucket_type,lane""", (hour, day)
            ).fetchall()
            attempts = connection.execute(
                """SELECT lane,status,COUNT(*) count,MAX(started_at) latest
                   FROM intelligence_model_attempts
                   WHERE julianday(started_at)>=julianday('now','-24 hours')
                   GROUP BY lane,status ORDER BY lane,status"""
            ).fetchall()
            cache = connection.execute(
                """SELECT COUNT(*) entries,COALESCE(SUM(hit_count),0) hits,
                          MAX(last_used_at) latest_hit_at
                   FROM intelligence_model_result_cache"""
            ).fetchone()
        return {
            "policies": [dict(row) for row in policies],
            "usage": [dict(row) for row in usage],
            "lane_usage": [dict(row) for row in lanes],
            "attempts_24h": [dict(row) for row in attempts],
            "result_cache": dict(cache),
            "next_hourly_reset_at": next_hour,
            "next_daily_reset_at": next_day,
        }

    def scheduler_cursor(self, engine):
        with self._connect() as connection:
            row = connection.execute(
                """SELECT last_rotation_key FROM intelligence_scheduler_state
                   WHERE engine=?""",
                (str(engine)[:120],),
            ).fetchone()
        return str(row[0] or "") if row else ""

    def advance_scheduler_cursor(self, engine, rotation_key):
        engine = str(engine)[:120]
        rotation_key = str(rotation_key or "")[:300]
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO intelligence_scheduler_state (
                     engine,last_rotation_key,updated_at
                   ) VALUES (?,?,?)
                   ON CONFLICT(engine) DO UPDATE SET
                     last_rotation_key=excluded.last_rotation_key,
                     updated_at=excluded.updated_at""",
                (engine, rotation_key, now),
            )

    def configure_workload_limits(self, engine, max_active_per_key,
                                  max_active_global,
                                  max_fresh_active_per_key=2,
                                  max_fresh_active_global=10):
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO intelligence_workload_limits (
                     engine,max_active_per_key,max_active_global,
                     max_fresh_active_per_key,max_fresh_active_global,updated_at
                   ) VALUES (?,?,?,?,?,?)
                   ON CONFLICT(engine) DO UPDATE SET
                     max_active_per_key=excluded.max_active_per_key,
                     max_active_global=excluded.max_active_global,
                     max_fresh_active_per_key=excluded.max_fresh_active_per_key,
                     max_fresh_active_global=excluded.max_fresh_active_global,
                     updated_at=excluded.updated_at""",
                (
                    str(engine)[:120], max(1, int(max_active_per_key)),
                    max(1, int(max_active_global)),
                    max(1, int(max_fresh_active_per_key)),
                    max(1, int(max_fresh_active_global)), now,
                ),
            )

    def article_analysis_overview(self, limit=100):
        limit = max(1, min(500, int(limit)))
        with self._connect() as connection:
            tasks = connection.execute(
                """SELECT status,COUNT(*) count FROM article_acquisition_tasks
                   GROUP BY status ORDER BY status"""
            ).fetchall()
            active_publishers = connection.execute(
                """SELECT COALESCE(NULLIF(documents.publisher_key,''),
                                   tasks.source_id) publisher_key,
                          COUNT(*) active_tasks,MIN(tasks.created_at) oldest_active_at
                          ,SUM(tasks.work_class!='fresh') backfill_active_tasks
                          ,SUM(tasks.work_class='fresh') fresh_active_tasks
                   FROM article_acquisition_tasks tasks
                   JOIN documents ON documents.id=tasks.document_id
                   WHERE tasks.status IN ('pending','retry','running')
                   GROUP BY COALESCE(NULLIF(documents.publisher_key,''),
                                     tasks.source_id)
                   ORDER BY publisher_key"""
            ).fetchall()
            limits = connection.execute(
                """SELECT max_active_per_key,max_active_global,
                          max_fresh_active_per_key,max_fresh_active_global
                   FROM intelligence_workload_limits
                   WHERE engine='article-acquisition'"""
            ).fetchone()
            captures = connection.execute(
                """SELECT content_scope,COUNT(*) count,
                          COALESCE(SUM(word_count),0) words
                   FROM article_content_captures WHERE status='complete'
                   GROUP BY content_scope ORDER BY content_scope"""
            ).fetchall()
            framing = connection.execute(
                """SELECT status,COUNT(*) count,
                          COALESCE(SUM(evidence_count),0) evidence_count
                   FROM article_framing_assessments
                   GROUP BY status ORDER BY status"""
            ).fetchall()
            recent = connection.execute(
                """SELECT capture.id,capture.document_id,capture.content_scope,
                          capture.word_count,capture.status,capture.extractor,
                          capture.captured_at,documents.publisher_key,
                          documents.publisher_label,documents.title,documents.url,
                          CASE WHEN policies.article_excerpt_display=1
                               THEN substr(capture.normalized_text,1,500)
                               ELSE '' END excerpt
                   FROM article_content_captures capture
                   JOIN documents ON documents.id=capture.document_id
                   JOIN source_policies policies ON policies.source_id=capture.source_id
                   ORDER BY capture.captured_at DESC,capture.id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        publisher_rows = [dict(row) for row in active_publishers]
        active_total = sum(int(row["active_tasks"]) for row in publisher_rows)
        backfill_active_total = sum(
            int(row["backfill_active_tasks"] or 0) for row in publisher_rows
        )
        per_key_limit = int(limits[0]) if limits else 0
        global_limit = int(limits[1]) if limits else 0
        fresh_per_key_limit = int(limits[2]) if limits else 0
        fresh_global_limit = int(limits[3]) if limits else 0
        fresh_active_total = sum(
            int(row["fresh_active_tasks"] or 0) for row in publisher_rows
        )
        above_limit = bool(
            (global_limit and backfill_active_total > global_limit)
            or any(
                per_key_limit
                and int(row["backfill_active_tasks"] or 0) > per_key_limit
                for row in publisher_rows
            )
        )
        at_limit = bool(
            (global_limit and backfill_active_total >= global_limit)
            or any(
                per_key_limit
                and int(row["backfill_active_tasks"] or 0) >= per_key_limit
                for row in publisher_rows
            )
        )
        for row in publisher_rows:
            row["max_active_tasks"] = per_key_limit
            row["max_fresh_active_tasks"] = fresh_per_key_limit
            row["ceiling_status"] = (
                "draining" if per_key_limit
                and row["backfill_active_tasks"] > per_key_limit
                else "backpressure-active"
                if per_key_limit
                and row["backfill_active_tasks"] >= per_key_limit
                else "healthy"
            )
            row["fresh_ceiling_status"] = (
                "backpressure-active"
                if fresh_per_key_limit
                and row["fresh_active_tasks"] >= fresh_per_key_limit
                else "healthy"
            )
        readiness = self.comparison_readiness(window_minutes=60, limit=25)
        return {
            "tasks": [dict(row) for row in tasks],
            "captures": [dict(row) for row in captures],
            "framing": [dict(row) for row in framing],
            "recent": [dict(row) for row in recent],
            "queue_health": {
                "status": (
                    "draining" if above_limit else
                    "backpressure-active" if at_limit else "healthy"
                ),
                "active_tasks": active_total,
                "backfill_active_tasks": backfill_active_total,
                "fresh_active_tasks": fresh_active_total,
                "max_active_per_publisher": per_key_limit,
                "max_active_global": global_limit,
                "max_fresh_active_per_publisher": fresh_per_key_limit,
                "max_fresh_active_global": fresh_global_limit,
                "publishers": publisher_rows,
            },
            "comparison_readiness": {
                "eligible_events": readiness["eligible_events"],
                "comparisons": readiness["comparisons"],
                "current_gate": readiness["current_gate"],
                "publishers": readiness["publishers"],
                "fusion_by_publisher": readiness["fusion_by_publisher"],
                "event_ready": readiness["event_ready"],
            },
        }

    def workload_queue_metrics(self, window_minutes=60, now=None):
        window_minutes = max(15, min(1440, int(window_minutes)))
        now = now or datetime.now(UTC)
        cutoff = (now - timedelta(minutes=window_minutes)).isoformat(
            timespec="seconds"
        ).replace("+00:00", "Z")
        with self._connect() as connection:
            limits = connection.execute(
                """SELECT max_active_per_key,max_active_global,
                          max_fresh_active_per_key,max_fresh_active_global
                   FROM intelligence_workload_limits
                   WHERE engine='article-acquisition'"""
            ).fetchone()
            rows = connection.execute(
                """SELECT COALESCE(NULLIF(documents.publisher_key,''),
                                   tasks.source_id) publisher_key,
                          SUM(tasks.work_class!='fresh') backfill_active,
                          SUM(tasks.work_class='fresh') fresh_active
                   FROM article_acquisition_tasks tasks
                   JOIN documents ON documents.id=tasks.document_id
                   WHERE tasks.status IN ('pending','retry','running')
                   GROUP BY COALESCE(NULLIF(documents.publisher_key,''),
                                     tasks.source_id)"""
            ).fetchall()
            recent_completions = connection.execute(
                """SELECT COUNT(*) FROM article_acquisition_tasks
                   WHERE status='complete' AND updated_at>=?""", (cutoff,)
            ).fetchone()[0]
        per_key, global_limit, fresh_per_key, fresh_global = (
            [int(value) for value in limits] if limits else (0, 0, 0, 0)
        )
        publishers = [dict(row) for row in rows]
        backfill = sum(int(row["backfill_active"] or 0) for row in publishers)
        fresh = sum(int(row["fresh_active"] or 0) for row in publishers)
        over = bool(
            (global_limit and backfill > global_limit)
            or any(per_key and int(row["backfill_active"] or 0) > per_key
                   for row in publishers)
        )
        at = bool(
            over or (global_limit and backfill >= global_limit)
            or any(per_key and int(row["backfill_active"] or 0) >= per_key
                   for row in publishers)
        )
        return {
            "backfill_active": backfill, "fresh_active": fresh,
            "active_total": backfill + fresh,
            "limits_known": limits is not None,
            "max_active_per_publisher": per_key,
            "max_active_global": global_limit,
            "max_fresh_active_per_publisher": fresh_per_key,
            "max_fresh_active_global": fresh_global,
            "at_ceiling": at, "over_ceiling": over,
            "recent_completions": int(recent_completions),
        }

    def record_workload_state(self, engine, status, reason, metrics,
                              policy_version, checked_at=None):
        checked_at = checked_at or utc_now()
        engine = str(engine)[:120]
        status = str(status)[:80]
        reason = str(reason)[:200]
        policy_version = str(policy_version)[:120]
        encoded = json.dumps(metrics, separators=(",", ":"), sort_keys=True)
        with self._connect() as connection:
            previous = connection.execute(
                "SELECT * FROM intelligence_workload_state WHERE engine=?",
                (engine,),
            ).fetchone()
            changed = previous is None or (
                previous["status"] != status or previous["reason"] != reason
            )
            first_entered = (
                checked_at if changed else previous["first_entered_at"]
            )
            connection.execute(
                """INSERT INTO intelligence_workload_state (
                     engine,status,reason,metrics,policy_version,first_entered_at,
                     last_checked_at,updated_at
                   ) VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(engine) DO UPDATE SET
                     status=excluded.status,reason=excluded.reason,
                     metrics=excluded.metrics,policy_version=excluded.policy_version,
                     first_entered_at=excluded.first_entered_at,
                     last_checked_at=excluded.last_checked_at,
                     updated_at=excluded.updated_at""",
                (engine, status, reason, encoded, policy_version, first_entered,
                 checked_at, checked_at),
            )
            if changed:
                connection.execute(
                    """INSERT INTO intelligence_workload_transitions (
                         engine,previous_status,new_status,reason,metrics,
                         policy_version,transitioned_at
                       ) VALUES (?,?,?,?,?,?,?)""",
                    (engine, previous["status"] if previous else "", status,
                     reason, encoded, policy_version, checked_at),
                )
        return changed

    def workload_health(self, window_minutes=60, transition_limit=20):
        window_minutes = max(15, min(1440, int(window_minutes)))
        transition_limit = max(1, min(100, int(transition_limit)))
        now = datetime.now(UTC)
        cutoff = (now - timedelta(minutes=window_minutes)).isoformat(
            timespec="seconds"
        ).replace("+00:00", "Z")
        queue = self.workload_queue_metrics(window_minutes, now=now)
        with self._connect() as connection:
            state = connection.execute(
                "SELECT * FROM intelligence_workload_state WHERE engine=?",
                ("article-acquisition",),
            ).fetchone()
            grouped = connection.execute(
                """SELECT tasks.work_class,tasks.status,
                          COALESCE(NULLIF(documents.publisher_key,''),
                                   tasks.source_id) publisher_key,
                          COUNT(*) count
                   FROM article_acquisition_tasks tasks
                   JOIN documents ON documents.id=tasks.document_id
                   WHERE tasks.status IN ('pending','retry','running')
                   GROUP BY tasks.work_class,tasks.status,
                     COALESCE(NULLIF(documents.publisher_key,''),tasks.source_id)
                   ORDER BY publisher_key,tasks.work_class,tasks.status"""
            ).fetchall()
            ages = connection.execute(
                """SELECT created_at FROM article_acquisition_tasks
                   WHERE status IN ('pending','retry','running')
                   ORDER BY created_at LIMIT 2000"""
            ).fetchall()
            recent = connection.execute(
                """SELECT
                   (SELECT COUNT(*) FROM article_acquisition_tasks
                    WHERE created_at>=?) enqueued,
                   (SELECT COUNT(*) FROM article_acquisition_tasks
                    WHERE status='complete' AND updated_at>=?) completed,
                   (SELECT COUNT(*) FROM article_content_captures
                    WHERE captured_at>=?) captured,
                   (SELECT COUNT(*) FROM article_framing_assessments
                    WHERE updated_at>=?) assessed,
                   (SELECT COUNT(*) FROM article_acquisition_tasks
                    WHERE status='retry' AND updated_at>=?) retries,
                   (SELECT COUNT(*) FROM article_acquisition_tasks
                    WHERE status='blocked' AND updated_at>=?) blocked,
                   (SELECT COUNT(*) FROM article_acquisition_tasks
                    WHERE status='running' AND lease_expires_at<=?) expired_leases""",
                (cutoff, cutoff, cutoff, cutoff, cutoff, cutoff, utc_now()),
            ).fetchone()
            publishers = connection.execute(
                """SELECT COALESCE(NULLIF(documents.publisher_key,''),
                                   tasks.source_id) publisher_key,
                          SUM(tasks.status IN ('pending','retry','running')) active,
                          SUM(tasks.status='complete' AND tasks.updated_at>=?) completed
                   FROM article_acquisition_tasks tasks
                   JOIN documents ON documents.id=tasks.document_id
                   GROUP BY COALESCE(NULLIF(documents.publisher_key,''),
                                     tasks.source_id)
                   ORDER BY publisher_key""", (cutoff,)
            ).fetchall()
            latency_rows = connection.execute(
                """SELECT documents.retrieved_at,captures.captured_at,
                          assessments.updated_at assessed_at
                   FROM article_acquisition_tasks tasks
                   JOIN documents ON documents.id=tasks.document_id
                   LEFT JOIN article_content_captures captures
                     ON captures.document_version_id=tasks.document_version_id
                   LEFT JOIN article_framing_assessments assessments
                     ON assessments.article_capture_id=captures.id
                   WHERE tasks.work_class='fresh'
                   ORDER BY tasks.updated_at DESC,tasks.id DESC LIMIT 500"""
            ).fetchall()
            transitions = connection.execute(
                """SELECT previous_status,new_status,reason,policy_version,
                          transitioned_at
                   FROM intelligence_workload_transitions WHERE engine=?
                   ORDER BY transitioned_at DESC,id DESC LIMIT ?""",
                ("article-acquisition", transition_limit),
            ).fetchall()
        state_dict = dict(state) if state else {
            "engine": "article-acquisition", "status": "unknown",
            "reason": "not-yet-checked", "policy_version": "",
            "first_entered_at": None, "last_checked_at": None,
            "updated_at": None, "metrics": "{}",
        }
        persisted = self._json_load(state_dict.pop("metrics", "{}"), {})
        age_seconds = sorted(
            max(0.0, (now - _parse_utc(row["created_at"])).total_seconds())
            for row in ages if _parse_utc(row["created_at"]) is not None
        )
        publisher_metrics = []
        hours = window_minutes / 60
        for row in publishers:
            item = dict(row)
            rate = int(item["completed"] or 0) / hours
            item["completion_rate_per_hour"] = round(rate, 3)
            item["drain_estimate_hours"] = (
                round(int(item["active"] or 0) / rate, 2) if rate > 0 else None
            )
            publisher_metrics.append(item)
        latency = {"retrieval_to_capture_seconds": [],
                   "capture_to_assessment_seconds": [],
                   "end_to_end_seconds": []}
        for row in latency_rows:
            retrieved = _parse_utc(row["retrieved_at"])
            captured = _parse_utc(row["captured_at"])
            assessed = _parse_utc(row["assessed_at"])
            if retrieved and captured:
                latency["retrieval_to_capture_seconds"].append(
                    max(0, (captured - retrieved).total_seconds())
                )
            if captured and assessed:
                latency["capture_to_assessment_seconds"].append(
                    max(0, (assessed - captured).total_seconds())
                )
            if retrieved and assessed:
                latency["end_to_end_seconds"].append(
                    max(0, (assessed - retrieved).total_seconds())
                )
        return {
            "state": state_dict,
            "storage": persisted.get("storage", {}),
            "queue": {**queue, "by_publisher_class_status": [
                dict(row) for row in grouped
            ], "oldest_age_seconds": age_seconds[-1] if age_seconds else None,
                "median_age_seconds": _percentile(age_seconds, 50)},
            "recent": {**dict(recent), "window_minutes": window_minutes},
            "publishers": publisher_metrics,
            "fresh_latency": {
                key: {"sample_count": len(values),
                      "p50": _percentile(values, 50),
                      "p95": _percentile(values, 95)}
                for key, values in latency.items()
            },
            "transitions": [dict(row) for row in transitions],
            "sample_limit": 2000,
        }

    def publisher_framing_audit(self, publisher_key, limit=100):
        publisher_key = str(publisher_key or "")[:300]
        limit = max(1, min(500, int(limit)))
        with self._connect() as connection:
            assessments = connection.execute(
                """SELECT assessment.*,capture.document_id,capture.captured_at,
                          documents.title,documents.url
                   FROM article_framing_assessments assessment
                   JOIN article_content_captures capture
                     ON capture.id=assessment.article_capture_id
                   JOIN documents ON documents.id=capture.document_id
                   WHERE assessment.publisher_key=?
                   ORDER BY assessment.updated_at DESC LIMIT ?""",
                (publisher_key, limit),
            ).fetchall()
            observations = connection.execute(
                """SELECT observation.*,documents.title,documents.url
                   FROM article_framing_observations observation
                   JOIN documents ON documents.id=observation.document_id
                   WHERE observation.publisher_key=?
                   ORDER BY observation.created_at DESC,observation.id DESC LIMIT ?""",
                (publisher_key, limit),
            ).fetchall()
            coverage = connection.execute(
                """SELECT * FROM publisher_coverage_windows
                   WHERE publisher_key=? ORDER BY window_end DESC LIMIT ?""",
                (publisher_key, limit),
            ).fetchall()
        return {
            "publisher_key": publisher_key,
            "mode": "shadow",
            "assessments": [
                {**dict(row), "dimension_scores": self._json_load(
                    row["dimension_scores"], {}
                )} for row in assessments
            ],
            "observations": [dict(row) for row in observations],
            "coverage": [dict(row) for row in coverage],
        }

    def event_framing_comparison_overview(self, limit=100):
        limit = max(1, min(500, int(limit)))
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT comparison.*,events.title AS canonical_title,
                          events.updated_at event_updated_at
                   FROM event_publisher_comparisons comparison
                   JOIN world_events events ON events.id=comparison.world_event_id
                   ORDER BY comparison.created_at DESC,comparison.id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return {"comparisons": [
            {
                **dict(row),
                "publisher_keys": self._json_load(row["publisher_keys"], []),
                "shared_claims": self._json_load(row["shared_claims"], []),
                "divergent_claims": self._json_load(row["divergent_claims"], []),
                "framing_dimensions": self._json_load(
                    row["framing_dimensions"], {}
                ),
            } for row in rows
        ]}

    def comparison_readiness(self, window_minutes=60, limit=100):
        """Bounded engineering audit for the assessed-evidence comparison path."""
        window_minutes = max(15, min(1440, int(window_minutes)))
        limit = max(1, min(500, int(limit)))
        fusion_method = "deterministic-event-fusion-v3"
        comparison_method = "event-framing-comparison-v2"
        with self._connect() as connection:
            publishers = connection.execute(
                """SELECT assessment.publisher_key,
                          COUNT(*) complete_assessments,
                          COUNT(DISTINCT capture.document_id) assessed_documents,
                          COUNT(DISTINCT CASE WHEN observation.id IS NULL
                            THEN capture.document_id END) awaiting_projection,
                          MIN(CASE WHEN observation.id IS NULL
                            THEN capture.captured_at END) oldest_projection_at
                   FROM article_framing_assessments assessment
                   JOIN article_content_captures capture
                     ON capture.id=assessment.article_capture_id
                    AND capture.status='complete'
                   LEFT JOIN world_event_observations observation
                     ON observation.document_version_id=capture.document_version_id
                   WHERE assessment.status='complete'
                   GROUP BY assessment.publisher_key
                   ORDER BY assessment.publisher_key LIMIT ?""", (limit,)
            ).fetchall()
            fusion = connection.execute(
                """SELECT documents.publisher_key,
                          COUNT(*) assessed_observations,
                          SUM(NOT EXISTS (
                            SELECT 1 FROM world_event_fusion_decisions decision
                            WHERE decision.observation_id=observation.id
                              AND decision.method=?)) awaiting_fusion,
                          MIN(CASE WHEN NOT EXISTS (
                            SELECT 1 FROM world_event_fusion_decisions decision
                            WHERE decision.observation_id=observation.id
                              AND decision.method=?)
                            THEN observation.captured_at END) oldest_fusion_at
                   FROM world_event_observations observation
                   JOIN documents ON documents.id=observation.document_id
                   WHERE EXISTS (
                     SELECT 1 FROM article_content_captures capture
                     JOIN article_framing_assessments assessment
                       ON assessment.article_capture_id=capture.id
                     WHERE capture.document_version_id=observation.document_version_id
                       AND capture.status='complete'
                       AND assessment.status='complete')
                   GROUP BY documents.publisher_key
                   ORDER BY documents.publisher_key LIMIT ?""",
                (fusion_method, fusion_method, limit),
            ).fetchall()
            outcomes = connection.execute(
                """SELECT decision.outcome,COUNT(*) count
                   FROM world_event_fusion_decisions decision
                   WHERE decision.method=?
                   GROUP BY decision.outcome ORDER BY decision.outcome""",
                (fusion_method,),
            ).fetchall()
            event_buckets = connection.execute(
                """WITH counts AS (
                     SELECT event.id,COUNT(DISTINCT assessment.publisher_key) publishers
                     FROM world_events event
                     LEFT JOIN world_event_memberships membership
                       ON membership.world_event_id=event.id AND membership.active=1
                     LEFT JOIN world_event_observations observation
                       ON observation.id=membership.observation_id
                     LEFT JOIN article_content_captures capture
                       ON capture.document_version_id=observation.document_version_id
                      AND capture.status='complete'
                     LEFT JOIN article_framing_assessments assessment
                       ON assessment.article_capture_id=capture.id
                      AND assessment.status='complete'
                     WHERE event.status='active' GROUP BY event.id
                   ) SELECT CASE WHEN publishers=0 THEN 'zero'
                                 WHEN publishers=1 THEN 'one' ELSE 'multiple' END bucket,
                            COUNT(*) count FROM counts GROUP BY bucket"""
            ).fetchall()
            gates = connection.execute(
                """WITH stats AS (
                     SELECT event.id,
                       COUNT(DISTINCT documents.publisher_key) member_publishers,
                       COUNT(DISTINCT CASE WHEN capture.status='complete'
                         THEN documents.publisher_key END) captured_publishers,
                       COUNT(DISTINCT CASE WHEN assessment.status='complete'
                         THEN documents.publisher_key END) assessed_publishers,
                       COUNT(DISTINCT CASE WHEN assessment.status='complete'
                           AND COALESCE(sources.last_error,'')=''
                         THEN documents.publisher_key END) healthy_publishers,
                       COUNT(DISTINCT CASE WHEN assessment.status='complete'
                           AND COALESCE(sources.last_error,'')=''
                         THEN COALESCE(NULLIF(documents.reporting_family_key,''),
                           NULLIF(documents.publisher_key,''),documents.source_id)
                         END) independent_families
                     FROM world_events event
                     JOIN world_event_memberships membership
                       ON membership.world_event_id=event.id AND membership.active=1
                     JOIN world_event_observations observation
                       ON observation.id=membership.observation_id
                      AND observation.status='active'
                     JOIN documents ON documents.id=observation.document_id
                     JOIN sources ON sources.id=observation.source_id
                     LEFT JOIN article_content_captures capture
                       ON capture.document_version_id=observation.document_version_id
                     LEFT JOIN article_framing_assessments assessment
                       ON assessment.article_capture_id=capture.id
                     WHERE event.status='active' GROUP BY event.id
                   ) SELECT
                     SUM(member_publishers<2) publisher,
                     SUM(member_publishers>=2 AND captured_publishers<2) capture,
                     SUM(captured_publishers>=2 AND assessed_publishers<2) framing,
                     SUM(assessed_publishers>=2 AND healthy_publishers<2) health,
                     SUM(healthy_publishers>=2 AND independent_families<2) family,
                     SUM(member_publishers>=2 AND
                         1.0*captured_publishers/member_publishers<.8) coverage
                   FROM stats"""
            ).fetchone()
            eligible = connection.execute(
                """SELECT event.id
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
                   WHERE event.status='active' AND COALESCE(sources.last_error,'')=''
                   GROUP BY event.id
                   HAVING COUNT(DISTINCT documents.publisher_key)>=2
                      AND COUNT(DISTINCT COALESCE(
                        NULLIF(documents.reporting_family_key,''),
                        NULLIF(documents.publisher_key,''),documents.source_id))>=2"""
            ).fetchall()
            comparison_count = connection.execute(
                "SELECT COUNT(*) FROM event_publisher_comparisons WHERE method=?",
                (comparison_method,),
            ).fetchone()[0]
            event_ready = connection.execute(
                """SELECT event.id event_id,event.title,
                          MIN(observation.captured_at) oldest_evidence_at,
                          COUNT(DISTINCT documents.publisher_key) member_publishers,
                          COUNT(DISTINCT COALESCE(
                            NULLIF(documents.reporting_family_key,''),
                            NULLIF(documents.publisher_key,''),documents.source_id
                          )) independent_families,
                          COUNT(DISTINCT CASE WHEN capture.status='complete'
                            THEN documents.publisher_key END) captured_publishers,
                          COUNT(DISTINCT CASE WHEN assessment.status='complete'
                            THEN documents.publisher_key END) assessed_publishers,
                          GROUP_CONCAT(DISTINCT documents.publisher_key) member_keys,
                          GROUP_CONCAT(DISTINCT CASE WHEN assessment.status='complete'
                            THEN documents.publisher_key END) assessed_keys,
                          GROUP_CONCAT(DISTINCT CASE WHEN capture.id IS NULL
                            AND (policies.article_acquisition_mode='publisher-page'
                              OR (versions.metadata LIKE
                                '%publisher_feed_full_content%' AND
                                  length(versions.content)>=500))
                            AND COALESCE(sources.last_error,'')=''
                            THEN documents.publisher_key END) acquisition_keys,
                          GROUP_CONCAT(DISTINCT CASE WHEN capture.status='complete'
                            AND capture.word_count>=80
                            AND (assessment.article_capture_id IS NULL OR
                              assessment.input_hash!=capture.content_hash OR
                              (assessment.status='needs-model' AND
                               julianday(assessment.updated_at)<
                                 julianday('now','-6 hours')))
                            THEN documents.publisher_key END) framing_keys,
                          GROUP_CONCAT(DISTINCT CASE WHEN assessment.status='needs-model'
                            AND assessment.input_hash=capture.content_hash
                            AND julianday(assessment.updated_at)>=
                                julianday('now','-6 hours')
                            THEN documents.publisher_key END) cooldown_keys,
                          GROUP_CONCAT(DISTINCT CASE WHEN capture.id IS NULL
                            AND policies.article_acquisition_mode!='publisher-page'
                            AND NOT (versions.metadata LIKE
                              '%publisher_feed_full_content%' AND
                              length(versions.content)>=500)
                            THEN documents.publisher_key END) policy_ineligible_keys,
                          GROUP_CONCAT(DISTINCT CASE WHEN
                            COALESCE(sources.last_error,'')!=''
                            THEN documents.publisher_key END) unhealthy_keys,
                          GROUP_CONCAT(DISTINCT task.status) task_statuses,
                          MAX(task.last_error) latest_task_error,
                          MAX(task.updated_at) latest_task_updated_at
                   FROM world_events event
                   JOIN world_event_memberships membership
                     ON membership.world_event_id=event.id AND membership.active=1
                   JOIN world_event_observations observation
                     ON observation.id=membership.observation_id
                    AND observation.status='active'
                   JOIN documents ON documents.id=observation.document_id
                   JOIN document_versions versions
                     ON versions.id=observation.document_version_id
                   JOIN sources ON sources.id=observation.source_id
                   LEFT JOIN source_policies policies
                     ON policies.source_id=observation.source_id
                   LEFT JOIN article_content_captures capture
                     ON capture.document_version_id=observation.document_version_id
                   LEFT JOIN article_framing_assessments assessment
                     ON assessment.article_capture_id=capture.id
                   LEFT JOIN article_acquisition_tasks task
                     ON task.document_version_id=observation.document_version_id
                    AND task.method='article-acquisition-v1'
                   WHERE event.status='active'
                   GROUP BY event.id
                   HAVING member_publishers>=2 AND independent_families>=2
                   ORDER BY oldest_evidence_at,event.id LIMIT ?""", (limit,)
            ).fetchall()
            event_ready_recent = connection.execute(
                """SELECT
                     (SELECT COUNT(*) FROM article_acquisition_tasks
                      WHERE priority>=2 AND
                        julianday(created_at)>=julianday('now',?)) enqueued,
                     (SELECT COUNT(*) FROM article_acquisition_tasks
                      WHERE priority>=2 AND status='complete' AND
                        julianday(updated_at)>=julianday('now',?)) captured,
                     (SELECT COUNT(DISTINCT assessment.article_capture_id)
                      FROM article_framing_assessments assessment
                      JOIN article_content_captures capture
                        ON capture.id=assessment.article_capture_id
                      JOIN world_event_observations observation
                        ON observation.document_version_id=capture.document_version_id
                      JOIN world_event_memberships membership
                        ON membership.observation_id=observation.id
                       AND membership.active=1
                      WHERE assessment.status='complete' AND
                        julianday(assessment.updated_at)>=julianday('now',?)
                        AND EXISTS (
                          SELECT 1 FROM world_event_memberships peer_membership
                          JOIN world_event_observations peer_observation
                            ON peer_observation.id=peer_membership.observation_id
                          JOIN documents peer_document
                            ON peer_document.id=peer_observation.document_id
                          WHERE peer_membership.world_event_id=
                                membership.world_event_id
                            AND peer_membership.active=1
                          GROUP BY peer_membership.world_event_id
                          HAVING COUNT(DISTINCT peer_document.publisher_key)>=2)
                     ) assessed""",
                tuple(f"-{window_minutes} minutes" for _ in range(3)),
            ).fetchone()
            backlog = connection.execute(
                """SELECT documents.publisher_key,COUNT(*) total,
                          SUM(EXISTS (
                            SELECT 1 FROM article_content_captures capture
                            JOIN article_framing_assessments assessment
                              ON assessment.article_capture_id=capture.id
                            WHERE capture.document_version_id=observation.document_version_id
                              AND capture.status='complete'
                              AND assessment.status='complete')) comparison_ready,
                          MIN(observation.captured_at) oldest_captured_at
                   FROM world_event_observations observation
                   JOIN documents ON documents.id=observation.document_id
                   JOIN sources ON sources.id=observation.source_id
                   WHERE NOT EXISTS (
                     SELECT 1 FROM world_event_fusion_decisions decision
                     WHERE decision.observation_id=observation.id AND decision.method=?)
                     AND sources.kind NOT IN (
                       'private_mail','prediction_market','weather_forecast',
                       'infrastructure_reference')
                   GROUP BY documents.publisher_key
                   ORDER BY oldest_captured_at LIMIT ?""",
                (fusion_method, limit),
            ).fetchall()
            latest_comparisons = connection.execute(
                """SELECT comparison.world_event_id,events.title,
                          comparison.publisher_keys,comparison.source_count,
                          comparison.evidence_cutoff_at,comparison.status,
                          comparison.input_hash,comparison.created_at
                   FROM event_publisher_comparisons comparison
                   JOIN world_events events ON events.id=comparison.world_event_id
                   WHERE comparison.method=?
                   ORDER BY comparison.created_at DESC,comparison.id DESC LIMIT ?""",
                (comparison_method, limit),
            ).fetchall()
            recent = connection.execute(
                """SELECT
                     (SELECT COUNT(*) FROM world_event_observations observation
                      WHERE julianday(observation.created_at)>=julianday('now',?)
                        AND EXISTS (
                          SELECT 1 FROM article_content_captures capture
                          JOIN article_framing_assessments assessment
                            ON assessment.article_capture_id=capture.id
                          WHERE capture.document_version_id=observation.document_version_id
                            AND assessment.status='complete')) projected,
                     (SELECT COUNT(DISTINCT decision.observation_id)
                      FROM world_event_fusion_decisions decision
                      WHERE decision.method=? AND
                        julianday(decision.created_at)>=julianday('now',?)) fused""",
                (f"-{window_minutes} minutes", fusion_method,
                 f"-{window_minutes} minutes"),
            ).fetchone()
            latest = connection.execute(
                """SELECT decision.observation_id,decision.candidate_event_id,
                          decision.chosen_event_id,decision.outcome,decision.score,
                          decision.cutoff_at,decision.feature_version,
                          decision.created_at
                   FROM world_event_fusion_decisions decision
                   WHERE decision.method=?
                   ORDER BY decision.created_at DESC,decision.id DESC LIMIT ?""",
                (fusion_method, limit),
            ).fetchall()
        publisher_rows = [dict(row) for row in publishers]
        waiting_projection = sum(row["awaiting_projection"] or 0
                                 for row in publisher_rows)
        fusion_rows = [dict(row) for row in fusion]
        waiting_fusion = sum(row["awaiting_fusion"] or 0 for row in fusion_rows)
        eligible_count = len(eligible)
        now_value = datetime.now(UTC)
        projection_ages = _timestamp_age_stats(
            [row.get("oldest_projection_at") for row in publisher_rows], now_value
        )
        fusion_ages = _timestamp_age_stats(
            [row.get("oldest_fusion_at") for row in fusion_rows], now_value
        )
        blocked = {key: int(gates[key] or 0) for key in (
            "publisher", "capture", "framing", "health", "family", "coverage"
        )}
        event_rows = []
        event_state_counts = Counter()
        event_ages = []
        for raw in event_ready:
            item = dict(raw)
            assessed_keys = _csv_values(item.pop("assessed_keys", ""))
            item["member_keys"] = _csv_values(item.get("member_keys"))
            item["assessed_keys"] = assessed_keys
            for key in (
                "acquisition_keys", "framing_keys", "cooldown_keys",
                "policy_ineligible_keys", "unhealthy_keys", "task_statuses",
            ):
                item[key] = [value for value in _csv_values(item.get(key))
                             if value not in assessed_keys]
            potential = set(assessed_keys)
            for key in ("acquisition_keys", "framing_keys", "cooldown_keys"):
                potential.update(item[key])
            if item["assessed_publishers"] >= 2:
                state = "comparison-ready"
            elif len(potential) < 2 and item["unhealthy_keys"]:
                state = "source-unhealthy"
            elif len(potential) < 2:
                state = "policy-ineligible"
            elif item["framing_keys"]:
                state = "awaiting-framing"
            elif item["cooldown_keys"]:
                state = "model-cooldown"
            elif item["acquisition_keys"]:
                state = (
                    "awaiting-capture" if any(status in {
                        "pending", "retry", "running"
                    } for status in item["task_statuses"])
                    else "awaiting-enqueue"
                )
            else:
                state = "policy-ineligible"
            item["next_stage"] = state
            event_state_counts[state] += 1
            parsed = _parse_utc(item.get("oldest_evidence_at"))
            if parsed is not None and state not in {
                "comparison-ready", "policy-ineligible"
            }:
                event_ages.append(max(0, (now_value - parsed).total_seconds()))
            event_rows.append(item)
        eligibility_gate = next(
            (f"{key}-gate" for key in (
                "health", "family", "framing", "capture", "publisher"
            ) if blocked[key]),
            "multi-publisher-event",
        )
        actionable_gate = next((f"event-ready-{state}" for state in (
            "awaiting-framing", "model-cooldown", "awaiting-capture",
            "awaiting-enqueue",
        ) if event_state_counts[state]), eligibility_gate)
        gate = (
            "projection-backlog" if waiting_projection else
            "fusion-backlog" if waiting_fusion else
            actionable_gate if not eligible_count else
            "comparison-current" if comparison_count else "comparison-run"
        )
        return {
            "methods": {"fusion": fusion_method,
                        "comparison": comparison_method},
            "publishers": publisher_rows, "fusion_by_publisher": fusion_rows,
            "fusion_outcomes": [dict(row) for row in outcomes],
            "event_assessed_publisher_buckets": [dict(row) for row in event_buckets],
            "blocked_events": blocked,
            "eligible_events": eligible_count,
            "comparisons": int(comparison_count),
            "fusion_backlog": [dict(row) for row in backlog],
            "queue_ages_seconds": {
                "projection": projection_ages, "fusion": fusion_ages,
            },
            "recent_throughput": dict(recent),
            "window_minutes": window_minutes, "current_gate": gate,
            "latest_fusion_decisions": [dict(row) for row in latest],
            "latest_comparisons": [{
                **dict(row),
                "publisher_keys": self._json_load(row["publisher_keys"], []),
            } for row in latest_comparisons],
            "event_ready": {
                "events": event_rows,
                "state_counts": dict(sorted(event_state_counts.items())),
                "queue_age_seconds": {
                    "sample_count": len(event_ages),
                    "oldest": round(max(event_ages), 3) if event_ages else None,
                    "median": _percentile(event_ages, 50),
                },
                "recent_throughput": dict(event_ready_recent),
                "drain_state": (
                    "clear" if not any(state in event_state_counts for state in (
                        "awaiting-enqueue", "awaiting-capture",
                        "awaiting-framing", "model-cooldown"
                    )) else "active"
                ),
            },
        }

    def epistemic_health(self):
        with self._connect() as connection:
            target_status = connection.execute(
                "SELECT target_status,COUNT(*) count FROM verification_targets "
                "GROUP BY target_status ORDER BY count DESC"
            ).fetchall()
            observation_outcomes = connection.execute(
                "SELECT outcome,COUNT(*) count FROM verification_observations "
                "GROUP BY outcome ORDER BY count DESC"
            ).fetchall()
            groundings = connection.execute(
                "SELECT grounding_type,COUNT(*) count FROM claim_groundings "
                "GROUP BY grounding_type ORDER BY count DESC LIMIT 20"
            ).fetchall()
            models = connection.execute(
                "SELECT id,method,sample_count,training_cutoff_at,status,"
                "brier_score,log_loss,created_at,promoted_at "
                "FROM forecast_model_versions ORDER BY created_at DESC LIMIT 10"
            ).fetchall()
            training = connection.execute(
                "SELECT * FROM ensemble_training_runs "
                "ORDER BY id DESC LIMIT 10"
            ).fetchall()
            portfolio = connection.execute(
                "SELECT * FROM forecast_portfolio_state "
                "ORDER BY target_share DESC"
            ).fetchall()
            grounding_state = connection.execute(
                "SELECT * FROM grounding_backfill_state ORDER BY updated_at DESC"
            ).fetchall()
        return {
            "verification_targets": [dict(row) for row in target_status],
            "verification_observations": [dict(row) for row in observation_outcomes],
            "groundings": [dict(row) for row in groundings],
            "grounding_backfills": [dict(row) for row in grounding_state],
            "forecast_portfolio": [dict(row) for row in portfolio],
            "models": [dict(row) for row in models],
            "training_runs": [dict(row) for row in training],
            "calibration": self.forecast_calibration(),
            "evaluations": self.intelligence_evaluations(limit=1)
        }

    def list_publisher_outcomes(self, publisher_key=None, limit=100):
        query = """
            SELECT publisher_outcomes.*, documents.title, documents.url,
                   documents.publisher_label
            FROM publisher_outcomes
            JOIN documents ON documents.id = publisher_outcomes.document_id
        """
        params = []
        if publisher_key:
            query += " WHERE publisher_outcomes.publisher_key = ?"
            params.append(str(publisher_key))
        query += " ORDER BY publisher_outcomes.evaluated_at DESC LIMIT ?"
        params.append(max(1, min(1000, int(limit))))
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        outcomes = []
        for row in rows:
            item = dict(row)
            item["corroborating_publishers"] = self._json_load(
                item.get("corroborating_publishers"), []
            )
            item["evidence_document_ids"] = self._json_load(
                item.get("evidence_document_ids"), []
            )
            item["was_early"] = bool(item.get("was_early"))
            outcomes.append(item)
        return outcomes

    def list_situations(
        self, limit=50, category=None, status=None, located_only=False
    ):
        limit = max(1, min(200, int(limit)))
        query = """
            SELECT situations.*,
                   COUNT(DISTINCT situation_documents.document_id)
                     AS evidence_count,
                   COUNT(DISTINCT COALESCE(
                       NULLIF(documents.reporting_family_key, ''),
                       NULLIF(documents.publisher_key, ''), documents.source_id
                   )) AS source_count,
                   (SELECT COUNT(*) FROM claims
                    WHERE claims.situation_id = situations.id
                      AND claims.status != 'superseded') AS claim_count,
                   (SELECT COUNT(*) FROM claims
                    WHERE claims.situation_id = situations.id
                      AND claims.status = 'contested') AS contested_count
            FROM situations
            LEFT JOIN situation_documents
              ON situation_documents.situation_id = situations.id
            LEFT JOIN documents
              ON documents.id = situation_documents.document_id
        """
        conditions = []
        params = []
        if category:
            conditions.append("situations.category = ?")
            params.append(clean_category(category))
        if status:
            conditions.append("situations.status = ?")
            params.append(str(status).strip().lower())
        if located_only:
            conditions.append(
                "situations.latitude IS NOT NULL "
                "AND situations.longitude IS NOT NULL"
            )
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += """
            GROUP BY situations.id
            ORDER BY situations.status = 'contested' DESC,
                     situations.confidence DESC,
                     situations.updated_at DESC
            LIMIT ?
        """
        params.append(limit)

        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def geography_overview(self, limit=200):
        """Return map-ready situations plus country rollups, all read-only."""
        situations = self.list_situations(limit=limit, located_only=True)
        countries = {}
        for item in situations:
            name = str(item.get("location_country_name") or "").strip()
            if not name:
                continue
            entry = countries.setdefault(name, {
                "country_name": name,
                "country_code": item.get("location_country_code") or "",
                "situations": 0, "active": 0, "contested": 0,
                "average_location_confidence": 0.0
            })
            entry["situations"] += 1
            entry["active"] += int(item.get("status") == "active")
            entry["contested"] += int(item.get("status") == "contested")
            entry["average_location_confidence"] += float(item.get("location_confidence") or 0)
        values = list(countries.values())
        for item in values:
            item["average_location_confidence"] = round(item["average_location_confidence"] / item["situations"], 4)
        values.sort(key=lambda item: (-item["active"], -item["situations"], item["country_name"]))
        return {"situations": situations, "countries": values}

    def replace_aircraft_states(self, states, source_id="opensky"):
        now = utc_now()
        with self._connect() as connection:
            for state in states:
                connection.execute(
                    """INSERT INTO aircraft_states (icao24,callsign,origin_country,latitude,longitude,altitude_m,
                      velocity_mps,heading_degrees,vertical_rate_mps,on_ground,last_contact_at,observed_at,source_id,updated_at)
                      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                      ON CONFLICT(icao24) DO UPDATE SET callsign=excluded.callsign,origin_country=excluded.origin_country,
                      latitude=excluded.latitude,longitude=excluded.longitude,altitude_m=excluded.altitude_m,
                      velocity_mps=excluded.velocity_mps,heading_degrees=excluded.heading_degrees,
                      vertical_rate_mps=excluded.vertical_rate_mps,on_ground=excluded.on_ground,
                      last_contact_at=excluded.last_contact_at,observed_at=excluded.observed_at,source_id=excluded.source_id,updated_at=excluded.updated_at""",
                    (state["icao24"], state.get("callsign", ""), state.get("origin_country", ""), state["latitude"], state["longitude"],
                     state.get("altitude_m"), state.get("velocity_mps"), state.get("heading_degrees"), state.get("vertical_rate_mps"),
                     int(bool(state.get("on_ground"))), state.get("last_contact_at"), state.get("observed_at", now), source_id, now)
                )
            connection.execute("DELETE FROM aircraft_states WHERE julianday(?) - julianday(observed_at) > 0.05", (now,))

    def list_aircraft_states(self, limit=300):
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM aircraft_states WHERE julianday('now')-julianday(observed_at)<=0.05 ORDER BY observed_at DESC LIMIT ?",
                (max(1, min(1000, int(limit))),)
            ).fetchall()
        return [dict(row) for row in rows]

    def map_commentary(self, kind, identifier="", country=""):
        """Produce a cheap, auditable hover readout from the stored worldview."""
        kind = str(kind or "").strip().lower()
        now = utc_now()
        if kind == "feature" and identifier:
            with self._connect() as connection:
                row = connection.execute(
                    """SELECT features.*,sources.name source_name,
                       (SELECT COUNT(*) FROM geo_anomalies anomalies
                        WHERE anomalies.feature_id=features.id AND anomalies.status='active') anomaly_count
                       FROM geo_features features JOIN sources ON sources.id=features.source_id
                       WHERE features.id=?""", (str(identifier)[:100],)
                ).fetchone()
            if not row:
                return {"headline":"Hazard unavailable","commentary":"The observation is no longer active.","updated_at":now}
            item = dict(row)
            commentary = (
                f"{item['source_name']} currently reports this {item['feature_type']} at "
                f"{round(float(item['severity'] or 0)*100)}% normalized severity. "
                f"It has {int(item['anomaly_count'] or 0)} active change signal(s). "
                "Proximity does not establish a causal relationship with nearby situations."
            )
            return {"headline":f"{item['feature_type'].title()} observation",
                    "commentary":commentary,"confidence":float(item["confidence"] or 0),
                    "updated_at":item["updated_at"],"basis":"authoritative-hazard-observation"}
        if kind == "situation" and identifier:
            with self._connect() as connection:
                row = connection.execute(
                    """SELECT situations.*,
                       COUNT(DISTINCT situation_documents.document_id) evidence_count,
                       COUNT(DISTINCT COALESCE(NULLIF(documents.reporting_family_key,''),
                         NULLIF(documents.publisher_key,''),documents.source_id)) source_count
                       FROM situations
                       LEFT JOIN situation_documents ON situation_documents.situation_id=situations.id
                       LEFT JOIN documents ON documents.id=situation_documents.document_id
                       WHERE situations.id=? GROUP BY situations.id""",
                    (str(identifier)[:100],)
                ).fetchone()
            if not row:
                return {"headline": "Situation unavailable", "commentary": "The referenced situation is no longer available.", "updated_at": now}
            item = dict(row)
            place = item.get("location_label") or item.get("location_country_name") or "the reported location"
            worldview = str(item.get("worldview") or "").strip()
            if worldview:
                commentary = worldview[:700]
            else:
                commentary = (
                    f"Entity currently treats this as {item['status']} around {place}, "
                    f"with {item['evidence_count']} evidence record(s) across "
                    f"{item['source_count']} reporting family or source(s)."
                )
            return {
                "headline": item["title"], "commentary": commentary,
                "confidence": round(float(item.get("confidence") or 0), 4),
                "location_confidence": round(float(item.get("location_confidence") or 0), 4),
                "updated_at": item.get("updated_at") or now,
                "basis": "stored-worldview"
            }
        if kind == "country" and country:
            name = str(country).strip()[:120]
            with self._connect() as connection:
                totals = connection.execute(
                    """SELECT COUNT(*) situations,
                       SUM(status='active') active,SUM(status='contested') contested,
                       AVG(confidence) confidence
                       FROM situations WHERE location_country_name=?""",
                    (name,)
                ).fetchone()
                top = connection.execute(
                    """SELECT title,category,status,confidence FROM situations
                       WHERE location_country_name=?
                       ORDER BY status='contested' DESC,confidence DESC,updated_at DESC LIMIT 3""",
                    (name,)
                ).fetchall()
            count = int(totals["situations"] or 0)
            if not count:
                commentary = "Entity has no country-attributed situations in the current geographic evidence set."
            else:
                topics = "; ".join(f"{row['title']} ({row['status']})" for row in top)
                commentary = (
                    f"Entity has {count} country-attributed situation(s): "
                    f"{int(totals['active'] or 0)} active and {int(totals['contested'] or 0)} contested. "
                    f"Highest-priority items: {topics}."
                )
            return {
                "headline": name, "commentary": commentary,
                "confidence": round(float(totals["confidence"] or 0), 4),
                "updated_at": now, "basis": "country-rollup"
            }
        return {"headline": "Map commentary", "commentary": "Hover over a country or situation for Entity's evidence-based readout.", "updated_at": now}

    def list_geo_features(self, bbox=(-180, -90, 180, 90), layers=(),
                          since_at=None, minimum_severity=0.0, limit=1000):
        west, south, east, north = bbox
        query = """SELECT * FROM geo_features WHERE status='active'
                   AND (expires_at IS NULL OR expires_at>=?)
                   AND centroid_latitude BETWEEN ? AND ?
                   AND severity>=?"""
        now = utc_now()
        params = [now, south, north, max(0.0, min(1.0, float(minimum_severity)))]
        if west <= east:
            query += " AND centroid_longitude BETWEEN ? AND ?"
            params.extend([west, east])
        else:
            query += " AND (centroid_longitude>=? OR centroid_longitude<=?)"
            params.extend([west, east])
        clean_layers = tuple(
            str(layer).strip().lower() for layer in layers
            if str(layer).strip().lower() in {
                "earthquake", "wildfire", "flood", "storm", "volcano",
                "drought", "weather"
            }
        )
        if clean_layers:
            query += " AND feature_type IN (%s)" % ",".join("?" for _ in clean_layers)
            params.extend(clean_layers)
        if since_at:
            query += " AND observed_at>=?"
            params.append(str(since_at))
        query += " ORDER BY severity DESC,observed_at DESC LIMIT ?"
        params.append(max(1, min(5000, int(limit))))
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["geometry"] = self._json_load(item.get("geometry"), {})
            item["properties"] = self._json_load(item.get("properties"), {})
            item["authoritative"] = bool(item.get("authoritative"))
            result.append(item)
        return result

    def open_source_enrichment_overview(self):
        with self._connect() as connection:
            totals = connection.execute(
                """SELECT COUNT(*) processed,
                   COALESCE(SUM(status='complete'),0) complete,
                   COALESCE(SUM(status='needs-model'),0) needs_model,
                   COALESCE(SUM(translated_content!=''),0) translated,
                   COALESCE(SUM(location_label!=''),0) grounded_locations,
                   COALESCE(SUM(forward_origin_key!=''),0) attributed_forwards,
                   COALESCE(SUM(extracted_urls!='[]'),0) with_urls
                   FROM document_enrichments"""
            ).fetchone()
            languages = connection.execute(
                """SELECT detected_language language,COUNT(*) count
                   FROM document_enrichments GROUP BY detected_language
                   ORDER BY count DESC,language LIMIT 20"""
            ).fetchall()
            channels = connection.execute(
                """SELECT documents.publisher_key,
                   MAX(documents.publisher_label) publisher_label,
                   COUNT(*) documents,
                   MAX(COALESCE(assessment.effective_credibility,
                                reputation.learned_credibility)) learned_credibility,
                   MAX(COALESCE(assessment.framing_signal,
                                priors.framing_signal)) framing_signal,
                   MAX(priors.affiliation) affiliation,
                   SUM(enrichment.status='needs-model') needs_model,
                   SUM(enrichment.translated_content!='') translated
                   FROM documents
                   LEFT JOIN document_enrichments enrichment
                     ON enrichment.document_id=documents.id
                   LEFT JOIN publisher_reputation reputation
                     ON reputation.publisher_key=documents.publisher_key
                   LEFT JOIN publisher_assessments assessment
                     ON assessment.publisher_key=documents.publisher_key
                    AND assessment.scope_kind='global'
                    AND assessment.scope_value=''
                   LEFT JOIN publisher_profile_priors priors
                     ON priors.publisher_key=documents.publisher_key
                   WHERE documents.source_id='telegram_public'
                   GROUP BY documents.publisher_key
                   ORDER BY documents DESC,publisher_label"""
            ).fetchall()
            state = connection.execute(
                "SELECT * FROM open_source_enrichment_state WHERE lane=?",
                ("public-report-versions-v1",),
            ).fetchone()
        return {
            "totals": dict(totals) if totals else {},
            "languages": [dict(row) for row in languages],
            "channels": [dict(row) for row in channels],
            "state": dict(state) if state else {},
        }

    def list_early_reports(self, limit=50):
        """Return recent public-channel reports with provenance and fusion state."""
        limit = max(1, min(200, int(limit)))
        with self._connect() as connection:
            rows = connection.execute(
                """WITH latest_enrichment AS (
                     SELECT enrichment.*,
                            ROW_NUMBER() OVER (
                              PARTITION BY enrichment.document_id
                              ORDER BY enrichment.document_version_id DESC,
                                       enrichment.id DESC
                            ) AS enrichment_rank
                     FROM document_enrichments enrichment
                   ), latest_observation AS (
                     SELECT observation.*,
                            ROW_NUMBER() OVER (
                              PARTITION BY observation.document_id
                              ORDER BY observation.document_version_id DESC,
                                       observation.created_at DESC
                            ) AS observation_rank
                     FROM world_event_observations observation
                   )
                   SELECT documents.id AS document_id,documents.source_id,
                          documents.publisher_key,documents.publisher_label,
                          documents.title,documents.summary,documents.url,
                          documents.category,documents.published_at,
                          documents.retrieved_at,documents.latitude,
                          documents.longitude,documents.reporting_family_key,
                          enrichment.detected_language,
                          enrichment.translated_title,
                          enrichment.translated_summary,
                          enrichment.enriched_category,
                          enrichment.event_time,enrichment.location_label,
                          enrichment.country_name,enrichment.actors,
                          enrichment.quoted_sources,
                          enrichment.forward_origin_key,
                          enrichment.forward_origin_label,
                          enrichment.media_evidence,
                          enrichment.confidence AS enrichment_confidence,
                          enrichment.status AS enrichment_status,
                          COALESCE(assessment.effective_credibility,
                                   reputation.learned_credibility)
                            AS learned_credibility,
                          COALESCE(assessment.framing_signal,
                                   priors.framing_signal) AS framing_signal,
                          assessment.evidence_estimate,
                          assessment.factual_samples,
                          assessment.maturity_status,
                          priors.affiliation,
                          membership.world_event_id,
                          events.title AS world_event_title,
                          events.confidence AS world_event_confidence,
                          events.source_count AS independent_family_count,
                          events.observation_count AS correlated_report_count
                   FROM documents
                   JOIN sources ON sources.id=documents.source_id
                   LEFT JOIN latest_enrichment enrichment
                     ON enrichment.document_id=documents.id
                    AND enrichment.enrichment_rank=1
                   LEFT JOIN publisher_reputation reputation
                     ON reputation.publisher_key=documents.publisher_key
                   LEFT JOIN publisher_assessments assessment
                     ON assessment.publisher_key=documents.publisher_key
                    AND assessment.scope_kind='global'
                    AND assessment.scope_value=''
                   LEFT JOIN publisher_profile_priors priors
                     ON priors.publisher_key=documents.publisher_key
                   LEFT JOIN latest_observation observation
                     ON observation.document_id=documents.id
                    AND observation.observation_rank=1
                   LEFT JOIN world_event_memberships membership
                     ON membership.observation_id=observation.id
                    AND membership.active=1
                   LEFT JOIN world_events events
                     ON events.id=membership.world_event_id
                   WHERE sources.kind='social_signal'
                   ORDER BY COALESCE(documents.published_at,
                                     documents.retrieved_at) DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
        reports = []
        for row in rows:
            item = dict(row)
            for field in ("actors", "quoted_sources"):
                item[field] = self._json_load(item.get(field), [])
            item["media_evidence"] = self._json_load(
                item.get("media_evidence"), {}
            )
            reports.append(item)
        return reports

    def world_graph_overview(self):
        with self._connect() as connection:
            counts = connection.execute(
                """SELECT
                   (SELECT COUNT(*) FROM world_entities) entities,
                   (SELECT COUNT(*) FROM world_events) events,
                   (SELECT COUNT(*) FROM world_event_observations) observations,
                   (SELECT COUNT(*) FROM world_event_relations) relations,
                   (SELECT COUNT(*) FROM world_event_memberships WHERE active=1)
                    fused_memberships,
                   (SELECT COUNT(*) FROM world_event_fusion_reviews
                    WHERE status='pending') fusion_reviews,
                   (SELECT COUNT(*) FROM world_event_versions) event_versions,
                   (SELECT COUNT(*) FROM infrastructure_assets) infrastructure,
                   (SELECT COUNT(*) FROM weather_forecast_cells
                    WHERE julianday(expires_at)>=julianday('now')) weather_forecasts,
                   (SELECT COUNT(*) FROM world_change_signals WHERE status='active') active_changes,
                   (SELECT COUNT(*) FROM world_alerts WHERE status='pending') pending_alerts"""
            ).fetchone()
            states = connection.execute(
                "SELECT * FROM world_graph_backfill_state ORDER BY lane"
            ).fetchall()
        return {**dict(counts), "backfill": [dict(row) for row in states]}

    def list_weather_forecasts(self, bbox=(-180, -90, 180, 90),
                               valid_at=None, limit=500):
        west, south, east, north = bbox
        target = normalize_timestamp(valid_at) if valid_at else utc_now()
        now = utc_now()
        conditions = ["expires_at>=?", "latitude BETWEEN ? AND ?"]
        params = [now, south, north]
        if west <= east:
            conditions.append("longitude BETWEEN ? AND ?")
        else:
            conditions.append("(longitude>=? OR longitude<=?)")
        params.extend([west, east])
        where = " AND ".join(conditions)
        query = f"""WITH ranked AS (
                   SELECT weather_forecast_cells.*,
                          ROW_NUMBER() OVER (
                            PARTITION BY source_id,external_id
                            ORDER BY ABS(strftime('%s',valid_at)-strftime('%s',?)),
                                     forecast_run_at DESC
                          ) AS forecast_rank
                   FROM weather_forecast_cells
                   WHERE {where}
                 )
                 SELECT ranked.*,sources.name source_name,
                        policies.attribution,policies.license_name,
                        policies.license_url
                 FROM ranked
                 JOIN sources ON sources.id=ranked.source_id
                 LEFT JOIN source_policies policies
                   ON policies.source_id=ranked.source_id
                 WHERE forecast_rank=1
                 ORDER BY valid_at,latitude,longitude LIMIT ?"""
        params = [target, *params, max(1, min(2000, int(limit)))]
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item.pop("forecast_rank", None)
            item["units"] = self._json_load(item.get("units"), {})
            item["properties"] = self._json_load(item.get("properties"), {})
            result.append(item)
        return result

    def list_infrastructure_assets(self, bbox=(-180, -90, 180, 90),
                                   asset_types=(), limit=1000):
        west, south, east, north = bbox
        query = """SELECT assets.*,sources.name source_name,
                          policies.attribution,policies.license_name,
                          policies.license_url
                   FROM infrastructure_assets assets
                   LEFT JOIN sources ON sources.id=assets.source_id
                   LEFT JOIN source_policies policies
                     ON policies.source_id=assets.source_id
                   WHERE assets.status='active'
                     AND assets.latitude BETWEEN ? AND ?"""
        params = [south, north]
        if west <= east:
            query += " AND assets.longitude BETWEEN ? AND ?"
        else:
            query += " AND (assets.longitude>=? OR assets.longitude<=?)"
        params.extend([west, east])
        clean_types = tuple(
            str(value).strip().lower() for value in asset_types
            if str(value).strip().lower() in {"airport", "port"}
        )
        if clean_types:
            query += " AND assets.asset_type IN (%s)" % ",".join(
                "?" for _ in clean_types
            )
            params.extend(clean_types)
        query += " ORDER BY assets.asset_type,assets.name LIMIT ?"
        params.append(max(1, min(5000, int(limit))))
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["geometry"] = self._json_load(item.get("geometry"), {})
            item["identifiers"] = self._json_load(item.get("identifiers"), {})
            item["properties"] = self._json_load(item.get("properties"), {})
            result.append(item)
        return result

    def list_world_events(self, limit=100, status=None, event_type=None,
                          country=None, bbox=None):
        query = """SELECT world_events.*,
                          assessments.assessment_status,
                          assessments.headline AS assessment_headline,
                          assessments.confidence AS assessment_confidence,
                          assessments.independent_family_count
                            AS assessment_family_count,
                          assessments.direct_observation_count,
                          assessments.established_facts,
                          assessments.reported_claims,
                          assessments.disputes,assessments.hypotheses,
                          assessments.unknowns,
                          assessments.evidence_cutoff_at,
                          assessments.epistemic_policy_version,
                          assessments.updated_at AS assessment_updated_at
                   FROM world_events
                   LEFT JOIN world_event_assessments assessments
                     ON assessments.world_event_id=world_events.id"""
        conditions = []
        params = []
        if status:
            conditions.append("world_events.status=?")
            params.append(str(status)[:30])
        else:
            conditions.append("world_events.status!='merged'")
            conditions.append(
                "world_events.id NOT IN (SELECT alias_event_id FROM world_event_aliases "
                "WHERE status='active')"
            )
        if event_type:
            conditions.append("world_events.event_type=?")
            params.append(str(event_type)[:80])
        if country:
            conditions.append("world_events.country_name=?")
            params.append(str(country)[:120])
        if bbox:
            west, south, east, north = bbox
            conditions.append("world_events.latitude BETWEEN ? AND ?")
            params.extend([south, north])
            if west <= east:
                conditions.append("world_events.longitude BETWEEN ? AND ?")
            else:
                conditions.append("(world_events.longitude>=? OR world_events.longitude<=?)")
            params.extend([west, east])
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY world_events.status='contested' DESC," \
                 "world_events.severity DESC," \
                 "COALESCE(assessments.confidence,world_events.confidence) DESC," \
                 "world_events.last_seen_at DESC LIMIT ?"
        params.append(max(1, min(1000, int(limit))))
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["geometry"] = self._json_load(item.get("geometry"), {})
            item["properties"] = self._json_load(item.get("properties"), {})
            for field in (
                "established_facts", "reported_claims", "disputes",
                "hypotheses", "unknowns",
            ):
                item[field] = self._json_load(item.get(field), [])
            output.append(item)
        return output

    def get_world_event(self, event_id):
        with self._connect() as connection:
            requested_event_id = str(event_id)[:100]
            event_id = requested_event_id
            seen_aliases = set()
            alias = None
            while event_id not in seen_aliases:
                seen_aliases.add(event_id)
                row = connection.execute(
                    """SELECT canonical_event_id FROM world_event_aliases
                       WHERE alias_event_id=? AND status='active'""",
                    (event_id,)
                ).fetchone()
                if not row:
                    break
                alias = row
                event_id = row["canonical_event_id"]
            event = connection.execute(
                "SELECT * FROM world_events WHERE id=?", (event_id,)
            ).fetchone()
            if not event:
                return None
            observations = connection.execute(
                """SELECT observations.*,sources.name source_name,
                          documents.title document_title,documents.url
                   FROM world_event_observations observations
                   JOIN sources ON sources.id=observations.source_id
                   JOIN documents ON documents.id=observations.document_id
                   LEFT JOIN world_event_memberships memberships
                     ON memberships.observation_id=observations.id
                    AND memberships.active=1
                   WHERE COALESCE(memberships.world_event_id,
                                  observations.world_event_id)=?
                   ORDER BY observations.captured_at DESC LIMIT 200""",
                (event_id,)
            ).fetchall()
            relations = connection.execute(
                """SELECT * FROM world_event_relations
                   WHERE (subject_kind='event' AND subject_id=?)
                      OR (object_kind='event' AND object_id=?)
                   ORDER BY confidence DESC LIMIT 200""", (event_id,event_id)
            ).fetchall()
            versions = connection.execute(
                """SELECT * FROM world_event_versions WHERE world_event_id=?
                   ORDER BY id DESC LIMIT 100""", (event_id,)
            ).fetchall()
            decisions = connection.execute(
                """SELECT decisions.* FROM world_event_fusion_decisions decisions
                   JOIN world_event_memberships memberships
                     ON memberships.decision_id=decisions.id
                   WHERE memberships.world_event_id=?
                   ORDER BY decisions.created_at DESC LIMIT 200""", (event_id,)
            ).fetchall()
            assessment = connection.execute(
                "SELECT * FROM world_event_assessments WHERE world_event_id=?",
                (event_id,),
            ).fetchone()
            assessment_history = connection.execute(
                """SELECT * FROM world_event_assessment_history
                   WHERE world_event_id=? ORDER BY id DESC LIMIT 50""",
                (event_id,),
            ).fetchall()
        item = dict(event)
        item["geometry"] = self._json_load(item.get("geometry"), {})
        item["properties"] = self._json_load(item.get("properties"), {})
        observation_items = []
        for row in observations:
            value = dict(row)
            value["geometry"] = self._json_load(value.get("geometry"), {})
            value["properties"] = self._json_load(value.get("properties"), {})
            observation_items.append(value)
        relation_items = []
        for row in relations:
            value = dict(row)
            value["evidence"] = self._json_load(value.get("evidence"), [])
            relation_items.append(value)
        version_items = []
        for row in versions:
            value = dict(row)
            value["snapshot"] = self._json_load(value.get("snapshot"), {})
            version_items.append(value)
        decision_items = []
        for row in decisions:
            value = dict(row)
            value["components"] = self._json_load(value.get("components"), {})
            value["vetoes"] = self._json_load(value.get("vetoes"), [])
            decision_items.append(value)
        assessment_fields = (
            "established_facts", "reported_claims", "disputes", "hypotheses",
            "unknowns", "evidence_document_ids",
        )
        assessment_item = dict(assessment) if assessment else None
        if assessment_item:
            for field in assessment_fields:
                assessment_item[field] = self._json_load(
                    assessment_item.get(field), []
                )
        assessment_history_items = []
        for row in assessment_history:
            value = dict(row)
            for field in assessment_fields:
                value[field] = self._json_load(value.get(field), [])
            assessment_history_items.append(value)
        return {"event":item,"observations":observation_items,
                "relations":relation_items,"versions":version_items,
                "fusion_decisions":decision_items,
                "assessment":assessment_item,
                "assessment_history":assessment_history_items,
                "requested_event_id":requested_event_id,
                "resolved_alias":bool(alias)}

    def fusion_overview(self):
        with self._connect() as connection:
            row = connection.execute(
                """SELECT
                   (SELECT COUNT(*) FROM world_event_memberships WHERE active=1)
                     active_memberships,
                   (SELECT COUNT(*) FROM world_event_fusion_decisions) decisions,
                   (SELECT COUNT(*) FROM world_event_fusion_reviews
                    WHERE status='pending') pending_reviews,
                   (SELECT COUNT(*) FROM world_event_aliases
                    WHERE status='active') active_aliases,
                   (SELECT COUNT(*) FROM world_event_versions) versions,
                   (SELECT COUNT(*) FROM world_event_operations
                    WHERE status='applied') applied_operations"""
            ).fetchone()
            states = connection.execute(
                "SELECT * FROM world_event_fusion_state ORDER BY lane"
            ).fetchall()
        return {**dict(row), "backfill": [dict(value) for value in states]}

    def list_fusion_reviews(self, limit=100, status="pending"):
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT reviews.*,documents.title document_title,
                          events.title event_title,sources.name source_name
                   FROM world_event_fusion_reviews reviews
                   JOIN world_event_observations observations
                     ON observations.id=reviews.observation_id
                   JOIN documents ON documents.id=observations.document_id
                   JOIN sources ON sources.id=observations.source_id
                   JOIN world_events events ON events.id=reviews.candidate_event_id
                   WHERE reviews.status=?
                   ORDER BY reviews.score DESC,reviews.created_at DESC LIMIT ?""",
                (str(status)[:30], max(1, min(1000, int(limit))))
            ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["rationale"] = self._json_load(item.get("rationale"), {})
            output.append(item)
        return output

    def list_geo_cells(self, bbox=(-180, -90, 180, 90), layers=(),
                       since_at=None, limit=1000):
        west, south, east, north = bbox
        query = """SELECT * FROM geo_cells WHERE centroid_latitude BETWEEN ? AND ?"""
        params = [south, north]
        if west <= east:
            query += " AND centroid_longitude BETWEEN ? AND ?"
            params.extend([west, east])
        else:
            query += " AND (centroid_longitude>=? OR centroid_longitude<=?)"
            params.extend([west, east])
        clean_layers = tuple(str(item).lower() for item in layers if item)
        if clean_layers:
            query += " AND feature_type IN (%s)" % ",".join("?" for _ in clean_layers)
            params.extend(clean_layers)
        if since_at:
            query += " AND latest_observed_at>=?"
            params.append(str(since_at))
        query += " ORDER BY detection_count DESC,max_severity DESC LIMIT ?"
        params.append(max(1, min(5000, int(limit))))
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def list_geo_anomalies(self, bbox=None, limit=100):
        query = """SELECT anomalies.*,features.feature_type,features.centroid_latitude,
                   features.centroid_longitude FROM geo_anomalies anomalies
                   LEFT JOIN geo_features features ON features.id=anomalies.feature_id
                   WHERE anomalies.status='active'"""
        params = []
        if bbox:
            west, south, east, north = bbox
            query += " AND features.centroid_latitude BETWEEN ? AND ?"
            params.extend([south, north])
            if west <= east:
                query += " AND features.centroid_longitude BETWEEN ? AND ?"
            else:
                query += " AND (features.centroid_longitude>=? OR features.centroid_longitude<=?)"
            params.extend([west, east])
        query += " ORDER BY anomalies.severity DESC,anomalies.last_seen_at DESC LIMIT ?"
        params.append(max(1, min(500, int(limit))))
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["evidence"] = self._json_load(item.get("evidence"), {})
            output.append(item)
        return output

    def regional_assessment(self, bbox, layers=(), since_at=None):
        features = self.list_geo_features(
            bbox=bbox, layers=layers, since_at=since_at, limit=1000
        )
        anomalies = self.list_geo_anomalies(bbox=bbox, limit=50)
        west, south, east, north = bbox
        with self._connect() as connection:
            situations = connection.execute(
                """SELECT id,title,category,status,confidence,latitude,longitude,
                          location_country_name,updated_at
                   FROM situations WHERE latitude BETWEEN ? AND ?
                     AND longitude BETWEEN ? AND ?
                   ORDER BY status='contested' DESC,confidence DESC LIMIT 100""",
                (south,north,west,east)
            ).fetchall() if west <= east else connection.execute(
                """SELECT id,title,category,status,confidence,latitude,longitude,
                          location_country_name,updated_at
                   FROM situations WHERE latitude BETWEEN ? AND ?
                     AND (longitude>=? OR longitude<=?)
                   ORDER BY status='contested' DESC,confidence DESC LIMIT 100""",
                (south,north,west,east)
            ).fetchall()
        type_counts = Counter(item["feature_type"] for item in features)
        countries = Counter(
            item["country_name"] for item in features if item.get("country_name")
        )
        contested = sum(row["status"] == "contested" for row in situations)
        headline = (
            f"{len(features)} native hazard feature(s), {len(situations)} situation(s), "
            f"and {len(anomalies)} active anomaly signal(s) in view"
        )
        hazard_summary = ", ".join(
            f"{count} {kind}" for kind, count in type_counts.most_common()
        ) or "no current native hazards"
        country_summary = ", ".join(name for name, _ in countries.most_common(5)) or "no country attribution"
        assessment = (
            f"Entity observes {hazard_summary}. The region contains {contested} contested "
            f"situation(s). Most represented countries: {country_summary}. "
            "This is a geographic evidence summary, not a claim that nearby events are causally related."
        )
        uncertainties = []
        if any(not item.get("country_name") for item in features):
            uncertainties.append("Some hazards have coordinates but no evidence-backed country attribution.")
        if len(features) >= 1000:
            uncertainties.append("The viewport feature limit was reached; zoom in for a complete local view.")
        if not features:
            uncertainties.append("No native hazard observations matched the selected time and layer filters.")
        evidence = [
            {"feature_id":item["id"],"source_id":item["source_id"],
             "document_id":item["document_id"],"observed_at":item["observed_at"]}
            for item in features[:100]
        ]
        fingerprint = hashlib.sha256(self._json({
            "bbox":bbox,"layers":sorted(layers),"since":since_at,
            "features":[item["id"]+item["observed_at"] for item in features],
            "anomalies":[item["id"] for item in anomalies]
        }).encode()).hexdigest()
        result = {
            "headline":headline,"assessment":assessment,
            "uncertainties":uncertainties,"evidence":evidence,
            "feature_counts":dict(type_counts),"situation_count":len(situations),
            "anomalies":anomalies,"request_fingerprint":fingerprint,
            "method":"deterministic-regional-assessment-v1","created_at":utc_now()
        }
        assessment_id = hashlib.sha256(
            f"regional:{fingerprint}".encode()
        ).hexdigest()
        expires_at = (
            datetime.now(UTC) + timedelta(minutes=15)
        ).isoformat(timespec="seconds").replace("+00:00", "Z")
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO regional_assessments
                   (id,request_fingerprint,bbox,layers,since_at,headline,assessment,
                    uncertainties,evidence,method,created_at,expires_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(request_fingerprint) DO UPDATE SET
                   headline=excluded.headline,assessment=excluded.assessment,
                   uncertainties=excluded.uncertainties,evidence=excluded.evidence,
                   method=excluded.method,created_at=excluded.created_at,
                   expires_at=excluded.expires_at""",
                (assessment_id,fingerprint,self._json(bbox),self._json(sorted(layers)),
                 since_at,headline,assessment,self._json(uncertainties),
                 self._json(evidence),result["method"],result["created_at"],expires_at)
            )
            connection.execute(
                "DELETE FROM regional_assessments WHERE expires_at<?",
                (result["created_at"],)
            )
        return result

    def get_country_profile(self, country):
        country = str(country or "").strip()[:120]
        key = "".join(character for character in country.lower() if character.isalnum())
        with self._connect() as connection:
            profile = connection.execute(
                "SELECT * FROM country_profiles WHERE country_key=? OR country_name=?",
                (key,country)
            ).fetchone()
            if not profile:
                return None
            situations = connection.execute(
                """SELECT id,title,category,status,confidence,updated_at FROM situations
                   WHERE location_country_name=? ORDER BY status='contested' DESC,
                   confidence DESC,updated_at DESC LIMIT 20""", (profile["country_name"],)
            ).fetchall()
            features = connection.execute(
                """SELECT id,feature_type,severity,severity_label,observed_at,source_id
                   FROM geo_features WHERE country_name=? AND status='active'
                   ORDER BY severity DESC,observed_at DESC LIMIT 50""", (profile["country_name"],)
            ).fetchall()
            forecasts = connection.execute(
                """SELECT forecasts.id,forecasts.question,forecasts.probability,forecasts.target_at
                   FROM forecasts JOIN situations ON situations.id=forecasts.situation_id
                   WHERE situations.location_country_name=? AND forecasts.status='active'
                   ORDER BY forecasts.target_at LIMIT 20""", (profile["country_name"],)
            ).fetchall()
        item = dict(profile)
        item["dimensions"] = self._json_load(item.get("dimensions"), {})
        item["coverage_gaps"] = self._json_load(item.get("coverage_gaps"), [])
        return {"profile":item,"situations":[dict(row) for row in situations],
                "features":[dict(row) for row in features],
                "forecasts":[dict(row) for row in forecasts]}

    def add_forecast_geo_snapshot(self, forecast_id, situation_id, cutoff_at,
                                  features, feature_ids, snapshot_hash):
        with self._connect() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO forecast_geo_feature_snapshots
                   (forecast_id,situation_id,evidence_cutoff_at,feature_version,features,
                    feature_ids,snapshot_hash,created_at) VALUES (?,?,?,?,?,?,?,?)""",
                (forecast_id,situation_id,cutoff_at,"geospatial-prediction-v1",
                 self._json(features),self._json(feature_ids),snapshot_hash,utc_now())
            )

    def get_situation(self, situation_id):
        with self._connect() as connection:
            situation = connection.execute(
                "SELECT * FROM situations WHERE id = ?",
                (situation_id,)
            ).fetchone()
            if not situation:
                return None
            documents = connection.execute(
                """
                SELECT documents.*, sources.name AS source_name,
                       sources.kind AS source_kind,
                       sources.credibility AS baseline_credibility,
                       COALESCE(assessments.effective_credibility,
                                publisher_reputation.learned_credibility,
                                sources.credibility) AS source_credibility,
                       profiles.factual_accuracy AS publisher_factual_accuracy,
                       CASE WHEN COALESCE(profiles.factual_samples,0)>=20
                            THEN profiles.framing_signal
                            ELSE COALESCE(priors.framing_signal,
                                          profiles.framing_signal,0) END
                         AS publisher_framing_signal,
                       priors.affiliation AS publisher_affiliation,
                       priors.rationale AS publisher_profile_rationale
                FROM situation_documents
                JOIN documents
                  ON documents.id = situation_documents.document_id
                JOIN sources ON sources.id = documents.source_id
                LEFT JOIN publisher_reputation
                  ON publisher_reputation.publisher_key = documents.publisher_key
                LEFT JOIN publisher_assessments assessments
                  ON assessments.publisher_key=documents.publisher_key
                 AND assessments.scope_kind='global'
                 AND assessments.scope_value=''
                LEFT JOIN publisher_epistemic_profiles profiles
                  ON profiles.publisher_key=documents.publisher_key
                LEFT JOIN publisher_profile_priors priors
                  ON priors.publisher_key=documents.publisher_key
                WHERE situation_documents.situation_id = ?
                ORDER BY COALESCE(documents.published_at,
                                  documents.retrieved_at) DESC
                """,
                (situation_id,)
            ).fetchall()
            claims = connection.execute(
                """
                SELECT claims.*,
                       COUNT(DISTINCT claim_evidence.document_version_id)
                         AS evidence_count,
                       COUNT(DISTINCT COALESCE(
                           NULLIF(documents.reporting_family_key, ''),
                           NULLIF(documents.publisher_key, ''), documents.source_id
                       )) AS source_count
                FROM claims
                LEFT JOIN claim_evidence
                  ON claim_evidence.claim_id = claims.id
                LEFT JOIN document_versions
                  ON document_versions.id = claim_evidence.document_version_id
                LEFT JOIN documents
                  ON documents.id = document_versions.document_id
                WHERE claims.situation_id = ?
                GROUP BY claims.id
                ORDER BY claims.status = 'contested' DESC,
                         claims.predicate, claims.confidence DESC
                """,
                (situation_id,)
            ).fetchall()
            claim_evidence = connection.execute(
                """
                SELECT claim_evidence.claim_id, claim_evidence.stance,
                       claim_evidence.source_weight, claim_evidence.excerpt,
                       claim_evidence.observed_at,
                       document_versions.version AS document_version,
                       documents.id AS document_id,
                       documents.title AS document_title,
                       documents.url, documents.source_id,
                       sources.name AS source_name
                FROM claims
                JOIN claim_evidence
                  ON claim_evidence.claim_id = claims.id
                JOIN document_versions
                  ON document_versions.id = claim_evidence.document_version_id
                JOIN documents ON documents.id = document_versions.document_id
                JOIN sources ON sources.id = documents.source_id
                WHERE claims.situation_id = ?
                ORDER BY claim_evidence.observed_at DESC
                """,
                (situation_id,)
            ).fetchall()
            timeline = connection.execute(
                """
                SELECT version, title, summary, status, confidence,
                       evidence_count, claim_count, contested_count,
                       created_at
                FROM situation_versions
                WHERE situation_id = ? ORDER BY version DESC
                """,
                (situation_id,)
            ).fetchall()
            syntheses = connection.execute(
                """
                SELECT * FROM worldview_syntheses
                WHERE situation_id = ?
                ORDER BY created_at DESC
                LIMIT 10
                """,
                (situation_id,)
            ).fetchall()
            hypotheses = connection.execute(
                """
                SELECT * FROM situation_hypotheses
                WHERE situation_id = ? AND status = 'active'
                ORDER BY probability DESC, updated_at DESC
                """,
                (situation_id,)
            ).fetchall()

        evidence_by_claim = {}
        for evidence in claim_evidence:
            evidence_by_claim.setdefault(evidence["claim_id"], []).append(
                dict(evidence)
            )
        claim_items = []
        for claim in claims:
            item = dict(claim)
            item["evidence"] = evidence_by_claim.get(item["id"], [])
            claim_items.append(item)

        return {
            "situation": dict(situation),
            "documents": [self._document_from_row(row) for row in documents],
            "claims": claim_items,
            "timeline": [dict(row) for row in timeline],
            "worldview_syntheses": [
                self._worldview_synthesis_from_row(row)
                for row in syntheses
            ],
            "hypotheses": [
                {
                    **dict(row),
                    "supporting_claim_ids": self._json_load(row["supporting_claim_ids"], []),
                    "contradicting_claim_ids": self._json_load(row["contradicting_claim_ids"], []),
                    "falsifiers": self._json_load(row["falsifiers"], []),
                    "assumptions": self._json_load(row["assumptions"], []),
                    "open_questions": self._json_load(row["open_questions"], [])
                }
                for row in hypotheses
            ]
        }

    def worldview_syntheses(self, situation_id, limit=10):
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM worldview_syntheses
                WHERE situation_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (situation_id, max(1, min(100, int(limit))))
            ).fetchall()
        return [self._worldview_synthesis_from_row(row) for row in rows]

    def list_reliability_cells(self, publisher_key=None, limit=200):
        query = "SELECT * FROM publisher_reliability_cells"
        params = []
        if publisher_key:
            query += " WHERE publisher_key=?"
            params.append(publisher_key)
        query += " ORDER BY evaluated_count DESC,updated_at DESC LIMIT ?"
        params.append(max(1, min(1000, int(limit))))
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def list_verification_tasks(self, status="pending", limit=100):
        query = "SELECT tasks.*,claims.predicate,claims.object,claims.topic " \
                "FROM claim_verification_tasks tasks JOIN claims ON claims.id=tasks.claim_id"
        params = []
        if status:
            query += " WHERE tasks.status=?"
            params.append(status)
        query += " ORDER BY tasks.priority DESC,tasks.next_attempt_at LIMIT ?"
        params.append(max(1, min(500, int(limit))))
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def list_intelligence_gaps(self, status="open", limit=100):
        query = "SELECT gaps.*,situations.title AS situation_title FROM " \
                "intelligence_gaps gaps JOIN situations ON situations.id=gaps.situation_id"
        params=[]
        if status:
            query += " WHERE gaps.status=?"; params.append(status)
        query += " ORDER BY gaps.priority DESC,gaps.updated_at LIMIT ?"
        params.append(max(1,min(500,int(limit))))
        with self._connect() as connection:
            rows=connection.execute(query,params).fetchall()
        return [dict(row) for row in rows]

    def intelligence_evaluations(self, limit=20):
        with self._connect() as connection:
            runs=connection.execute(
                "SELECT * FROM intelligence_evaluation_runs ORDER BY id DESC LIMIT ?",
                (max(1,min(100,int(limit))),)
            ).fetchall()
            gates=connection.execute(
                "SELECT * FROM intelligence_feature_gates ORDER BY feature"
            ).fetchall()
        return {"runs":[{**dict(row),"metrics":self._json_load(row["metrics"],{})} for row in runs],
                "gates":[dict(row) for row in gates]}

    def feature_gate_status(self, feature, default="shadow"):
        with self._connect() as connection:
            row=connection.execute(
                "SELECT status FROM intelligence_feature_gates WHERE feature=?",
                (feature,)
            ).fetchone()
        return row["status"] if row else default

    def reasoning_overview(self, limit=50):
        with self._connect() as connection:
            counts=connection.execute(
                "SELECT status,COUNT(*) count FROM intelligence_reasoning_jobs GROUP BY status"
            ).fetchall()
            jobs=connection.execute(
                "SELECT * FROM intelligence_reasoning_jobs ORDER BY "
                "status='pending' DESC,priority DESC,created_at LIMIT ?",
                (max(1,min(200,int(limit))),)
            ).fetchall()
            budget=connection.execute(
                "SELECT * FROM intelligence_budget_usage ORDER BY bucket_start DESC LIMIT 10"
            ).fetchall()
            lanes=connection.execute(
                "SELECT lane,status,COUNT(*) count,MIN(created_at) oldest "
                "FROM intelligence_reasoning_jobs GROUP BY lane,status "
                "ORDER BY lane,status"
            ).fetchall()
            lane_budget=connection.execute(
                "SELECT * FROM intelligence_budget_lane_usage "
                "ORDER BY bucket_start DESC,lane LIMIT 30"
            ).fetchall()
        return {"counts":{row["status"]:row["count"] for row in counts},
                "jobs":[dict(row) for row in jobs],
                "budget":[dict(row) for row in budget],
                "lanes":[dict(row) for row in lanes],
                "lane_budget":[dict(row) for row in lane_budget]}

    def add_forecast(self, forecast):
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO forecasts (
                    id, situation_id, question, predicted_outcome, probability,
                    target_at, resolution_criteria, rationale, evidence, model,
                    method, status, created_at,hypothesis_id,forecast_kind,
                    category,horizon_bucket,evidence_cutoff_at,evidence_snapshot_hash,
                    base_rate,base_rate_source,model_probability,ensemble_probability,
                    shadow,generation_job_id,portfolio_slot
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,'active',?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    forecast["id"], forecast["situation_id"], forecast["question"],
                    forecast["predicted_outcome"], forecast["probability"],
                    forecast["target_at"], forecast["resolution_criteria"],
                    forecast.get("rationale", ""), self._json(forecast.get("evidence", [])),
                    forecast.get("model", ""), forecast.get("method", "thinking-forecast-v1"),
                    forecast["created_at"],forecast.get("hypothesis_id"),
                    forecast.get("forecast_kind","freeform"),
                    forecast.get("category","general"),
                    forecast.get("horizon_bucket","unknown"),
                    forecast.get("evidence_cutoff_at"),
                    forecast.get("evidence_snapshot_hash",""),
                    forecast.get("base_rate"),forecast.get("base_rate_source",""),
                    forecast.get("model_probability"),
                    forecast.get("ensemble_probability"),int(bool(forecast.get("shadow"))),
                    forecast.get("generation_job_id"),forecast.get("portfolio_slot","")
                )
            )
            now=forecast["created_at"]
            for component in forecast.get("components",[]):
                connection.execute(
                    "INSERT OR IGNORE INTO forecast_component_predictions VALUES (?,?,?,?,?,?)",
                    (forecast["id"],component["component"],component["probability"],
                     component["weight"],forecast.get("ensemble_method","fixed-log-odds-v1"),now)
                )
            for claim_id in forecast.get("claim_ids",[]):
                connection.execute(
                    "INSERT OR IGNORE INTO forecast_evidence "
                    "(forecast_id,claim_id,document_version_id,role,observed_at,snapshot_hash) "
                    "VALUES (?,?,NULL,'snapshot',?,?)",
                    (forecast["id"],claim_id,now,
                     forecast.get("evidence_snapshot_hash",""))
                )
            if forecast.get("portfolio_slot"):
                connection.execute(
                    "UPDATE forecast_portfolio_state SET generated_count="
                    "generated_count+1,updated_at=? WHERE horizon_bucket=?",
                    (now,forecast["portfolio_slot"])
                )
            if forecast.get("geo_snapshot_hash"):
                connection.execute(
                    """INSERT OR IGNORE INTO forecast_geo_feature_snapshots
                       (forecast_id,situation_id,evidence_cutoff_at,feature_version,
                        features,feature_ids,snapshot_hash,created_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (forecast["id"],forecast["situation_id"],
                     forecast.get("evidence_cutoff_at") or forecast["created_at"],
                     "geospatial-prediction-v1",
                     self._json(forecast.get("geo_feature_values",{})),
                     self._json(forecast.get("geo_feature_ids",[])),
                     forecast["geo_snapshot_hash"],now)
                )

    def list_forecasts(self, limit=50, status=None):
        query = "SELECT forecasts.*, situations.title AS situation_title, situations.category AS situation_category FROM forecasts JOIN situations ON situations.id = forecasts.situation_id"
        params = []
        if status:
            query += " WHERE forecasts.status = ?"
            params.append(str(status).lower())
        query += " ORDER BY CASE forecasts.status WHEN 'active' THEN 0 ELSE 1 END, forecasts.target_at ASC, forecasts.created_at DESC LIMIT ?"
        params.append(max(1, min(200, int(limit))))
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
            ids=[row["id"] for row in rows]
            component_rows=[]
            if ids:
                component_rows=connection.execute(
                    "SELECT * FROM forecast_component_predictions WHERE "
                    "forecast_id IN (%s) ORDER BY forecast_id,component"
                    % ",".join("?" for _ in ids), ids
                ).fetchall()
        components={}
        for row in component_rows:
            components.setdefault(row["forecast_id"],[]).append(dict(row))
        result=[]
        for row in rows:
            item=self._forecast_from_row(row)
            item["components"]=components.get(item["id"],[])
            result.append(item)
        return result

    def due_forecasts(self, now, limit=20):
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM forecasts WHERE status = 'active' AND target_at <= ? "
                "AND (next_resolution_at IS NULL OR next_resolution_at<=?) "
                "ORDER BY target_at LIMIT ?",
                (now, now, max(1, min(100, int(limit))))
            ).fetchall()
        return [self._forecast_from_row(row) for row in rows]

    def active_forecast_situation_ids(self, shadow=False):
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT DISTINCT situation_id FROM forecasts "
                "WHERE status='active' AND shadow=?", (int(bool(shadow)),)
            ).fetchall()
        return {row["situation_id"] for row in rows}

    def resolve_forecast(self, forecast_id, outcome, summary, evidence, now,
                         confidence=0.0, resolver_method=""):
        actual = 1 if outcome == "yes" else 0
        with self._connect() as connection:
            row = connection.execute("SELECT probability FROM forecasts WHERE id = ? AND status = 'active'", (forecast_id,)).fetchone()
            if not row:
                return False
            score = (float(row["probability"]) - actual) ** 2
            connection.execute(
                "UPDATE forecasts SET status = 'resolved', resolved_at = ?, actual_outcome = ?, resolution_summary = ?, resolution_evidence = ?, brier_score = ?, resolution_attempts = resolution_attempts + 1,resolution_confidence=?,resolver_method=?,resolver_version='v1' WHERE id = ?",
                (now, actual, str(summary)[:3000], self._json(evidence), score,
                 float(confidence or 0),str(resolver_method),forecast_id)
            )
            connection.execute(
                "UPDATE forecast_portfolio_state SET resolved_count="
                "resolved_count+1,updated_at=? WHERE horizon_bucket=("
                "SELECT horizon_bucket FROM forecasts WHERE id=?)",
                (now,forecast_id)
            )
        return True

    def note_forecast_unresolved(self, forecast_id):
        with self._connect() as connection:
            row=connection.execute(
                "SELECT resolution_attempts,target_at FROM forecasts "
                "WHERE id=? AND status='active'",(forecast_id,)
            ).fetchone()
            if not row:
                return
            attempts=int(row["resolution_attempts"] or 0)+1
            if attempts>=8:
                connection.execute(
                    "UPDATE forecasts SET status='expired',resolution_attempts=?,"
                    "terminal_reason='Insufficient post-cutoff evidence after eight "
                    "bounded resolution attempts' WHERE id=?",
                    (attempts,forecast_id)
                )
            else:
                connection.execute(
                    "UPDATE forecasts SET resolution_attempts=?,"
                    "next_resolution_at=datetime('now','+6 hours') WHERE id=?",
                    (attempts,forecast_id)
                )

    def record_forecast_resolution_attempt(self, forecast_id, outcome,
                                           confidence, summary, evidence,
                                           snapshot_hash, method):
        document_ids = [item.get("document_id") for item in evidence if item.get("document_id")]
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO forecast_resolution_attempts (
                  forecast_id,outcome,confidence,summary,evidence_document_ids,
                  input_snapshot_hash,method,created_at
                ) VALUES (?,?,?,?,?,?,?,?)
                """,
                (forecast_id,outcome,float(confidence or 0),str(summary)[:3000],
                 self._json(document_ids),str(snapshot_hash),str(method),utc_now())
            )

    def forecast_calibration(self):
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS resolved, AVG(brier_score) AS brier, AVG(actual_outcome) AS base_rate FROM forecasts WHERE status = 'resolved'").fetchone()
            active = connection.execute("SELECT COUNT(*) FROM forecasts WHERE status = 'active'").fetchone()[0]
            active_live = connection.execute(
                "SELECT COUNT(*) FROM forecasts WHERE status='active' AND shadow=0"
            ).fetchone()[0]
            active_shadow = connection.execute(
                "SELECT COUNT(*) FROM forecasts WHERE status='active' AND shadow=1"
            ).fetchone()[0]
            v2 = connection.execute(
                """
                SELECT COUNT(*) resolved,AVG(brier_score) brier
                FROM forecasts
                WHERE status='resolved' AND method='hypothesis-forecast-v2'
                """
            ).fetchone()
            unclear = connection.execute(
                "SELECT COUNT(*) FROM forecast_resolution_attempts WHERE outcome='unclear'"
            ).fetchone()[0]
            v2_unclear = connection.execute(
                """
                SELECT COUNT(*) FROM forecast_resolution_attempts attempts
                JOIN forecasts ON forecasts.id=attempts.forecast_id
                WHERE attempts.outcome='unclear'
                  AND forecasts.method='hypothesis-forecast-v2'
                """
            ).fetchone()[0]
            log_loss = connection.execute(
                """
                SELECT AVG(-(actual_outcome*log(MAX(0.000001,probability))+
                  (1-actual_outcome)*log(MAX(0.000001,1-probability))))
                FROM forecasts WHERE actual_outcome IS NOT NULL
                """
            ).fetchone()[0]
        decided=int(row["resolved"] or 0)
        coverage=decided/max(1,decided+int(unclear or 0))
        v2_decided = int(v2["resolved"] or 0)
        return {"active": active, "active_live": active_live,
                "active_shadow": active_shadow, "resolved": decided,
                "brier_score": row["brier"], "base_rate": row["base_rate"],
                "log_loss": log_loss, "resolution_coverage": coverage,
                "unclear_attempts": unclear,
                "v2_resolved": v2_decided, "v2_brier_score": v2["brier"],
                "v2_resolution_coverage": (
                    v2_decided / max(1, v2_decided + int(v2_unclear or 0))
                ), "v2_unclear_attempts": int(v2_unclear or 0)}

    def latest_briefing(self):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM briefings ORDER BY id DESC LIMIT 1"
            ).fetchone()
        if not row:
            return {
                "period_start": None,
                "period_end": None,
                "situation_count": 0,
                "content": {
                    "headline": "No evidence has been analyzed yet.",
                    "situations": [],
                    "method": "deterministic-v1"
                },
                "created_at": None
            }
        briefing = dict(row)
        briefing["content"] = self._json_load(briefing["content"], {})
        return briefing

    def outbox_since(self, after_id=0, limit=100):
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM intelligence_outbox
                WHERE id > ? ORDER BY id ASC LIMIT ?
                """,
                (max(0, int(after_id)), max(1, min(500, int(limit))))
            ).fetchall()

        return [
            {
                **dict(row),
                "payload": self._json_load(row["payload"], {})
            }
            for row in rows
        ]

    def count_document_versions(self, document_id):
        with self._connect() as connection:
            return connection.execute(
                """
                SELECT COUNT(*) AS count FROM document_versions
                WHERE document_id = ?
                """,
                (document_id,)
            ).fetchone()["count"]

    def _document_from_row(self, row):
        item = dict(row)
        item["metadata"] = self._json_load(item.get("metadata"), {})
        return item

    def _worldview_synthesis_from_row(self, row):
        item = dict(row)
        for field in (
            "implications", "contradictions", "open_questions", "evidence"
        ):
            item[field] = self._json_load(item.get(field), [])
        return item

    def _forecast_from_row(self, row):
        item = dict(row)
        for field in ("evidence", "resolution_evidence"):
            item[field] = self._json_load(item.get(field), [])
        return item

    def _source_from_row(self, row):
        item = dict(row)
        item["enabled"] = bool(item["enabled"])
        return item

    def _json(self, value):
        return json.dumps(value, separators=(",", ":"), default=str)

    def _json_load(self, value, default):
        try:
            return json.loads(value or "")
        except (TypeError, ValueError):
            return default


def canonicalize_url(url):
    url = str(url or "").strip()

    if not url:
        return ""

    try:
        parts = urlsplit(url)
    except ValueError:
        return url

    scheme = parts.scheme.lower() or "https"
    hostname = (parts.hostname or "").lower()
    try:
        port = parts.port
    except ValueError:
        return url
    netloc = hostname

    if port and not (
        (scheme == "http" and port == 80)
        or (scheme == "https" and port == 443)
    ):
        netloc = f"{hostname}:{port}"

    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
        and key.lower() not in TRACKING_QUERY_KEYS
    ]
    path = re.sub(r"/{2,}", "/", parts.path or "/")

    if path != "/":
        path = path.rstrip("/")

    return urlunsplit(
        (scheme, netloc, path, urlencode(sorted(query)), "")
    )


def document_hash(item):
    payload = {
        "title": clean_text(item.title),
        "summary": clean_text(item.summary),
        "content": clean_text(item.content),
        "published_at": normalize_timestamp(item.published_at),
        "category": clean_category(item.category),
        "latitude": item.latitude,
        "longitude": item.longitude,
        "metadata": _stable_metadata(item.metadata or {}),
        "status": _document_status(item.status)
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def clean_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def clean_category(value):
    category = re.sub(r"[^a-z0-9_-]+", "-", str(value or "").lower())
    return category.strip("-") or "general"


def _document_status(value):
    status = str(value or "active").strip().lower()
    return status if status in {"active", "deleted"} else "active"


def _stable_metadata(value):
    if isinstance(value, dict):
        return {
            key: _stable_metadata(item)
            for key, item in value.items()
            if key not in VOLATILE_METADATA_KEYS
        }
    if isinstance(value, list):
        return [_stable_metadata(item) for item in value]
    return value


def publisher_identity(source_id, metadata):
    metadata = metadata or {}
    platform = str(metadata.get("platform") or "").lower()
    if platform == "telegram" and metadata.get("channel_username"):
        username = str(metadata["channel_username"]).strip().lstrip("@").lower()
        return f"telegram:{username}", f"@{username}"
    if platform == "x" and metadata.get("author_username"):
        username = str(metadata["author_username"]).strip().lstrip("@").lower()
        return f"x:{username}", f"@{username}"
    if metadata.get("domain"):
        domain = str(metadata["domain"]).strip().lower()
        return f"domain:{domain}", domain
    return str(source_id), str(source_id)


def normalize_timestamp(value):
    if value is None or value == "":
        return None

    if isinstance(value, (int, float)):
        seconds = float(value)

        if seconds > 10_000_000_000:
            seconds /= 1000

        return datetime.fromtimestamp(seconds, UTC).isoformat(
            timespec="seconds"
        ).replace("+00:00", "Z")

    text = str(value).strip()

    if text.endswith("Z"):
        return text

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return text

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)

    return parsed.astimezone(UTC).isoformat(timespec="seconds").replace(
        "+00:00",
        "Z"
    )


def _parse_utc(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _percentile(values, percentile):
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    index = max(0, min(
        len(ordered) - 1,
        int(((float(percentile) / 100) * len(ordered)) + 0.999999) - 1,
    ))
    return round(ordered[index], 3)


def _timestamp_age_stats(values, now):
    ages = []
    for value in values:
        parsed = _parse_utc(value)
        if parsed is not None:
            ages.append(max(0.0, (now - parsed).total_seconds()))
    return {
        "sample_count": len(ages),
        "oldest": round(max(ages), 3) if ages else None,
        "median": _percentile(ages, 50),
    }


def _csv_values(value):
    return sorted({item for item in str(value or "").split(",") if item})
