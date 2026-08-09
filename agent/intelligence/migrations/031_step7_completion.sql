ALTER TABLE publisher_epistemic_profiles
ADD COLUMN timeliness_score REAL NOT NULL DEFAULT 0.5;
ALTER TABLE publisher_epistemic_profiles
ADD COLUMN timeliness_samples INTEGER NOT NULL DEFAULT 0;

ALTER TABLE publisher_assessments
ADD COLUMN timeliness_score REAL NOT NULL DEFAULT 0.5;

ALTER TABLE publisher_assessment_history
ADD COLUMN attribution_quality REAL NOT NULL DEFAULT 0.5;
ALTER TABLE publisher_assessment_history
ADD COLUMN revision_discipline REAL NOT NULL DEFAULT 0.5;
ALTER TABLE publisher_assessment_history
ADD COLUMN independence_confidence REAL NOT NULL DEFAULT 0.5;
ALTER TABLE publisher_assessment_history
ADD COLUMN timeliness_score REAL NOT NULL DEFAULT 0.5;
ALTER TABLE publisher_assessment_history
ADD COLUMN observed_framing REAL NOT NULL DEFAULT 0.0;

CREATE TABLE publisher_dimension_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    publisher_key TEXT NOT NULL,
    dimension TEXT NOT NULL,
    scope_kind TEXT NOT NULL DEFAULT 'global',
    scope_value TEXT NOT NULL DEFAULT '',
    value REAL NOT NULL,
    sample_count INTEGER NOT NULL DEFAULT 0,
    evidence_basis TEXT NOT NULL,
    evidence_ids TEXT NOT NULL DEFAULT '[]',
    method TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    evidence_cutoff_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(publisher_key,dimension,scope_kind,scope_value,input_hash),
    FOREIGN KEY(publisher_key) REFERENCES publisher_reputation(publisher_key)
);

CREATE INDEX idx_publisher_dimension_observations_lookup
ON publisher_dimension_observations(publisher_key,dimension,created_at DESC);

CREATE TABLE public_media_derivations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL,
    document_version_id INTEGER NOT NULL,
    input_hash TEXT NOT NULL,
    media_hash TEXT NOT NULL,
    media_type TEXT NOT NULL DEFAULT '',
    mime_type TEXT NOT NULL DEFAULT '',
    byte_size INTEGER NOT NULL DEFAULT 0,
    derivation_kind TEXT NOT NULL,
    derived_text TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 0.0,
    evidence_locator TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    method TEXT NOT NULL,
    error_code TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(document_version_id,media_hash,derivation_kind,method),
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE,
    FOREIGN KEY(document_version_id) REFERENCES document_versions(id)
);

CREATE INDEX idx_public_media_derivations_status
ON public_media_derivations(status,updated_at,document_version_id);

CREATE TABLE public_media_derivation_state (
    lane TEXT PRIMARY KEY,
    cursor_version_id INTEGER NOT NULL DEFAULT 0,
    processed INTEGER NOT NULL DEFAULT 0,
    completed INTEGER NOT NULL DEFAULT 0,
    unavailable INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);
