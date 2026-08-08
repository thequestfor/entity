"""Turns information gaps into allowlisted read-only source repolls."""

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


class ActiveAcquisitionEngine:
    method="allowlisted-gap-acquisition-v1"
    def __init__(self,store,enabled=False,max_per_cycle=5,queue=None):
        self.store=store; self.enabled=bool(enabled); self.max_per_cycle=max(1,min(20,int(max_per_cycle))); self.queue=queue or ReasoningJobQueue(store)

    def enqueue_gaps(self):
        if not self.enabled: return 0
        created=0
        with self.store._connect() as c:
            rows=c.execute("SELECT * FROM intelligence_gaps WHERE status='open' ORDER BY priority DESC LIMIT ?",(self.max_per_cycle,)).fetchall()
        for row in rows:
            adapter=ALLOWLIST.get(row["desired_source_kind"])
            if not adapter: continue
            created += int(self.queue.enqueue("active_acquisition","gap",row["id"],f"gap:{row['id']}:{adapter}",row["priority"]))
        return created

    def dispatch_one(self):
        if not self.enabled: return None
        job=self.queue.lease(["active_acquisition"])
        if not job: return None
        try:
            with self.store._connect() as c:
                gap=c.execute("SELECT * FROM intelligence_gaps WHERE id=?",(job["subject_id"],)).fetchone()
                adapter=ALLOWLIST.get(gap["desired_source_kind"]) if gap else None
                source=c.execute("SELECT id FROM sources WHERE id=? AND enabled=1",(adapter,)).fetchone() if adapter else None
                if not source:
                    raise ValueError("No enabled allowlisted adapter for this gap")
                c.execute("UPDATE source_cursors SET last_polled_at=NULL,updated_at=? WHERE source_id=?",(utc_now(),adapter))
                c.execute("UPDATE intelligence_gaps SET status='requested',updated_at=? WHERE id=?",(utc_now(),gap["id"]))
                c.execute("INSERT INTO active_acquisition_attempts (gap_id,job_id,adapter,outcome,details,created_at) VALUES (?,?,?,'scheduled','{}',?)",(gap["id"],job["id"],adapter,utc_now()))
            self.queue.complete(job["id"],{"adapter":adapter,"outcome":"scheduled"})
            return adapter
        except Exception as exc:
            self.queue.fail(job["id"],exc); return None
