ALTER TABLE claims ADD COLUMN attributed_to TEXT NOT NULL DEFAULT '';
ALTER TABLE claims ADD COLUMN endorsement TEXT NOT NULL DEFAULT 'asserts';
ALTER TABLE claims ADD COLUMN extraction_confidence REAL NOT NULL DEFAULT 0.5;
ALTER TABLE claims ADD COLUMN extraction_method TEXT NOT NULL DEFAULT 'legacy';
ALTER TABLE claims ADD COLUMN extraction_version TEXT NOT NULL DEFAULT 'legacy-v1';
ALTER TABLE claims ADD COLUMN precision TEXT NOT NULL DEFAULT 'unknown';
ALTER TABLE claims ADD COLUMN evidence_role TEXT NOT NULL DEFAULT 'secondary';

CREATE TABLE epistemic_backfill_state (
    name TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    cursor_rowid INTEGER NOT NULL DEFAULT 0,
    processed INTEGER NOT NULL DEFAULT 0,
    updated INTEGER NOT NULL DEFAULT 0,
    integrity_warnings INTEGER NOT NULL DEFAULT 0,
    completed INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE situation_integrity_flags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    situation_id TEXT NOT NULL,
    flag_type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'review',
    details TEXT NOT NULL DEFAULT '{}',
    method TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'review',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(situation_id, flag_type, method),
    FOREIGN KEY(situation_id) REFERENCES situations(id) ON DELETE CASCADE
);

CREATE INDEX idx_integrity_flags_status
ON situation_integrity_flags(status, severity, updated_at DESC);

CREATE TABLE claim_extraction_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_version_id INTEGER NOT NULL,
    method TEXT NOT NULL,
    version TEXT NOT NULL,
    outcome TEXT NOT NULL,
    claims_extracted INTEGER NOT NULL DEFAULT 0,
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(document_version_id, method, version),
    FOREIGN KEY(document_version_id)
      REFERENCES document_versions(id) ON DELETE CASCADE
);

CREATE INDEX idx_claims_extraction_version
ON claims(extraction_version, created_at);
