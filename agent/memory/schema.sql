CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT NOT NULL,
    importance INTEGER NOT NULL DEFAULT 1,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_accessed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_memories_kind
ON memories(kind);

CREATE INDEX IF NOT EXISTS idx_memories_importance
ON memories(importance);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    type TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0,
    payload TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_created_at
ON events(created_at);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_text TEXT NOT NULL,
    entity_text TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts
USING fts5(
    content,
    kind,
    source,
    content='memories',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS memories_ai
AFTER INSERT ON memories
BEGIN
    INSERT INTO memory_fts(rowid, content, kind, source)
    VALUES (new.id, new.content, new.kind, new.source);
END;

CREATE TRIGGER IF NOT EXISTS memories_ad
AFTER DELETE ON memories
BEGIN
    INSERT INTO memory_fts(memory_fts, rowid, content, kind, source)
    VALUES ('delete', old.id, old.content, old.kind, old.source);
END;

CREATE TRIGGER IF NOT EXISTS memories_au
AFTER UPDATE ON memories
BEGIN
    INSERT INTO memory_fts(memory_fts, rowid, content, kind, source)
    VALUES ('delete', old.id, old.content, old.kind, old.source);

    INSERT INTO memory_fts(rowid, content, kind, source)
    VALUES (new.id, new.content, new.kind, new.source);
END;
