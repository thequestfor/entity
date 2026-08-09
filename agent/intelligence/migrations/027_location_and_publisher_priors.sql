CREATE TABLE document_location_inferences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL,
    document_version_id INTEGER NOT NULL,
    location_label TEXT NOT NULL DEFAULT '',
    country_code TEXT NOT NULL DEFAULT '',
    country_name TEXT NOT NULL DEFAULT '',
    latitude REAL,
    longitude REAL,
    precision_km REAL,
    confidence REAL NOT NULL DEFAULT 0.0,
    evidence_excerpt TEXT NOT NULL DEFAULT '',
    candidate_source TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    method TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(document_version_id, method),
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE,
    FOREIGN KEY(document_version_id) REFERENCES document_versions(id)
);

CREATE INDEX idx_document_location_inferences_status
ON document_location_inferences(status, updated_at DESC);

CREATE INDEX idx_document_location_inferences_document
ON document_location_inferences(document_id, document_version_id DESC);

CREATE TABLE publisher_profile_priors (
    publisher_key TEXT PRIMARY KEY,
    baseline_credibility REAL NOT NULL,
    framing_signal REAL NOT NULL DEFAULT 0.0,
    affiliation TEXT NOT NULL DEFAULT '',
    rationale TEXT NOT NULL DEFAULT '',
    configured_by TEXT NOT NULL DEFAULT 'configuration',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
