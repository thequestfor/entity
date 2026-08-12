ALTER TABLE source_policies
ADD COLUMN article_acquisition_mode TEXT NOT NULL DEFAULT 'feed-only';
ALTER TABLE source_policies
ADD COLUMN article_hosts TEXT NOT NULL DEFAULT '[]';
ALTER TABLE source_policies
ADD COLUMN article_max_bytes INTEGER NOT NULL DEFAULT 0;
ALTER TABLE source_policies
ADD COLUMN article_requests_per_cycle INTEGER NOT NULL DEFAULT 0;
ALTER TABLE source_policies
ADD COLUMN article_excerpt_display INTEGER NOT NULL DEFAULT 0;

CREATE TABLE article_acquisition_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL,
    document_version_id INTEGER NOT NULL,
    source_id TEXT NOT NULL,
    article_url TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    priority REAL NOT NULL DEFAULT 0.5,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT NOT NULL,
    lease_expires_at TEXT,
    last_error TEXT NOT NULL DEFAULT '',
    policy_version TEXT NOT NULL,
    method TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(document_version_id,method),
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE,
    FOREIGN KEY(document_version_id) REFERENCES document_versions(id),
    FOREIGN KEY(source_id) REFERENCES sources(id)
);

CREATE INDEX idx_article_acquisition_tasks_due
ON article_acquisition_tasks(status,next_attempt_at,priority DESC,id);

CREATE TABLE article_content_captures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL,
    document_version_id INTEGER NOT NULL,
    source_id TEXT NOT NULL,
    original_url TEXT NOT NULL,
    final_url TEXT NOT NULL,
    content_scope TEXT NOT NULL,
    normalized_text TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    byline TEXT NOT NULL DEFAULT '',
    published_at TEXT,
    modified_at TEXT,
    content_hash TEXT NOT NULL,
    word_count INTEGER NOT NULL DEFAULT 0,
    http_etag TEXT NOT NULL DEFAULT '',
    http_last_modified TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    extractor TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    retention_expires_at TEXT,
    captured_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(document_version_id,content_hash,extractor),
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE,
    FOREIGN KEY(document_version_id) REFERENCES document_versions(id),
    FOREIGN KEY(source_id) REFERENCES sources(id)
);

CREATE INDEX idx_article_content_captures_document
ON article_content_captures(document_id,captured_at DESC,id DESC);

CREATE TABLE article_extraction_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    status TEXT NOT NULL,
    http_status INTEGER,
    response_bytes INTEGER NOT NULL DEFAULT 0,
    final_url TEXT NOT NULL DEFAULT '',
    error_code TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL,
    finished_at TEXT,
    FOREIGN KEY(task_id) REFERENCES article_acquisition_tasks(id) ON DELETE CASCADE
);

CREATE TABLE article_framing_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_capture_id INTEGER NOT NULL,
    document_id TEXT NOT NULL,
    publisher_key TEXT NOT NULL,
    dimension TEXT NOT NULL,
    direction TEXT NOT NULL DEFAULT 'present',
    strength REAL NOT NULL,
    confidence REAL NOT NULL,
    evidence_span TEXT NOT NULL,
    evidence_start INTEGER NOT NULL,
    evidence_end INTEGER NOT NULL,
    explanation TEXT NOT NULL,
    method TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    input_hash TEXT NOT NULL,
    evidence_cutoff_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(article_capture_id,dimension,evidence_start,evidence_end,method),
    FOREIGN KEY(article_capture_id) REFERENCES article_content_captures(id) ON DELETE CASCADE,
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE INDEX idx_article_framing_observations_publisher
ON article_framing_observations(publisher_key,dimension,created_at DESC);

CREATE TABLE article_framing_assessments (
    article_capture_id INTEGER PRIMARY KEY,
    publisher_key TEXT NOT NULL,
    dimension_scores TEXT NOT NULL DEFAULT '{}',
    evidence_count INTEGER NOT NULL DEFAULT 0,
    confidence REAL NOT NULL DEFAULT 0.0,
    status TEXT NOT NULL,
    method TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(article_capture_id) REFERENCES article_content_captures(id) ON DELETE CASCADE
);

CREATE TABLE event_publisher_comparisons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    world_event_id TEXT NOT NULL,
    publisher_keys TEXT NOT NULL,
    shared_claims TEXT NOT NULL DEFAULT '[]',
    divergent_claims TEXT NOT NULL DEFAULT '[]',
    framing_dimensions TEXT NOT NULL DEFAULT '{}',
    source_count INTEGER NOT NULL,
    evidence_cutoff_at TEXT NOT NULL,
    status TEXT NOT NULL,
    method TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(world_event_id,input_hash,method),
    FOREIGN KEY(world_event_id) REFERENCES world_events(id) ON DELETE CASCADE
);

CREATE TABLE publisher_coverage_windows (
    publisher_key TEXT NOT NULL,
    topic TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    eligible_event_count INTEGER NOT NULL DEFAULT 0,
    covered_event_count INTEGER NOT NULL DEFAULT 0,
    peer_event_count INTEGER NOT NULL DEFAULT 0,
    source_healthy INTEGER NOT NULL DEFAULT 0,
    acquisition_coverage REAL NOT NULL DEFAULT 0.0,
    selection_signal REAL,
    status TEXT NOT NULL,
    method TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(publisher_key,topic,window_start,window_end)
);

CREATE TABLE intelligence_model_result_cache (
    input_hash TEXT NOT NULL,
    lane TEXT NOT NULL,
    operation TEXT NOT NULL,
    response_json TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    last_used_at TEXT NOT NULL,
    hit_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(input_hash,lane,operation)
);

INSERT OR IGNORE INTO intelligence_feature_gates
(feature,status,reason,updated_at) VALUES
('article_full_text','shadow','Policy-approved sources only',datetime('now')),
('semantic_framing_v2','shadow','Awaiting literal-span and symmetry evaluation',datetime('now')),
('event_framing_comparison','shadow','Awaiting multi-publisher replay evaluation',datetime('now')),
('selection_framing_v2','shadow','Awaiting coverage and outage evaluation',datetime('now'));
