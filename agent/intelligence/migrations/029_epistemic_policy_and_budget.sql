CREATE TABLE publisher_assessments (
    publisher_key TEXT NOT NULL,
    scope_kind TEXT NOT NULL DEFAULT 'global',
    scope_value TEXT NOT NULL DEFAULT '',
    baseline_credibility REAL NOT NULL,
    evidence_estimate REAL NOT NULL,
    effective_credibility REAL NOT NULL,
    reliability_lower_bound REAL NOT NULL,
    reliability_upper_bound REAL NOT NULL,
    confirmed_count INTEGER NOT NULL DEFAULT 0,
    refuted_count INTEGER NOT NULL DEFAULT 0,
    mixed_count INTEGER NOT NULL DEFAULT 0,
    factual_samples INTEGER NOT NULL DEFAULT 0,
    attribution_quality REAL NOT NULL DEFAULT 0.5,
    revision_discipline REAL NOT NULL DEFAULT 0.5,
    independence_confidence REAL NOT NULL DEFAULT 0.5,
    framing_prior REAL NOT NULL DEFAULT 0.0,
    observed_framing REAL NOT NULL DEFAULT 0.0,
    framing_signal REAL NOT NULL DEFAULT 0.0,
    affiliation TEXT NOT NULL DEFAULT '',
    rationale TEXT NOT NULL DEFAULT '',
    maturity_status TEXT NOT NULL,
    method TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(publisher_key,scope_kind,scope_value),
    FOREIGN KEY(publisher_key) REFERENCES publisher_reputation(publisher_key)
);

CREATE TABLE publisher_assessment_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    publisher_key TEXT NOT NULL,
    scope_kind TEXT NOT NULL,
    scope_value TEXT NOT NULL,
    baseline_credibility REAL NOT NULL,
    evidence_estimate REAL NOT NULL,
    effective_credibility REAL NOT NULL,
    reliability_lower_bound REAL NOT NULL,
    reliability_upper_bound REAL NOT NULL,
    confirmed_count INTEGER NOT NULL,
    refuted_count INTEGER NOT NULL,
    mixed_count INTEGER NOT NULL,
    factual_samples INTEGER NOT NULL,
    framing_signal REAL NOT NULL,
    maturity_status TEXT NOT NULL,
    method TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(publisher_key,scope_kind,scope_value,input_hash),
    FOREIGN KEY(publisher_key) REFERENCES publisher_reputation(publisher_key)
);

CREATE INDEX idx_publisher_assessment_effective
ON publisher_assessments(scope_kind,effective_credibility DESC,factual_samples DESC);

CREATE TABLE intelligence_budget_lane_policies (
    lane TEXT PRIMARY KEY,
    hourly_limit INTEGER NOT NULL,
    daily_limit INTEGER NOT NULL,
    hourly_reserve INTEGER NOT NULL DEFAULT 0,
    daily_reserve INTEGER NOT NULL DEFAULT 0,
    configured_by TEXT NOT NULL DEFAULT 'runtime-configuration',
    updated_at TEXT NOT NULL
);

CREATE TABLE intelligence_model_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lane TEXT NOT NULL,
    operation TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    error_code TEXT NOT NULL DEFAULT '',
    estimated_input_tokens INTEGER NOT NULL DEFAULT 0,
    estimated_output_tokens INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE INDEX idx_intelligence_model_attempts_lane_time
ON intelligence_model_attempts(lane,started_at DESC,status);
