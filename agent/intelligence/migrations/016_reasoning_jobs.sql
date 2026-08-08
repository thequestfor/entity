CREATE TABLE intelligence_reasoning_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_type TEXT NOT NULL,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    priority REAL NOT NULL DEFAULT 0.5,
    status TEXT NOT NULL DEFAULT 'pending',
    dedupe_key TEXT NOT NULL UNIQUE,
    input_snapshot_hash TEXT NOT NULL DEFAULT '',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    not_before TEXT NOT NULL,
    lease_expires_at TEXT,
    provider TEXT NOT NULL DEFAULT '',
    estimated_input_tokens INTEGER NOT NULL DEFAULT 0,
    estimated_output_tokens INTEGER NOT NULL DEFAULT 0,
    estimated_cost REAL NOT NULL DEFAULT 0.0,
    last_error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE INDEX idx_reasoning_jobs_due
ON intelligence_reasoning_jobs(status, not_before, priority DESC);

CREATE TABLE intelligence_reasoning_artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    schema_version TEXT NOT NULL,
    input_snapshot_hash TEXT NOT NULL,
    output TEXT NOT NULL,
    valid INTEGER NOT NULL,
    provider TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(job_id, schema_version, input_snapshot_hash),
    FOREIGN KEY(job_id) REFERENCES intelligence_reasoning_jobs(id) ON DELETE CASCADE
);

CREATE TABLE intelligence_budget_usage (
    bucket_type TEXT NOT NULL,
    bucket_start TEXT NOT NULL,
    model_calls INTEGER NOT NULL DEFAULT 0,
    estimated_input_tokens INTEGER NOT NULL DEFAULT 0,
    estimated_output_tokens INTEGER NOT NULL DEFAULT 0,
    estimated_cost REAL NOT NULL DEFAULT 0.0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(bucket_type, bucket_start)
);

CREATE TABLE active_acquisition_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    gap_id TEXT NOT NULL,
    job_id INTEGER,
    adapter TEXT NOT NULL,
    outcome TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY(gap_id) REFERENCES intelligence_gaps(id) ON DELETE CASCADE,
    FOREIGN KEY(job_id) REFERENCES intelligence_reasoning_jobs(id) ON DELETE SET NULL
);
