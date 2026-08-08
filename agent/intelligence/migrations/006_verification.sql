ALTER TABLE publisher_outcomes
ADD COLUMN evidence_document_ids TEXT NOT NULL DEFAULT '[]';

ALTER TABLE publisher_outcomes
ADD COLUMN outcome_confidence REAL NOT NULL DEFAULT 0.5;

ALTER TABLE publisher_outcomes
ADD COLUMN was_early INTEGER NOT NULL DEFAULT 0;

ALTER TABLE publisher_outcomes
ADD COLUMN verification_method TEXT NOT NULL DEFAULT 'delayed-corroboration-v2';

ALTER TABLE publisher_reputation
ADD COLUMN reliability_lower_bound REAL NOT NULL DEFAULT 0.0;

ALTER TABLE publisher_reputation
ADD COLUMN reliability_upper_bound REAL NOT NULL DEFAULT 1.0;

CREATE TABLE publisher_verification_attempts (
    document_id TEXT PRIMARY KEY,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_attempt_at TEXT NOT NULL,
    next_attempt_at TEXT NOT NULL,
    last_reason TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE INDEX idx_publisher_verification_due
ON publisher_verification_attempts(next_attempt_at);
