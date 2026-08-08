ALTER TABLE situation_hypotheses ADD COLUMN hypothesis_key TEXT NOT NULL DEFAULT '';
ALTER TABLE situation_hypotheses ADD COLUMN hypothesis_type TEXT NOT NULL DEFAULT 'alternative';
ALTER TABLE situation_hypotheses ADD COLUMN prior_probability REAL NOT NULL DEFAULT 0.2;
ALTER TABLE situation_hypotheses ADD COLUMN assumptions TEXT NOT NULL DEFAULT '[]';
ALTER TABLE situation_hypotheses ADD COLUMN open_questions TEXT NOT NULL DEFAULT '[]';
ALTER TABLE situation_hypotheses ADD COLUMN evidence_cutoff_at TEXT;
ALTER TABLE situation_hypotheses ADD COLUMN generator_version TEXT NOT NULL DEFAULT '';
ALTER TABLE situation_hypotheses ADD COLUMN retired_at TEXT;

CREATE TABLE hypothesis_claim_links (
    hypothesis_id TEXT NOT NULL,
    claim_id TEXT NOT NULL,
    relationship TEXT NOT NULL,
    likelihood_ratio REAL NOT NULL,
    independence_key TEXT NOT NULL DEFAULT '',
    method TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(hypothesis_id, claim_id, relationship, method),
    FOREIGN KEY(hypothesis_id) REFERENCES situation_hypotheses(id) ON DELETE CASCADE,
    FOREIGN KEY(claim_id) REFERENCES claims(id) ON DELETE CASCADE
);

CREATE TABLE hypothesis_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hypothesis_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    prior_probability REAL NOT NULL,
    posterior_probability REAL NOT NULL,
    supporting_claim_ids TEXT NOT NULL DEFAULT '[]',
    contradicting_claim_ids TEXT NOT NULL DEFAULT '[]',
    input_snapshot_hash TEXT NOT NULL,
    reason TEXT NOT NULL,
    method TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(hypothesis_id, version),
    FOREIGN KEY(hypothesis_id) REFERENCES situation_hypotheses(id) ON DELETE CASCADE
);

CREATE TABLE hypothesis_generation_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    situation_id TEXT NOT NULL,
    input_snapshot_hash TEXT NOT NULL,
    hypotheses_created INTEGER NOT NULL DEFAULT 0,
    outcome TEXT NOT NULL,
    error TEXT NOT NULL DEFAULT '',
    method TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(situation_id, input_snapshot_hash, method),
    FOREIGN KEY(situation_id) REFERENCES situations(id) ON DELETE CASCADE
);

CREATE TABLE intelligence_gaps (
    id TEXT PRIMARY KEY,
    situation_id TEXT NOT NULL,
    hypothesis_id TEXT,
    question TEXT NOT NULL,
    target_predicate TEXT NOT NULL DEFAULT '',
    desired_source_kind TEXT NOT NULL DEFAULT 'independent-public',
    expected_information_value REAL NOT NULL DEFAULT 0.0,
    priority REAL NOT NULL DEFAULT 0.5,
    status TEXT NOT NULL DEFAULT 'open',
    dedupe_key TEXT NOT NULL UNIQUE,
    method TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(situation_id) REFERENCES situations(id) ON DELETE CASCADE,
    FOREIGN KEY(hypothesis_id) REFERENCES situation_hypotheses(id) ON DELETE SET NULL
);

CREATE INDEX idx_intelligence_gaps_status_priority
ON intelligence_gaps(status, priority DESC, updated_at);
