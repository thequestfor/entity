ALTER TABLE claims ADD COLUMN claim_type TEXT NOT NULL DEFAULT 'reported_fact';
ALTER TABLE claims ADD COLUMN verifiability TEXT NOT NULL DEFAULT 'unknown';
ALTER TABLE claims ADD COLUMN attribution TEXT NOT NULL DEFAULT 'source_report';
ALTER TABLE claims ADD COLUMN topic TEXT NOT NULL DEFAULT 'general';

CREATE TABLE situation_hypotheses (
    id TEXT PRIMARY KEY,
    situation_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    probability REAL NOT NULL DEFAULT 0.0,
    status TEXT NOT NULL DEFAULT 'active',
    supporting_claim_ids TEXT NOT NULL DEFAULT '[]',
    contradicting_claim_ids TEXT NOT NULL DEFAULT '[]',
    falsifiers TEXT NOT NULL DEFAULT '[]',
    method TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(situation_id, title, method),
    FOREIGN KEY(situation_id) REFERENCES situations(id) ON DELETE CASCADE
);

CREATE INDEX idx_hypotheses_situation_status
ON situation_hypotheses(situation_id, status, probability DESC);
