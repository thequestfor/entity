ALTER TABLE intelligence_reasoning_jobs
ADD COLUMN lane TEXT NOT NULL DEFAULT 'general';

ALTER TABLE intelligence_reasoning_jobs
ADD COLUMN expires_at TEXT;

CREATE INDEX idx_reasoning_jobs_lane_due
ON intelligence_reasoning_jobs(lane,status,not_before,priority DESC);

UPDATE intelligence_reasoning_jobs SET lane=CASE
  WHEN subject_type='verification_task' THEN 'verification'
  WHEN subject_type='gap' THEN 'gap'
  ELSE 'general' END;

CREATE TABLE intelligence_lane_scheduler (
    scheduler TEXT PRIMARY KEY,
    cursor INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE verification_targets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL UNIQUE,
    claim_id TEXT NOT NULL,
    adapter TEXT NOT NULL,
    identifier_type TEXT NOT NULL DEFAULT '',
    identifier_value TEXT NOT NULL DEFAULT '',
    query_parameters TEXT NOT NULL DEFAULT '{}',
    expected_value TEXT NOT NULL DEFAULT '{}',
    target_status TEXT NOT NULL DEFAULT 'ready',
    method TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(task_id) REFERENCES claim_verification_tasks(id)
      ON DELETE CASCADE,
    FOREIGN KEY(claim_id) REFERENCES claims(id) ON DELETE CASCADE
);

CREATE TABLE verification_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id INTEGER NOT NULL,
    task_id INTEGER NOT NULL,
    source_id TEXT NOT NULL,
    outcome TEXT NOT NULL,
    observed_value TEXT NOT NULL DEFAULT '{}',
    confidence REAL NOT NULL,
    basis TEXT NOT NULL,
    revision_kind TEXT NOT NULL DEFAULT '',
    closed_world INTEGER NOT NULL DEFAULT 0,
    response_hash TEXT NOT NULL,
    response_snapshot TEXT NOT NULL DEFAULT '{}',
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(target_id,response_hash,outcome),
    FOREIGN KEY(target_id) REFERENCES verification_targets(id)
      ON DELETE CASCADE,
    FOREIGN KEY(task_id) REFERENCES claim_verification_tasks(id)
      ON DELETE CASCADE,
    FOREIGN KEY(source_id) REFERENCES sources(id)
);

ALTER TABLE claim_verification_results
ADD COLUMN basis TEXT NOT NULL DEFAULT 'corroboration';
ALTER TABLE claim_verification_results
ADD COLUMN observed_value TEXT NOT NULL DEFAULT '{}';
ALTER TABLE claim_verification_results
ADD COLUMN expected_value TEXT NOT NULL DEFAULT '{}';
ALTER TABLE claim_verification_results
ADD COLUMN response_hash TEXT NOT NULL DEFAULT '';
ALTER TABLE claim_verification_results
ADD COLUMN revision_kind TEXT NOT NULL DEFAULT '';
ALTER TABLE claim_verification_results
ADD COLUMN closed_world INTEGER NOT NULL DEFAULT 0;

CREATE TABLE intelligence_budget_lane_usage (
    bucket_type TEXT NOT NULL,
    bucket_start TEXT NOT NULL,
    lane TEXT NOT NULL,
    model_calls INTEGER NOT NULL DEFAULT 0,
    estimated_input_tokens INTEGER NOT NULL DEFAULT 0,
    estimated_output_tokens INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(bucket_type,bucket_start,lane)
);

ALTER TABLE forecasts ADD COLUMN generation_job_id INTEGER;

CREATE TABLE forecast_generation_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    situation_id TEXT NOT NULL,
    evidence_snapshot_hash TEXT NOT NULL,
    outcome TEXT NOT NULL,
    forecast_id TEXT,
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY(job_id) REFERENCES intelligence_reasoning_jobs(id)
      ON DELETE CASCADE,
    FOREIGN KEY(situation_id) REFERENCES situations(id) ON DELETE CASCADE,
    FOREIGN KEY(forecast_id) REFERENCES forecasts(id) ON DELETE SET NULL
);

CREATE INDEX idx_forecast_generation_attempts_situation
ON forecast_generation_attempts(situation_id,created_at DESC);
