CREATE TABLE situations (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    confidence REAL NOT NULL DEFAULT 0.0,
    latitude REAL,
    longitude REAL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX idx_situations_status_updated
ON situations(status, updated_at DESC);

CREATE INDEX idx_situations_category_updated
ON situations(category, updated_at DESC);

CREATE TABLE situation_documents (
    situation_id TEXT NOT NULL,
    document_id TEXT NOT NULL UNIQUE,
    relevance REAL NOT NULL DEFAULT 1.0,
    linked_at TEXT NOT NULL,
    PRIMARY KEY(situation_id, document_id),
    FOREIGN KEY(situation_id) REFERENCES situations(id) ON DELETE CASCADE,
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE TABLE claims (
    id TEXT PRIMARY KEY,
    situation_id TEXT NOT NULL,
    subject TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object TEXT NOT NULL,
    normalized_object TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    confidence REAL NOT NULL DEFAULT 0.0,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(situation_id, subject, predicate, normalized_object),
    FOREIGN KEY(situation_id) REFERENCES situations(id) ON DELETE CASCADE
);

CREATE INDEX idx_claims_situation_status
ON claims(situation_id, status, predicate);

CREATE TABLE claim_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL,
    document_version_id INTEGER NOT NULL,
    stance TEXT NOT NULL DEFAULT 'supports',
    source_weight REAL NOT NULL DEFAULT 0.5,
    excerpt TEXT NOT NULL DEFAULT '',
    observed_at TEXT NOT NULL,
    UNIQUE(claim_id, document_version_id, stance),
    FOREIGN KEY(claim_id) REFERENCES claims(id) ON DELETE CASCADE,
    FOREIGN KEY(document_version_id) REFERENCES document_versions(id)
);

CREATE INDEX idx_claim_evidence_claim
ON claim_evidence(claim_id, observed_at DESC);

CREATE TABLE document_analysis (
    document_id TEXT PRIMARY KEY,
    document_version_id INTEGER NOT NULL,
    situation_id TEXT NOT NULL,
    method TEXT NOT NULL,
    analyzed_at TEXT NOT NULL,
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE,
    FOREIGN KEY(document_version_id) REFERENCES document_versions(id),
    FOREIGN KEY(situation_id) REFERENCES situations(id) ON DELETE CASCADE
);

CREATE TABLE situation_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    situation_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    status TEXT NOT NULL,
    confidence REAL NOT NULL,
    evidence_count INTEGER NOT NULL,
    claim_count INTEGER NOT NULL,
    contested_count INTEGER NOT NULL,
    snapshot TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(situation_id, version),
    FOREIGN KEY(situation_id) REFERENCES situations(id) ON DELETE CASCADE
);

CREATE TABLE analysis_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    outcome TEXT NOT NULL DEFAULT 'running',
    documents_analyzed INTEGER NOT NULL DEFAULT 0,
    situations_created INTEGER NOT NULL DEFAULT 0,
    claims_created INTEGER NOT NULL DEFAULT 0,
    error TEXT NOT NULL DEFAULT ''
);

CREATE TABLE briefings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    situation_count INTEGER NOT NULL,
    content TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX idx_briefings_created
ON briefings(created_at DESC);
