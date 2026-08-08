ALTER TABLE documents
ADD COLUMN reporting_family_key TEXT NOT NULL DEFAULT '';

ALTER TABLE situations
ADD COLUMN merged_into_id TEXT;

CREATE TABLE document_features (
    document_id TEXT PRIMARY KEY,
    feature_version TEXT NOT NULL,
    normalized_title TEXT NOT NULL DEFAULT '',
    occurred_at TEXT NOT NULL,
    entity_keys TEXT NOT NULL DEFAULT '[]',
    location_key TEXT NOT NULL DEFAULT '',
    lexical_signature TEXT NOT NULL DEFAULT '[]',
    content_fingerprint TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE INDEX idx_document_features_occurred
ON document_features(occurred_at DESC);

CREATE INDEX idx_document_features_fingerprint
ON document_features(content_fingerprint);

CREATE TABLE document_embeddings (
    document_id TEXT NOT NULL,
    model TEXT NOT NULL,
    dimensions INTEGER NOT NULL,
    vector TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(document_id, model),
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE TABLE situation_entities (
    situation_id TEXT NOT NULL,
    entity_key TEXT NOT NULL,
    entity_type TEXT NOT NULL DEFAULT 'named',
    mention_count INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(situation_id, entity_key),
    FOREIGN KEY(situation_id) REFERENCES situations(id) ON DELETE CASCADE
);

CREATE INDEX idx_situation_entities_key
ON situation_entities(entity_key, situation_id);

CREATE TABLE document_relationships (
    left_document_id TEXT NOT NULL,
    right_document_id TEXT NOT NULL,
    relationship TEXT NOT NULL,
    score REAL NOT NULL DEFAULT 0.0,
    method TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(left_document_id, right_document_id, relationship),
    FOREIGN KEY(left_document_id) REFERENCES documents(id) ON DELETE CASCADE,
    FOREIGN KEY(right_document_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE TABLE situation_merge_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_situation_id TEXT NOT NULL,
    target_situation_id TEXT NOT NULL,
    score REAL NOT NULL,
    components TEXT NOT NULL DEFAULT '{}',
    vetoes TEXT NOT NULL DEFAULT '[]',
    decision TEXT NOT NULL DEFAULT 'review',
    method TEXT NOT NULL,
    created_at TEXT NOT NULL,
    reviewed_at TEXT,
    UNIQUE(source_situation_id, target_situation_id, method),
    FOREIGN KEY(source_situation_id) REFERENCES situations(id),
    FOREIGN KEY(target_situation_id) REFERENCES situations(id)
);

CREATE INDEX idx_merge_candidates_decision_score
ON situation_merge_candidates(decision, score DESC);

CREATE TABLE situation_merge_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_situation_id TEXT NOT NULL,
    target_situation_id TEXT NOT NULL,
    score REAL NOT NULL,
    reason TEXT NOT NULL,
    snapshot TEXT NOT NULL DEFAULT '{}',
    reversible INTEGER NOT NULL DEFAULT 1,
    method TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE clustering_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mode TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    documents_scanned INTEGER NOT NULL DEFAULT 0,
    auto_links INTEGER NOT NULL DEFAULT 0,
    review_candidates INTEGER NOT NULL DEFAULT 0,
    separate_situations INTEGER NOT NULL DEFAULT 0,
    error TEXT NOT NULL DEFAULT ''
);
