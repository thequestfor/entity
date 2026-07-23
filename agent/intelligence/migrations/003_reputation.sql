ALTER TABLE documents ADD COLUMN publisher_key TEXT NOT NULL DEFAULT '';
ALTER TABLE documents ADD COLUMN publisher_label TEXT NOT NULL DEFAULT '';

UPDATE documents
SET publisher_key = CASE
    WHEN json_extract(metadata, '$.platform') = 'telegram'
         AND json_extract(metadata, '$.channel_username') IS NOT NULL
      THEN 'telegram:' || lower(json_extract(metadata, '$.channel_username'))
    WHEN json_extract(metadata, '$.platform') = 'x'
         AND json_extract(metadata, '$.author_username') IS NOT NULL
      THEN 'x:' || lower(json_extract(metadata, '$.author_username'))
    WHEN json_extract(metadata, '$.domain') IS NOT NULL
      THEN 'domain:' || lower(json_extract(metadata, '$.domain'))
    ELSE source_id
END,
publisher_label = CASE
    WHEN json_extract(metadata, '$.channel_username') IS NOT NULL
      THEN '@' || json_extract(metadata, '$.channel_username')
    WHEN json_extract(metadata, '$.author_username') IS NOT NULL
      THEN '@' || json_extract(metadata, '$.author_username')
    WHEN json_extract(metadata, '$.domain') IS NOT NULL
      THEN json_extract(metadata, '$.domain')
    ELSE source_id
END;

CREATE INDEX idx_documents_publisher_published
ON documents(publisher_key, published_at DESC);

CREATE TABLE publisher_reputation (
    publisher_key TEXT PRIMARY KEY,
    publisher_label TEXT NOT NULL,
    source_id TEXT NOT NULL,
    baseline_credibility REAL NOT NULL,
    learned_credibility REAL NOT NULL,
    confirmed_count INTEGER NOT NULL DEFAULT 0,
    contradicted_count INTEGER NOT NULL DEFAULT 0,
    deleted_unverified_count INTEGER NOT NULL DEFAULT 0,
    early_confirmation_count INTEGER NOT NULL DEFAULT 0,
    evaluated_count INTEGER NOT NULL DEFAULT 0,
    last_evaluated_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(source_id) REFERENCES sources(id)
);

CREATE TABLE publisher_outcomes (
    document_id TEXT PRIMARY KEY,
    publisher_key TEXT NOT NULL,
    outcome TEXT NOT NULL,
    reason TEXT NOT NULL,
    corroborating_publishers TEXT NOT NULL DEFAULT '[]',
    evaluated_at TEXT NOT NULL,
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE,
    FOREIGN KEY(publisher_key) REFERENCES publisher_reputation(publisher_key)
);

CREATE TABLE publisher_reputation_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    publisher_key TEXT NOT NULL,
    previous_credibility REAL NOT NULL,
    learned_credibility REAL NOT NULL,
    confirmed_count INTEGER NOT NULL,
    contradicted_count INTEGER NOT NULL,
    deleted_unverified_count INTEGER NOT NULL,
    early_confirmation_count INTEGER NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(publisher_key) REFERENCES publisher_reputation(publisher_key)
);

CREATE INDEX idx_publisher_reputation_learned
ON publisher_reputation(learned_credibility DESC);

CREATE INDEX idx_publisher_outcomes_publisher
ON publisher_outcomes(publisher_key, evaluated_at DESC);
