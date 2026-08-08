"""Turns concrete gaps and checks into allowlisted read-only source repolls."""

from agent.intelligence.reasoning_jobs import ReasoningJobQueue
from agent.intelligence.store import utc_now


ALLOWLIST={
    "usgs":"usgs_earthquakes", "nws-alerts":"nws_alerts",
    "cisa-kev":"cisa_known_exploited_vulnerabilities",
    "github-advisories":"github_security_advisories",
    "who-outbreaks":"who_outbreaks", "gdacs":"gdacs",
    "eonet":"nasa_eonet", "reliefweb":"reliefweb",
    "world-bank":"world_bank_indicators",
    "fred":"fred_economic_indicators", "firms":"nasa_firms_wildfires"
}

TOPIC_ROUTES = {
    "earthquake": "usgs", "seismic": "usgs",
    "weather": "nws-alerts", "weather-alert": "nws-alerts",
    "cybersecurity": "cisa-kev", "cyber": "cisa-kev",
    "public-health": "who-outbreaks", "health": "who-outbreaks",
    "wildfire": "firms", "fire": "firms",
    "economics": "world-bank", "economic-indicator": "world-bank",
    "humanitarian": "reliefweb", "disaster": "gdacs",
    "natural-disaster": "gdacs"
}


class ActiveAcquisitionEngine:
    method="allowlisted-gap-acquisition-v1"
    def __init__(self,store,enabled=False,max_per_cycle=5,queue=None):
        self.store=store; self.enabled=bool(enabled); self.max_per_cycle=max(1,min(20,int(max_per_cycle))); self.queue=queue or ReasoningJobQueue(store)

    def _adapter(self, desired_source_kind, topic="", predicate=""):
        desired = str(desired_source_kind or "").strip().lower()
        if desired not in ALLOWLIST:
            desired = TOPIC_ROUTES.get(str(topic or "").strip().lower(), "")
        if not desired and str(predicate or "").startswith("seismic."):
            desired = "usgs"
        if not desired and str(predicate or "").startswith("event.alert"):
            desired = TOPIC_ROUTES.get(str(topic or "").strip().lower(), "gdacs")
        return ALLOWLIST.get(desired)

    def enqueue_gaps(self):
        if not self.enabled: return 0
        created=0
        with self.store._connect() as c:
            rows=c.execute("""
              SELECT gaps.*,situations.category
              FROM intelligence_gaps gaps
              JOIN situations ON situations.id=gaps.situation_id
              WHERE gaps.status='open'
              ORDER BY (gaps.desired_source_kind!='independent-public') DESC,
                       gaps.priority DESC,gaps.created_at LIMIT ?
            """,(self.max_per_cycle * 20,)).fetchall()
        for row in rows:
            if created >= self.max_per_cycle:
                break
            adapter=self._adapter(row["desired_source_kind"],row["category"],row["target_predicate"])
            if not adapter: continue
            created += int(self.queue.enqueue("active_acquisition","gap",row["id"],f"gap:{row['id']}:{adapter}",row["priority"]))
        return created

    def enqueue_verifications(self):
        if not self.enabled: return 0
        created=0
        with self.store._connect() as c:
            rows=c.execute("""
              SELECT tasks.*,claims.topic,claims.predicate
              FROM claim_verification_tasks tasks
              JOIN claims ON claims.id=tasks.claim_id
              WHERE tasks.status='pending'
              ORDER BY (tasks.desired_source_kind!='independent-public') DESC,
                       tasks.priority DESC,tasks.created_at LIMIT ?
            """,(self.max_per_cycle * 20,)).fetchall()
        for row in rows:
            if created >= self.max_per_cycle:
                break
            adapter=self._adapter(
                row["desired_source_kind"],row["topic"],row["predicate"]
            )
            if not adapter: continue
            dedupe=(
                f"verification:{row['id']}:{adapter}:"
                f"attempt-{int(row['attempt_count'] or 0)}"
            )
            created += int(self.queue.enqueue(
                "active_acquisition","verification_task",str(row["id"]),
                dedupe,row["priority"]
            ))
        return created

    def dispatch_one(self):
        if not self.enabled: return None
        job=self.queue.lease(["active_acquisition"])
        if not job: return None
        try:
            with self.store._connect() as c:
                gap = None
                task = None
                if job["subject_type"] == "gap":
                    gap=c.execute("""
                      SELECT gaps.*,situations.category
                      FROM intelligence_gaps gaps
                      JOIN situations ON situations.id=gaps.situation_id
                      WHERE gaps.id=?
                    """,(job["subject_id"],)).fetchone()
                    adapter=self._adapter(
                        gap["desired_source_kind"],gap["category"],
                        gap["target_predicate"]
                    ) if gap else None
                elif job["subject_type"] == "verification_task":
                    task=c.execute("""
                      SELECT tasks.*,claims.topic,claims.predicate
                      FROM claim_verification_tasks tasks
                      JOIN claims ON claims.id=tasks.claim_id
                      WHERE tasks.id=?
                    """,(job["subject_id"],)).fetchone()
                    adapter=self._adapter(
                        task["desired_source_kind"],task["topic"],
                        task["predicate"]
                    ) if task else None
                else:
                    adapter=None
                source=c.execute("SELECT id FROM sources WHERE id=? AND enabled=1",(adapter,)).fetchone() if adapter else None
                if not source:
                    raise ValueError("No enabled allowlisted adapter for this gap")
                c.execute("UPDATE source_cursors SET last_polled_at=NULL,updated_at=? WHERE source_id=?",(utc_now(),adapter))
                details={"source_id":adapter,"subject_type":job["subject_type"]}
                if gap:
                    c.execute("UPDATE intelligence_gaps SET status='requested',updated_at=? WHERE id=?",(utc_now(),gap["id"]))
                    c.execute("INSERT INTO active_acquisition_attempts (gap_id,job_id,adapter,outcome,details,created_at) VALUES (?,?,?,'scheduled',?,?)",(gap["id"],job["id"],adapter,self.store._json(details),utc_now()))
                else:
                    c.execute("INSERT INTO verification_acquisition_attempts (verification_task_id,job_id,adapter,outcome,details,created_at) VALUES (?,?,?,'scheduled',?,?)",(task["id"],job["id"],adapter,self.store._json(details),utc_now()))
            self.queue.complete(job["id"],{"adapter":adapter,"outcome":"scheduled","subject_type":job["subject_type"]})
            return adapter
        except Exception as exc:
            self.queue.fail(job["id"],exc); return None
