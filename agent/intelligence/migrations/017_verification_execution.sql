CREATE TABLE claim_verification_applications (
    result_id INTEGER PRIMARY KEY,
    claim_id TEXT NOT NULL,
    applied_status TEXT NOT NULL,
    previous_status TEXT NOT NULL,
    confidence REAL NOT NULL,
    method TEXT NOT NULL,
    applied_at TEXT NOT NULL,
    FOREIGN KEY(result_id) REFERENCES claim_verification_results(id)
      ON DELETE CASCADE,
    FOREIGN KEY(claim_id) REFERENCES claims(id) ON DELETE CASCADE
);

CREATE TABLE verification_acquisition_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    verification_task_id INTEGER NOT NULL,
    job_id INTEGER,
    adapter TEXT NOT NULL,
    outcome TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY(verification_task_id) REFERENCES claim_verification_tasks(id)
      ON DELETE CASCADE,
    FOREIGN KEY(job_id) REFERENCES intelligence_reasoning_jobs(id)
      ON DELETE SET NULL
);

CREATE INDEX idx_verification_results_claim
ON claim_verification_results(claim_id, created_at DESC);

CREATE INDEX idx_verification_acquisition_task
ON verification_acquisition_attempts(verification_task_id, created_at DESC);
