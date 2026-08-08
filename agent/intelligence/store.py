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
    def __init__(self, path=DEFAULT_DB, migrations=MIGRATIONS):
        self.path = Path(path)
        self.migrations = Path(migrations)
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
                    policy_version,reviewed_at,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                   reviewed_at=excluded.reviewed_at,updated_at=excluded.updated_at""",
                (source_id,snapshot["access_class"],snapshot["authority_class"],
                 snapshot["evidence_role"],snapshot["license_name"],
                 snapshot["license_url"],snapshot["attribution"],
                 snapshot["usage_scope"],int(snapshot["credentials_required"]),
                 snapshot["geographic_coverage"],snapshot["expected_latency"],
                 snapshot["independence_family"],self._json(snapshot["allowed_hosts"]),
                 self._json(snapshot["caveats"]),snapshot["retention_days"],
                 snapshot["policy_version"],snapshot["reviewed_at"],now,now)
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
            item["caveats"] = self._json_load(item.get("caveats"), [])
            item["credentials_required"] = bool(item["credentials_required"])
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
            document_id = str(uuid4())
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
                       profiles.factual_accuracy,
                       profiles.attribution_quality,
                       profiles.revision_discipline,
                       profiles.independence_confidence,
                       profiles.framing_signal,
                       profiles.factual_samples,
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
                LEFT JOIN publisher_epistemic_profiles profiles
                  ON profiles.publisher_key=publisher_reputation.publisher_key
                ORDER BY evaluated_count DESC, learned_credibility DESC,
                         publisher_label
                LIMIT ?
                """,
                (max(1, min(1000, int(limit))),)
            ).fetchall()
        return [dict(row) for row in rows]

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

    def world_graph_overview(self):
        with self._connect() as connection:
            counts = connection.execute(
                """SELECT
                   (SELECT COUNT(*) FROM world_entities) entities,
                   (SELECT COUNT(*) FROM world_events) events,
                   (SELECT COUNT(*) FROM world_event_observations) observations,
                   (SELECT COUNT(*) FROM world_event_relations) relations,
                   (SELECT COUNT(*) FROM infrastructure_assets) infrastructure,
                   (SELECT COUNT(*) FROM world_change_signals WHERE status='active') active_changes,
                   (SELECT COUNT(*) FROM world_alerts WHERE status='pending') pending_alerts"""
            ).fetchone()
            states = connection.execute(
                "SELECT * FROM world_graph_backfill_state ORDER BY lane"
            ).fetchall()
        return {**dict(counts), "backfill": [dict(row) for row in states]}

    def list_world_events(self, limit=100, status=None, event_type=None,
                          country=None, bbox=None):
        query = "SELECT * FROM world_events"
        conditions = []
        params = []
        if status:
            conditions.append("status=?")
            params.append(str(status)[:30])
        if event_type:
            conditions.append("event_type=?")
            params.append(str(event_type)[:80])
        if country:
            conditions.append("country_name=?")
            params.append(str(country)[:120])
        if bbox:
            west, south, east, north = bbox
            conditions.append("latitude BETWEEN ? AND ?")
            params.extend([south, north])
            if west <= east:
                conditions.append("longitude BETWEEN ? AND ?")
            else:
                conditions.append("(longitude>=? OR longitude<=?)")
            params.extend([west, east])
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY status='contested' DESC,severity DESC,confidence DESC,last_seen_at DESC LIMIT ?"
        params.append(max(1, min(1000, int(limit))))
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["geometry"] = self._json_load(item.get("geometry"), {})
            item["properties"] = self._json_load(item.get("properties"), {})
            output.append(item)
        return output

    def get_world_event(self, event_id):
        with self._connect() as connection:
            event = connection.execute(
                "SELECT * FROM world_events WHERE id=?", (str(event_id)[:100],)
            ).fetchone()
            if not event:
                return None
            observations = connection.execute(
                """SELECT observations.*,sources.name source_name,
                          documents.title document_title,documents.url
                   FROM world_event_observations observations
                   JOIN sources ON sources.id=observations.source_id
                   JOIN documents ON documents.id=observations.document_id
                   WHERE observations.world_event_id=?
                   ORDER BY observations.captured_at DESC LIMIT 200""",
                (event_id,)
            ).fetchall()
            relations = connection.execute(
                """SELECT * FROM world_event_relations
                   WHERE (subject_kind='event' AND subject_id=?)
                      OR (object_kind='event' AND object_id=?)
                   ORDER BY confidence DESC LIMIT 200""", (event_id,event_id)
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
        return {"event":item,"observations":observation_items,
                "relations":relation_items}

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
                       COALESCE(publisher_reputation.learned_credibility,
                                sources.credibility) AS source_credibility
                FROM situation_documents
                JOIN documents
                  ON documents.id = situation_documents.document_id
                JOIN sources ON sources.id = documents.source_id
                LEFT JOIN publisher_reputation
                  ON publisher_reputation.publisher_key = documents.publisher_key
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
