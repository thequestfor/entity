CREATE TABLE forecasts (
    id TEXT PRIMARY KEY,
    situation_id TEXT NOT NULL,
    question TEXT NOT NULL,
    predicted_outcome TEXT NOT NULL,
    probability REAL NOT NULL,
    target_at TEXT NOT NULL,
    resolution_criteria TEXT NOT NULL,
    rationale TEXT NOT NULL DEFAULT '',
    evidence TEXT NOT NULL DEFAULT '[]',
    model TEXT NOT NULL DEFAULT '',
    method TEXT NOT NULL DEFAULT 'thinking-forecast-v1',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    actual_outcome INTEGER,
    resolution_summary TEXT NOT NULL DEFAULT '',
    resolution_evidence TEXT NOT NULL DEFAULT '[]',
    brier_score REAL,
    resolution_attempts INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(situation_id) REFERENCES situations(id) ON DELETE CASCADE
);

CREATE INDEX idx_forecasts_status_target ON forecasts(status, target_at);
CREATE INDEX idx_forecasts_situation_created ON forecasts(situation_id, created_at DESC);
