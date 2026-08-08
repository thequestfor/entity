ALTER TABLE forecasts ADD COLUMN hypothesis_id TEXT;
ALTER TABLE forecasts ADD COLUMN forecast_kind TEXT NOT NULL DEFAULT 'freeform';
ALTER TABLE forecasts ADD COLUMN category TEXT NOT NULL DEFAULT 'general';
ALTER TABLE forecasts ADD COLUMN horizon_bucket TEXT NOT NULL DEFAULT 'unknown';
ALTER TABLE forecasts ADD COLUMN evidence_cutoff_at TEXT;
ALTER TABLE forecasts ADD COLUMN evidence_snapshot_hash TEXT NOT NULL DEFAULT '';
ALTER TABLE forecasts ADD COLUMN base_rate REAL;
ALTER TABLE forecasts ADD COLUMN base_rate_source TEXT NOT NULL DEFAULT '';
ALTER TABLE forecasts ADD COLUMN model_probability REAL;
ALTER TABLE forecasts ADD COLUMN ensemble_probability REAL;
ALTER TABLE forecasts ADD COLUMN resolution_confidence REAL NOT NULL DEFAULT 0.0;
ALTER TABLE forecasts ADD COLUMN resolver_method TEXT NOT NULL DEFAULT '';
ALTER TABLE forecasts ADD COLUMN resolver_version TEXT NOT NULL DEFAULT '';
ALTER TABLE forecasts ADD COLUMN next_resolution_at TEXT;
ALTER TABLE forecasts ADD COLUMN terminal_reason TEXT NOT NULL DEFAULT '';
ALTER TABLE forecasts ADD COLUMN shadow INTEGER NOT NULL DEFAULT 0;

CREATE TABLE forecast_evidence (
    forecast_id TEXT NOT NULL,
    claim_id TEXT,
    document_version_id INTEGER,
    role TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    snapshot_hash TEXT NOT NULL,
    PRIMARY KEY(forecast_id, claim_id, document_version_id, role),
    FOREIGN KEY(forecast_id) REFERENCES forecasts(id) ON DELETE CASCADE,
    FOREIGN KEY(claim_id) REFERENCES claims(id),
    FOREIGN KEY(document_version_id) REFERENCES document_versions(id)
);

CREATE TABLE forecast_component_predictions (
    forecast_id TEXT NOT NULL,
    component TEXT NOT NULL,
    probability REAL NOT NULL,
    weight REAL NOT NULL,
    method TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(forecast_id, component, method),
    FOREIGN KEY(forecast_id) REFERENCES forecasts(id) ON DELETE CASCADE
);

CREATE TABLE forecast_resolution_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    forecast_id TEXT NOT NULL,
    outcome TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.0,
    summary TEXT NOT NULL DEFAULT '',
    evidence_document_ids TEXT NOT NULL DEFAULT '[]',
    input_snapshot_hash TEXT NOT NULL,
    method TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(forecast_id) REFERENCES forecasts(id) ON DELETE CASCADE
);

CREATE TABLE base_rate_models (
    category TEXT NOT NULL,
    forecast_kind TEXT NOT NULL,
    horizon_bucket TEXT NOT NULL,
    successes INTEGER NOT NULL DEFAULT 0,
    failures INTEGER NOT NULL DEFAULT 0,
    rate REAL NOT NULL,
    lower_bound REAL NOT NULL,
    upper_bound REAL NOT NULL,
    method TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(category, forecast_kind, horizon_bucket)
);

CREATE TABLE situation_feature_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    situation_id TEXT NOT NULL,
    feature_version TEXT NOT NULL,
    features TEXT NOT NULL,
    snapshot_hash TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    UNIQUE(situation_id, snapshot_hash, feature_version),
    FOREIGN KEY(situation_id) REFERENCES situations(id) ON DELETE CASCADE
);

CREATE TABLE forecast_model_versions (
    id TEXT PRIMARY KEY,
    method TEXT NOT NULL,
    coefficients TEXT NOT NULL,
    sample_count INTEGER NOT NULL DEFAULT 0,
    training_cutoff_at TEXT,
    status TEXT NOT NULL DEFAULT 'candidate',
    brier_score REAL,
    log_loss REAL,
    created_at TEXT NOT NULL,
    promoted_at TEXT
);

CREATE TABLE ensemble_training_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_version_id TEXT,
    training_cutoff_at TEXT NOT NULL,
    training_samples INTEGER NOT NULL,
    validation_samples INTEGER NOT NULL,
    baseline_brier REAL,
    candidate_brier REAL,
    promoted INTEGER NOT NULL DEFAULT 0,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE forecast_calibration_buckets (
    category TEXT NOT NULL,
    horizon_bucket TEXT NOT NULL,
    probability_bucket TEXT NOT NULL,
    forecast_count INTEGER NOT NULL,
    observed_rate REAL,
    brier_score REAL,
    resolution_coverage REAL NOT NULL DEFAULT 0.0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(category, horizon_bucket, probability_bucket)
);

UPDATE forecasts SET
    forecast_kind=COALESCE(forecast_kind,'freeform'),
    category=COALESCE(category,'general'),
    horizon_bucket=COALESCE(horizon_bucket,'unknown'),
    evidence_snapshot_hash=COALESCE(evidence_snapshot_hash,''),
    base_rate_source=COALESCE(base_rate_source,''),
    resolution_confidence=COALESCE(resolution_confidence,0.0),
    resolver_method=COALESCE(resolver_method,''),
    resolver_version=COALESCE(resolver_version,''),
    terminal_reason=COALESCE(terminal_reason,''),
    shadow=COALESCE(shadow,0);
