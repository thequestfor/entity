"""Persistent idempotent jobs with crash-safe leases and bounded retries."""

from datetime import UTC, datetime, timedelta

from agent.intelligence.store import utc_now


class ReasoningJobQueue:
    def __init__(self,store,lease_seconds=120,max_attempts=3):
        self.store=store; self.lease_seconds=max(30,int(lease_seconds)); self.max_attempts=max(1,int(max_attempts))

    def enqueue(self,job_type,subject_type,subject_id,dedupe_key,priority=.5,snapshot_hash=""):
        now=utc_now()
        with self.store._connect() as c:
            cursor=c.execute("""
              INSERT OR IGNORE INTO intelligence_reasoning_jobs
              (job_type,subject_type,subject_id,priority,dedupe_key,input_snapshot_hash,not_before,created_at,updated_at)
              VALUES (?,?,?,?,?,?,?,?,?)
            """,(job_type,subject_type,subject_id,max(0,min(1,float(priority))),dedupe_key,snapshot_hash,now,now,now))
        return cursor.rowcount>0

    def lease(self,job_types=None):
        now=datetime.now(UTC); now_text=now.isoformat(timespec="seconds").replace("+00:00","Z")
        expiry=(now+timedelta(seconds=self.lease_seconds)).isoformat(timespec="seconds").replace("+00:00","Z")
        with self.store._connect() as c:
            c.execute("BEGIN IMMEDIATE")
            c.execute("UPDATE intelligence_reasoning_jobs SET status='pending',lease_expires_at=NULL,updated_at=? WHERE status='leased' AND lease_expires_at<?",(now_text,now_text))
            query="SELECT * FROM intelligence_reasoning_jobs WHERE status='pending' AND not_before<=?"
            params=[now_text]
            if job_types:
                query += " AND job_type IN (%s)" % ",".join("?" for _ in job_types); params.extend(job_types)
            query += " ORDER BY priority DESC,created_at LIMIT 1"
            row=c.execute(query,params).fetchone()
            if not row: return None
            c.execute("UPDATE intelligence_reasoning_jobs SET status='leased',lease_expires_at=?,attempt_count=attempt_count+1,updated_at=? WHERE id=?",(expiry,now_text,row["id"]))
            return dict(c.execute("SELECT * FROM intelligence_reasoning_jobs WHERE id=?",(row["id"],)).fetchone())

    def complete(self,job_id,output=None,schema_version="v1",provider=""):
        now=utc_now()
        with self.store._connect() as c:
            if output is not None:
                c.execute("INSERT OR IGNORE INTO intelligence_reasoning_artifacts (job_id,schema_version,input_snapshot_hash,output,valid,provider,created_at) SELECT id,?,input_snapshot_hash,?,1,?,? FROM intelligence_reasoning_jobs WHERE id=?",
                          (schema_version,self.store._json(output),provider,now,job_id))
            c.execute("UPDATE intelligence_reasoning_jobs SET status='completed',lease_expires_at=NULL,completed_at=?,updated_at=? WHERE id=?",(now,now,job_id))

    def fail(self,job_id,error):
        now=datetime.now(UTC)
        with self.store._connect() as c:
            row=c.execute("SELECT attempt_count FROM intelligence_reasoning_jobs WHERE id=?",(job_id,)).fetchone()
            attempts=int(row[0] or 0) if row else self.max_attempts
            status="failed" if attempts>=self.max_attempts else "pending"
            delay=min(3600,60*(2**max(0,attempts-1)))
            not_before=(now+timedelta(seconds=delay)).isoformat(timespec="seconds").replace("+00:00","Z")
            c.execute("UPDATE intelligence_reasoning_jobs SET status=?,not_before=?,lease_expires_at=NULL,last_error=?,updated_at=? WHERE id=?",
                      (status,not_before,str(error)[:500],utc_now(),job_id))

    def overview(self):
        with self.store._connect() as c:
            rows=c.execute("SELECT status,COUNT(*) count FROM intelligence_reasoning_jobs GROUP BY status").fetchall()
            oldest=c.execute("SELECT MIN(created_at) FROM intelligence_reasoning_jobs WHERE status='pending'").fetchone()[0]
        return {"counts":{row["status"]:row["count"] for row in rows},"oldest_pending_at":oldest}
