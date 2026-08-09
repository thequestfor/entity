CREATE TABLE document_enrichments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL,
    document_version_id INTEGER NOT NULL,
    input_hash TEXT NOT NULL,
    detected_language TEXT NOT NULL DEFAULT 'und',
    translated_title TEXT NOT NULL DEFAULT '',
    translated_summary TEXT NOT NULL DEFAULT '',
    translated_content TEXT NOT NULL DEFAULT '',
    enriched_category TEXT NOT NULL DEFAULT '',
    event_time TEXT,
    location_label TEXT NOT NULL DEFAULT '',
    country_name TEXT NOT NULL DEFAULT '',
    actors TEXT NOT NULL DEFAULT '[]',
    extracted_urls TEXT NOT NULL DEFAULT '[]',
    quoted_sources TEXT NOT NULL DEFAULT '[]',
    forward_origin_key TEXT NOT NULL DEFAULT '',
    forward_origin_label TEXT NOT NULL DEFAULT '',
    media_evidence TEXT NOT NULL DEFAULT '{}',
    content_fingerprint TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 0.0,
    evidence_spans TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL,
    method TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(document_version_id, method),
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE,
    FOREIGN KEY(document_version_id) REFERENCES document_versions(id)
);

CREATE INDEX idx_document_enrichments_status
ON document_enrichments(status, updated_at DESC);

CREATE INDEX idx_document_enrichments_fingerprint
ON document_enrichments(content_fingerprint, document_id)
WHERE content_fingerprint!='';

CREATE TABLE open_source_enrichment_state (
    lane TEXT PRIMARY KEY,
    cursor_version_id INTEGER NOT NULL DEFAULT 0,
    processed INTEGER NOT NULL DEFAULT 0,
    translated INTEGER NOT NULL DEFAULT 0,
    categorized INTEGER NOT NULL DEFAULT 0,
    attributed INTEGER NOT NULL DEFAULT 0,
    relationships INTEGER NOT NULL DEFAULT 0,
    completed INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);

ALTER TABLE world_event_observations
ADD COLUMN enrichment_updated_at TEXT NOT NULL DEFAULT '';
