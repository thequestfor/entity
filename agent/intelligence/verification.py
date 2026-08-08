"""Plans and executes bounded checks against already-ingested public evidence."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from agent.intelligence.store import utc_now


SOURCE_KIND_BY_TOPIC = {
    "earthquake": "usgs", "seismic": "usgs",
    "weather": "nws-alerts", "weather-alert": "nws-alerts",
    "cybersecurity": "cisa-kev", "cyber": "cisa-kev",
    "public-health": "who-outbreaks", "health": "who-outbreaks",
    "wildfire": "firms", "economics": "world-bank",
    "economic-indicator": "world-bank", "humanitarian": "reliefweb",
    "disaster": "gdacs", "natural-disaster": "gdacs"
}

SOURCE_IDS_BY_KIND = {
    "usgs": {"usgs_earthquakes"},
    "nws-alerts": {"nws_alerts"},
    "cisa-kev": {"cisa_known_exploited_vulnerabilities"},
    "github-advisories": {"github_security_advisories"},
    "who-outbreaks": {"who_outbreaks"},
    "gdacs": {"gdacs"},
    "eonet": {"nasa_eonet"},
    "reliefweb": {"reliefweb"},
    "world-bank": {"world_bank_indicators"},
    "fred": {"fred_economic_indicators"},
    "firms": {"nasa_firms_wildfires"},
}

AUTHORITATIVE_SOURCE_IDS = set().union(*SOURCE_IDS_BY_KIND.values())
EXCLUDED_SOURCE_KINDS = {"private_mail", "prediction_market"}


@dataclass(frozen=True)
class VerificationExecutionResult:
    tasks_examined: int = 0
    results_recorded: int = 0
    tasks_postponed: int = 0


class VerificationPlanner:
    method = "verification-planner-v1"

    def __init__(self, store, batch_size=50, max_attempts=8):
        self.store = store
        self.batch_size = max(1, min(200, int(batch_size)))
        self.max_attempts = max(1, min(20, int(max_attempts)))

    def plan(self, connection, claim_ids):
        now = utc_now()
        created = 0
        for claim_id in list(dict.fromkeys(claim_ids))[:self.batch_size]:
            claim = connection.execute(
                "SELECT * FROM claims WHERE id = ?", (claim_id,)
            ).fetchone()
            if not claim or claim["verifiability"] != "checkable":
                continue
            if claim["truth_status"] in {"corroborated", "refuted"}:
                continue
            topic = str(claim["topic"] or "general")
            desired = SOURCE_KIND_BY_TOPIC.get(topic, "independent-public")
            key = f"{claim_id}:{desired}:{self.method}"
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO claim_verification_tasks (
                  claim_id, desired_source_kind, priority, status,
                  next_attempt_at, dedupe_key, created_at, updated_at
                ) VALUES (?, ?, ?, 'pending', ?, ?, ?, ?)
                """,
                (
                    claim_id, desired,
                    min(1.0, 0.4 + float(claim["core_importance"] or 0.5) * 0.5),
                    now, key, now, now
                )
            )
            created += int(cursor.rowcount > 0)
        return created

    def postpone(self, connection, task_id, error="No decisive evidence yet"):
        row = connection.execute(
            "SELECT attempt_count FROM claim_verification_tasks WHERE id = ?",
            (task_id,)
        ).fetchone()
        attempts = int(row["attempt_count"] or 0) + 1 if row else 1
        delay = min(168, 6 * (2 ** min(attempts - 1, 5)))
        next_at = (datetime.now(UTC) + timedelta(hours=delay)).isoformat(
            timespec="seconds"
        ).replace("+00:00", "Z")
        status = "deferred" if attempts >= self.max_attempts else "pending"
        connection.execute(
            "UPDATE claim_verification_tasks SET status=?, "
            "attempt_count=?, next_attempt_at=?, last_error=?, updated_at=? "
            "WHERE id=?",
            (status, attempts, next_at, str(error)[:500], utc_now(), task_id)
        )


