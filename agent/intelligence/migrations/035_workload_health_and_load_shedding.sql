CREATE TABLE intelligence_workload_state (
    engine TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    reason TEXT NOT NULL,
    metrics TEXT NOT NULL DEFAULT '{}',
    policy_version TEXT NOT NULL,
    first_entered_at TEXT NOT NULL,
    last_checked_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE intelligence_workload_transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    engine TEXT NOT NULL,
    previous_status TEXT NOT NULL,
    new_status TEXT NOT NULL,
    reason TEXT NOT NULL,
    metrics TEXT NOT NULL DEFAULT '{}',
    policy_version TEXT NOT NULL,
    transitioned_at TEXT NOT NULL
);

CREATE INDEX idx_intelligence_workload_transitions_engine_time
ON intelligence_workload_transitions(engine,transitioned_at DESC,id DESC);
