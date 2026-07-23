import hashlib
import json
import re
import sqlite3
from datetime import UTC, datetime
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
        connection = sqlite3.connect(self.path, timeout=30)
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
                     WHERE status = 'contested') AS contested_claims
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

        return {
            **dict(counts),
            "latest_retrieved_at": latest,
            "categories": [dict(row) for row in categories]
        }

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
                SELECT * FROM publisher_reputation
                ORDER BY evaluated_count DESC, learned_credibility DESC,
                         publisher_label
                LIMIT ?
                """,
                (max(1, min(1000, int(limit))),)
            ).fetchall()
        return [dict(row) for row in rows]

    def list_situations(self, limit=50, category=None, status=None):
        limit = max(1, min(200, int(limit)))
        query = """
            SELECT situations.*,
                   COUNT(DISTINCT situation_documents.document_id)
                     AS evidence_count,
                   COUNT(DISTINCT documents.publisher_key) AS source_count,
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
                       sources.credibility AS source_credibility
                FROM situation_documents
                JOIN documents
                  ON documents.id = situation_documents.document_id
                JOIN sources ON sources.id = documents.source_id
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
                       COUNT(DISTINCT documents.publisher_key) AS source_count
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

    def add_forecast(self, forecast):
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO forecasts (
                    id, situation_id, question, predicted_outcome, probability,
                    target_at, resolution_criteria, rationale, evidence, model,
                    method, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
                """,
                (
                    forecast["id"], forecast["situation_id"], forecast["question"],
                    forecast["predicted_outcome"], forecast["probability"],
                    forecast["target_at"], forecast["resolution_criteria"],
                    forecast.get("rationale", ""), self._json(forecast.get("evidence", [])),
                    forecast.get("model", ""), forecast.get("method", "thinking-forecast-v1"),
                    forecast["created_at"]
                )
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
        return [self._forecast_from_row(row) for row in rows]

    def due_forecasts(self, now, limit=20):
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM forecasts WHERE status = 'active' AND target_at <= ? ORDER BY target_at LIMIT ?",
                (now, max(1, min(100, int(limit))))
            ).fetchall()
        return [self._forecast_from_row(row) for row in rows]

    def active_forecast_situation_ids(self):
        with self._connect() as connection:
            rows = connection.execute("SELECT DISTINCT situation_id FROM forecasts WHERE status = 'active'").fetchall()
        return {row["situation_id"] for row in rows}

    def resolve_forecast(self, forecast_id, outcome, summary, evidence, now):
        actual = 1 if outcome == "yes" else 0
        with self._connect() as connection:
            row = connection.execute("SELECT probability FROM forecasts WHERE id = ? AND status = 'active'", (forecast_id,)).fetchone()
            if not row:
                return False
            score = (float(row["probability"]) - actual) ** 2
            connection.execute(
                "UPDATE forecasts SET status = 'resolved', resolved_at = ?, actual_outcome = ?, resolution_summary = ?, resolution_evidence = ?, brier_score = ?, resolution_attempts = resolution_attempts + 1 WHERE id = ?",
                (now, actual, str(summary)[:3000], self._json(evidence), score, forecast_id)
            )
        return True

    def note_forecast_unresolved(self, forecast_id):
        with self._connect() as connection:
            connection.execute("UPDATE forecasts SET resolution_attempts = resolution_attempts + 1 WHERE id = ? AND status = 'active'", (forecast_id,))

    def forecast_calibration(self):
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS resolved, AVG(brier_score) AS brier, AVG(actual_outcome) AS base_rate FROM forecasts WHERE status = 'resolved'").fetchone()
            active = connection.execute("SELECT COUNT(*) FROM forecasts WHERE status = 'active'").fetchone()[0]
        return {"active": active, "resolved": row["resolved"], "brier_score": row["brier"], "base_rate": row["base_rate"]}

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