class VerificationEngine:
    """Materialize decisive checks without performing arbitrary web requests.

    Source-specific tasks only accept evidence from the configured authoritative
    connector. Generic tasks require two independent public reporting families,
    or one allowlisted authoritative connector. Missing evidence is retried with
    exponential backoff and can separately trigger an allowlisted source repoll.
    """

    method = "deterministic-verification-v1"

    def __init__(self, store, enabled=True, batch_size=20, max_attempts=8):
        self.store = store
        self.enabled = bool(enabled)
        self.batch_size = max(1, min(100, int(batch_size)))
        self.planner = VerificationPlanner(
            store, batch_size=batch_size, max_attempts=max_attempts
        )

    def run_batch(self):
        if not self.enabled:
            return VerificationExecutionResult()
        with self.store._connect() as connection:
            tasks = connection.execute(
                """
                SELECT tasks.*, claims.situation_id
                FROM claim_verification_tasks tasks
                JOIN claims ON claims.id=tasks.claim_id
                WHERE tasks.status='pending' AND tasks.next_attempt_at<=?
                ORDER BY tasks.priority DESC,tasks.created_at
                LIMIT ?
                """,
                (utc_now(), self.batch_size)
            ).fetchall()
        recorded = postponed = 0
        for task in tasks:
            with self.store._connect() as connection:
                decision = self._decide(connection, task)
                if decision is None:
                    self.planner.postpone(connection, task["id"])
                    postponed += 1
                    continue
                now = utc_now()
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO claim_verification_results (
                      task_id,claim_id,result,confidence,authority_level,
                      document_version_id,reason,method,created_at
                    ) VALUES (?,?,?,?,?,?,?,?,?)
                    """,
                    (task["id"], task["claim_id"], decision["result"],
                     decision["confidence"], decision["authority_level"],
                     decision.get("document_version_id"), decision["reason"],
                     self.method, now)
                )
                connection.execute(
                    "UPDATE claim_verification_tasks SET status='completed',"
                    "attempt_count=attempt_count+1,last_error='',updated_at=? "
                    "WHERE id=?",
                    (now, task["id"])
                )
                recorded += int(cursor.rowcount > 0)
        return VerificationExecutionResult(len(tasks), recorded, postponed)

    def _decide(self, connection, task):
        support = self._claim_evidence(connection, task["claim_id"])
        contrary = self._contrary_evidence(connection, task["claim_id"])
        requested = str(task["desired_source_kind"] or "independent-public")
        support_signal = self._signal(support, requested)
        contrary_signal = self._signal(contrary, requested)
        if not support_signal and not contrary_signal:
            return None
        if support_signal and contrary_signal:
            difference = support_signal["confidence"] - contrary_signal["confidence"]
            if abs(difference) < 0.15:
                chosen = max(support_signal, contrary_signal,
                             key=lambda item: item["confidence"])
                return {
                    **chosen, "result": "mixed",
                    "confidence": round(min(chosen["confidence"], 0.65), 4),
                    "reason": "Requested evidence supports incompatible claim values."
                }
            signal = support_signal if difference > 0 else contrary_signal
            result = "supports" if difference > 0 else "refutes"
        elif support_signal:
            signal, result = support_signal, "supports"
        else:
            signal, result = contrary_signal, "refutes"
        return {
            **signal, "result": result,
            "reason": (
                "Matched an allowlisted authoritative source."
                if signal["authority_level"] == "primary"
                else "Matched at least two independent public reporting families."
            )
        }

    def _claim_evidence(self, connection, claim_id):
        return connection.execute(
            """
            SELECT evidence.document_version_id,documents.id AS document_id,
              documents.source_id,documents.publisher_key,
              COALESCE(NULLIF(documents.reporting_family_key,''),
                       NULLIF(documents.publisher_key,''),documents.source_id)
                AS family_key,
              sources.kind AS source_kind,sources.credibility
            FROM claim_evidence evidence
            JOIN document_versions versions
              ON versions.id=evidence.document_version_id
            JOIN documents ON documents.id=versions.document_id
            JOIN sources ON sources.id=documents.source_id
            WHERE evidence.claim_id=? AND evidence.stance='supports'
              AND sources.kind NOT IN ('private_mail','prediction_market')
            ORDER BY evidence.observed_at DESC
            """, (claim_id,)
        ).fetchall()

    def _contrary_evidence(self, connection, claim_id):
        return connection.execute(
            """
            SELECT evidence.document_version_id,documents.id AS document_id,
              documents.source_id,documents.publisher_key,
              COALESCE(NULLIF(documents.reporting_family_key,''),
                       NULLIF(documents.publisher_key,''),documents.source_id)
                AS family_key,
              sources.kind AS source_kind,sources.credibility
            FROM claim_relations relations
            JOIN claim_evidence evidence ON evidence.claim_id=(
              CASE WHEN relations.left_claim_id=? THEN relations.right_claim_id
                   ELSE relations.left_claim_id END
            )
            JOIN document_versions versions
              ON versions.id=evidence.document_version_id
            JOIN documents ON documents.id=versions.document_id
            JOIN sources ON sources.id=documents.source_id
            WHERE relations.relationship='contradicts'
              AND (relations.left_claim_id=? OR relations.right_claim_id=?)
              AND evidence.stance='supports'
              AND sources.kind NOT IN ('private_mail','prediction_market')
            ORDER BY evidence.observed_at DESC
            """, (claim_id, claim_id, claim_id)
        ).fetchall()

    def _signal(self, evidence, requested):
        if not evidence:
            return None
        requested_ids = SOURCE_IDS_BY_KIND.get(requested)
        if requested_ids:
            matches = [row for row in evidence if row["source_id"] in requested_ids]
            if not matches:
                return None
            best = max(matches, key=lambda row: float(row["credibility"] or 0))
            return {
                "confidence": round(max(.8, min(.99, float(best["credibility"]))), 4),
                "authority_level": "primary",
                "document_version_id": best["document_version_id"]
            }
        authoritative = [
            row for row in evidence if row["source_id"] in AUTHORITATIVE_SOURCE_IDS
        ]
        if authoritative:
            best = max(authoritative,
                       key=lambda row: float(row["credibility"] or 0))
            return {
                "confidence": round(max(.8, min(.99, float(best["credibility"]))), 4),
                "authority_level": "primary",
                "document_version_id": best["document_version_id"]
            }
        families = {}
        for row in evidence:
            families.setdefault(row["family_key"], row)
        if len(families) < 2:
            return None
        best = max(families.values(),
                   key=lambda row: float(row["credibility"] or 0))
        confidence = min(.9, .65 + .08 * len(families))
        return {
            "confidence": round(confidence, 4),
            "authority_level": "secondary",
            "document_version_id": best["document_version_id"]
        }
