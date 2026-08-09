CREATE TABLE epistemic_policy_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    policy TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    promoted_at TEXT
);

INSERT INTO epistemic_policy_versions (
    version,status,policy,input_hash,created_at,promoted_at
) VALUES (
    'truth-seeking-v1','active',
    '{"corroboration":"independent-reporting-families","forecast_truth_separation":true,"operator_preferences_affect_truth":false,"retain_competing_hypotheses":true,"retain_unknowns":true,"source_framing_separate_from_accuracy":true}',
    'truth-seeking-v1','2026-08-09T00:00:00Z','2026-08-09T00:00:00Z'
);

CREATE TABLE world_event_assessments (
    world_event_id TEXT PRIMARY KEY,
    assessment_status TEXT NOT NULL,
    headline TEXT NOT NULL,
    confidence REAL NOT NULL,
    independent_family_count INTEGER NOT NULL DEFAULT 0,
    observation_count INTEGER NOT NULL DEFAULT 0,
    direct_observation_count INTEGER NOT NULL DEFAULT 0,
    established_facts TEXT NOT NULL DEFAULT '[]',
    reported_claims TEXT NOT NULL DEFAULT '[]',
    disputes TEXT NOT NULL DEFAULT '[]',
    hypotheses TEXT NOT NULL DEFAULT '[]',
    unknowns TEXT NOT NULL DEFAULT '[]',
    evidence_document_ids TEXT NOT NULL DEFAULT '[]',
    evidence_cutoff_at TEXT NOT NULL,
    epistemic_policy_version TEXT NOT NULL,
    method TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    event_updated_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(world_event_id) REFERENCES world_events(id) ON DELETE CASCADE
);

CREATE TABLE world_event_assessment_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    world_event_id TEXT NOT NULL,
    assessment_status TEXT NOT NULL,
    headline TEXT NOT NULL,
    confidence REAL NOT NULL,
    independent_family_count INTEGER NOT NULL,
    observation_count INTEGER NOT NULL,
    direct_observation_count INTEGER NOT NULL,
    established_facts TEXT NOT NULL,
    reported_claims TEXT NOT NULL,
    disputes TEXT NOT NULL,
    hypotheses TEXT NOT NULL,
    unknowns TEXT NOT NULL,
    evidence_document_ids TEXT NOT NULL,
    evidence_cutoff_at TEXT NOT NULL,
    epistemic_policy_version TEXT NOT NULL,
    method TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(world_event_id,input_hash),
    FOREIGN KEY(world_event_id) REFERENCES world_events(id) ON DELETE CASCADE
);

CREATE INDEX idx_world_event_assessments_status
ON world_event_assessments(assessment_status,confidence DESC,evidence_cutoff_at DESC);
