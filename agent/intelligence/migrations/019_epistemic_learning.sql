CREATE TABLE claim_groundings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL,
    document_version_id INTEGER,
    grounding_type TEXT NOT NULL,
    namespace TEXT NOT NULL DEFAULT '',
    value TEXT NOT NULL,
    normalized_value TEXT NOT NULL,
    confidence REAL NOT NULL,
    evidence_excerpt TEXT NOT NULL DEFAULT '',
    method TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(claim_id, grounding_type, namespace, normalized_value,
           document_version_id, schema_version),
    FOREIGN KEY(claim_id) REFERENCES claims(id) ON DELETE CASCADE,
    FOREIGN KEY(document_version_id) REFERENCES document_versions(id)
);

CREATE INDEX idx_claim_groundings_lookup
ON claim_groundings(claim_id, grounding_type, namespace, confidence DESC);

CREATE UNIQUE INDEX idx_claim_groundings_dedupe
ON claim_groundings(
    claim_id,grounding_type,namespace,normalized_value,
    COALESCE(document_version_id,0),schema_version
);

CREATE TABLE grounding_backfill_state (
    name TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL,
    cursor_rowid INTEGER NOT NULL DEFAULT 0,
    processed INTEGER NOT NULL DEFAULT 0,
    grounded INTEGER NOT NULL DEFAULT 0,
    skipped INTEGER NOT NULL DEFAULT 0,
    errors INTEGER NOT NULL DEFAULT 0,
    completed INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);

ALTER TABLE verification_targets ADD COLUMN grounding_id INTEGER;
ALTER TABLE verification_targets ADD COLUMN schema_version TEXT NOT NULL DEFAULT 'v1';
ALTER TABLE verification_targets ADD COLUMN resolution_reason TEXT NOT NULL DEFAULT '';
ALTER TABLE verification_targets ADD COLUMN refreshed_at TEXT;

ALTER TABLE claim_verification_results
ADD COLUMN verifier_source_id TEXT NOT NULL DEFAULT '';

ALTER TABLE publisher_claim_outcomes
ADD COLUMN evidence_basis TEXT NOT NULL DEFAULT 'independent-corroboration';
ALTER TABLE publisher_claim_outcomes
ADD COLUMN outcome_weight REAL NOT NULL DEFAULT 1.0;
ALTER TABLE publisher_claim_outcomes
ADD COLUMN verifier_source_id TEXT NOT NULL DEFAULT '';
ALTER TABLE publisher_claim_outcomes
ADD COLUMN independent_family_count INTEGER NOT NULL DEFAULT 0;

CREATE TABLE publisher_epistemic_profiles (
    publisher_key TEXT PRIMARY KEY,
    factual_accuracy REAL NOT NULL DEFAULT 0.5,
    attribution_quality REAL NOT NULL DEFAULT 0.5,
    revision_discipline REAL NOT NULL DEFAULT 0.5,
    independence_confidence REAL NOT NULL DEFAULT 0.5,
    framing_signal REAL NOT NULL DEFAULT 0.0,
    factual_samples INTEGER NOT NULL DEFAULT 0,
    revision_samples INTEGER NOT NULL DEFAULT 0,
    method TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(publisher_key) REFERENCES publisher_reputation(publisher_key)
);

ALTER TABLE forecasts ADD COLUMN portfolio_slot TEXT NOT NULL DEFAULT '';
ALTER TABLE forecasts ADD COLUMN resolution_job_id INTEGER;

CREATE TABLE forecast_portfolio_state (
    horizon_bucket TEXT PRIMARY KEY,
    target_share REAL NOT NULL,
    generated_count INTEGER NOT NULL DEFAULT 0,
    resolved_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

INSERT OR IGNORE INTO forecast_portfolio_state
(horizon_bucket,target_share,updated_at) VALUES
('0-1d',0.40,datetime('now')),
('1-3d',0.35,datetime('now')),
('3-7d',0.20,datetime('now')),
('7-30d',0.05,datetime('now'));

UPDATE claim_verification_tasks
SET status='not_applicable',
    last_error='Bookkeeping predicates are not independently verifiable facts',
    updated_at=datetime('now')
WHERE status='pending' AND claim_id IN (
    SELECT id FROM claims
    WHERE predicate IN ('event.reported','event.category')
);

CREATE INDEX idx_forecasts_v2_training
ON forecasts(method,status,resolved_at,created_at,shadow);
