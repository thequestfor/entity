ALTER TABLE situations ADD COLUMN worldview TEXT NOT NULL DEFAULT '';
ALTER TABLE situations ADD COLUMN worldview_confidence REAL NOT NULL DEFAULT 0.0;
ALTER TABLE situations ADD COLUMN worldview_stance TEXT NOT NULL DEFAULT 'uncertain';
ALTER TABLE situations ADD COLUMN worldview_method TEXT NOT NULL DEFAULT '';
ALTER TABLE situations ADD COLUMN worldview_updated_at TEXT;

CREATE TABLE worldview_syntheses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    situation_id TEXT NOT NULL,
    conclusion TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.0,
    stance TEXT NOT NULL DEFAULT 'uncertain',
    implications TEXT NOT NULL DEFAULT '[]',
    contradictions TEXT NOT NULL DEFAULT '[]',
    open_questions TEXT NOT NULL DEFAULT '[]',
    evidence TEXT NOT NULL DEFAULT '[]',
    model TEXT NOT NULL DEFAULT '',
    method TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY(situation_id) REFERENCES situations(id) ON DELETE CASCADE
);

CREATE INDEX idx_worldview_syntheses_situation
ON worldview_syntheses(situation_id, created_at DESC);
