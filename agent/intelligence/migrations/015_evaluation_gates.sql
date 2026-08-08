CREATE TABLE intelligence_evaluation_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    suite_version TEXT NOT NULL,
    outcome TEXT NOT NULL,
    passed INTEGER NOT NULL,
    failed INTEGER NOT NULL,
    critical_failures INTEGER NOT NULL,
    metrics TEXT NOT NULL DEFAULT '{}',
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL
);

CREATE TABLE intelligence_evaluation_cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    case_key TEXT NOT NULL,
    category TEXT NOT NULL,
    passed INTEGER NOT NULL,
    critical INTEGER NOT NULL DEFAULT 0,
    difference REAL NOT NULL DEFAULT 0.0,
    details TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(run_id, case_key),
    FOREIGN KEY(run_id) REFERENCES intelligence_evaluation_runs(id) ON DELETE CASCADE
);

CREATE TABLE intelligence_feature_gates (
    feature TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'shadow',
    reason TEXT NOT NULL,
    evaluation_run_id INTEGER,
    sample_count INTEGER NOT NULL DEFAULT 0,
    metric REAL,
    required_metric REAL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(evaluation_run_id) REFERENCES intelligence_evaluation_runs(id)
);

INSERT INTO intelligence_feature_gates (
  feature,status,reason,updated_at
) VALUES
('topic_reliability','shadow','Awaiting sufficient scoped outcomes and symmetry evaluation',datetime('now')),
('hypothesis_competition','shadow','Awaiting blinded symmetry evaluation',datetime('now')),
('forecast_v2','shadow','Awaiting 50 resolved forecasts and calibration improvement',datetime('now')),
('learned_ensemble','blocked','Awaiting 100 resolved forecasts and out-of-time validation',datetime('now'));
