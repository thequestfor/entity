CREATE TABLE intelligence_scheduler_state (
    engine TEXT PRIMARY KEY,
    last_rotation_key TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE TABLE intelligence_workload_limits (
    engine TEXT PRIMARY KEY,
    max_active_per_key INTEGER NOT NULL,
    max_active_global INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX idx_article_acquisition_tasks_active_source
ON article_acquisition_tasks(source_id,status,created_at,id);
