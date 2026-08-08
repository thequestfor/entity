ALTER TABLE claims ADD COLUMN truth_status TEXT NOT NULL DEFAULT 'unverified';
ALTER TABLE claims ADD COLUMN resolution_confidence REAL NOT NULL DEFAULT 0.0;
ALTER TABLE claims ADD COLUMN core_importance REAL NOT NULL DEFAULT 0.5;
ALTER TABLE claims ADD COLUMN last_resolved_at TEXT;
ALTER TABLE claims ADD COLUMN resolver_version TEXT NOT NULL DEFAULT '';

CREATE TABLE claim_relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    left_claim_id TEXT NOT NULL,
    right_claim_id TEXT NOT NULL,
    relationship TEXT NOT NULL,
    confidence REAL NOT NULL,
    method TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(left_claim_id, right_claim_id, relationship, method),
    FOREIGN KEY(left_claim_id) REFERENCES claims(id) ON DELETE CASCADE,
    FOREIGN KEY(right_claim_id) REFERENCES claims(id) ON DELETE CASCADE
);

CREATE INDEX idx_claim_relations_left ON claim_relations(left_claim_id, relationship);
CREATE INDEX idx_claim_relations_right ON claim_relations(right_claim_id, relationship);

CREATE TABLE claim_resolution_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL,
    previous_status TEXT NOT NULL,
    truth_status TEXT NOT NULL,
    confidence REAL NOT NULL,
    supporting_claim_ids TEXT NOT NULL DEFAULT '[]',
    contradicting_claim_ids TEXT NOT NULL DEFAULT '[]',
    evidence_document_ids TEXT NOT NULL DEFAULT '[]',
    reason TEXT NOT NULL,
    method TEXT NOT NULL,
    input_snapshot_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(claim_id) REFERENCES claims(id) ON DELETE CASCADE
);

CREATE INDEX idx_claim_resolution_history_claim
ON claim_resolution_history(claim_id, created_at DESC);

CREATE TABLE claim_verification_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL,
    verification_kind TEXT NOT NULL DEFAULT 'independent_evidence',
    desired_source_kind TEXT NOT NULL DEFAULT '',
    priority REAL NOT NULL DEFAULT 0.5,
    status TEXT NOT NULL DEFAULT 'pending',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT NOT NULL,
    last_error TEXT NOT NULL DEFAULT '',
    dedupe_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(claim_id) REFERENCES claims(id) ON DELETE CASCADE
);

CREATE INDEX idx_claim_verification_due
ON claim_verification_tasks(status, next_attempt_at, priority DESC);

CREATE TABLE claim_verification_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    claim_id TEXT NOT NULL,
    result TEXT NOT NULL,
    confidence REAL NOT NULL,
    authority_level TEXT NOT NULL DEFAULT 'secondary',
    document_version_id INTEGER,
    reason TEXT NOT NULL DEFAULT '',
    method TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(task_id, document_version_id, result, method),
    FOREIGN KEY(task_id) REFERENCES claim_verification_tasks(id) ON DELETE CASCADE,
    FOREIGN KEY(claim_id) REFERENCES claims(id) ON DELETE CASCADE,
    FOREIGN KEY(document_version_id) REFERENCES document_versions(id)
);

CREATE TABLE publisher_claim_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    publisher_key TEXT NOT NULL,
    claim_id TEXT NOT NULL,
    topic TEXT NOT NULL,
    claim_type TEXT NOT NULL,
    outcome TEXT NOT NULL,
    confidence REAL NOT NULL,
    evidence_document_ids TEXT NOT NULL DEFAULT '[]',
    method TEXT NOT NULL,
    evaluated_at TEXT NOT NULL,
    UNIQUE(publisher_key, claim_id, method),
    FOREIGN KEY(publisher_key) REFERENCES publisher_reputation(publisher_key),
    FOREIGN KEY(claim_id) REFERENCES claims(id) ON DELETE CASCADE
);

CREATE TABLE publisher_reliability_cells (
    publisher_key TEXT NOT NULL,
    topic TEXT NOT NULL,
    claim_type TEXT NOT NULL,
    baseline REAL NOT NULL,
    alpha REAL NOT NULL,
    beta REAL NOT NULL,
    learned_reliability REAL NOT NULL,
    reliability_lower_bound REAL NOT NULL,
    reliability_upper_bound REAL NOT NULL,
    confirmed_count INTEGER NOT NULL DEFAULT 0,
    refuted_count INTEGER NOT NULL DEFAULT 0,
    mixed_count INTEGER NOT NULL DEFAULT 0,
    evaluated_count INTEGER NOT NULL DEFAULT 0,
    method TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(publisher_key, topic, claim_type),
    FOREIGN KEY(publisher_key) REFERENCES publisher_reputation(publisher_key)
);

CREATE INDEX idx_reliability_cells_topic
ON publisher_reliability_cells(topic, claim_type, learned_reliability DESC);

CREATE TABLE publisher_reliability_cell_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    publisher_key TEXT NOT NULL,
    topic TEXT NOT NULL,
    claim_type TEXT NOT NULL,
    previous_reliability REAL NOT NULL,
    learned_reliability REAL NOT NULL,
    lower_bound REAL NOT NULL,
    upper_bound REAL NOT NULL,
    evaluated_count INTEGER NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE publisher_content_profiles (
    publisher_key TEXT PRIMARY KEY,
    direct_fact_share REAL NOT NULL DEFAULT 0.0,
    attributed_claim_share REAL NOT NULL DEFAULT 0.0,
    interpretation_share REAL NOT NULL DEFAULT 0.0,
    causal_claim_share REAL NOT NULL DEFAULT 0.0,
    primary_evidence_share REAL NOT NULL DEFAULT 0.0,
    syndication_share REAL NOT NULL DEFAULT 0.0,
    sample_count INTEGER NOT NULL DEFAULT 0,
    method TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(publisher_key) REFERENCES publisher_reputation(publisher_key)
);
