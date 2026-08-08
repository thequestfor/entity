"""Creates bounded verification work from unresolved, checkable claims."""

from datetime import UTC, datetime, timedelta

from agent.intelligence.store import utc_now


SOURCE_KIND_BY_TOPIC = {
    "earthquake": "usgs", "weather": "nws-alerts",
    "cybersecurity": "cisa-kev", "public-health": "who-outbreaks",
    "wildfire": "firms", "economics": "world-bank"
}


class VerificationPlanner:
    method = "verification-planner-v1"

    def __init__(self, store, batch_size=50):
        self.store = store
        self.batch_size = max(1, min(200, int(batch_size)))

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
        connection.execute(
            "UPDATE claim_verification_tasks SET status='pending', "
            "attempt_count=?, next_attempt_at=?, last_error=?, updated_at=? "
            "WHERE id=?",
            (attempts, next_at, str(error)[:500], utc_now(), task_id)
        )
