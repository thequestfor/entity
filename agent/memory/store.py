import json
import sqlite3
from pathlib import Path
from uuid import uuid4

from agent.events import Event, utc_now


DEFAULT_DB = Path("agent/entity_memory.db")
SCHEMA = Path(__file__).with_name("schema.sql")


class MemoryStore:
    def __init__(self, path=DEFAULT_DB):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.executescript(SCHEMA.read_text())

    def add_memory(
        self,
        kind,
        content,
        source="system",
        importance=1,
        metadata=None
    ):
        now = utc_now()

        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO memories (
                    kind,
                    content,
                    source,
                    importance,
                    metadata,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    kind,
                    content,
                    source,
                    importance,
                    json.dumps(metadata or {}),
                    now,
                    now
                )
            )

            return cursor.lastrowid

    def add_candidate(self, candidate, metadata=None):
        if not candidate.should_remember:
            return None

        payload = candidate.to_memory_kwargs()
        candidate_metadata = payload["metadata"]
        candidate_metadata.update(metadata or {})

        return self.add_memory(
            payload["kind"],
            payload["content"],
            source=payload["source"],
            importance=payload["importance"],
            metadata=candidate_metadata
        )

    def add_conversation(self, user_text, entity_text, state=None):
        now = utc_now()

        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO conversations (
                    user_text,
                    entity_text,
                    state,
                    created_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    user_text,
                    entity_text,
                    json.dumps(state or {}),
                    now
                )
            )

            return cursor.lastrowid

    def add_event(self, event):
        if isinstance(event, Event):
            event = event.to_dict()

        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO events (
                    id,
                    source,
                    type,
                    priority,
                    payload,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event["id"],
                    event["source"],
                    event["type"],
                    event.get("priority", 0),
                    json.dumps(event.get("payload", {})),
                    event["created_at"]
                )
            )

    def add_task(
        self,
        title,
        message,
        due_at,
        kind="reminder",
        priority=7,
        source="user",
        metadata=None,
        task_id=None
    ):
        task_id = task_id or str(uuid4())

        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO tasks (
                    id,
                    kind,
                    title,
                    message,
                    status,
                    due_at,
                    priority,
                    source,
                    metadata,
                    created_at,
                    completed_at
                )
                VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, NULL)
                """,
                (
                    task_id,
                    kind,
                    title,
                    message,
                    due_at,
                    priority,
                    source,
                    json.dumps(metadata or {}),
                    utc_now()
                )
            )

        return task_id

    def pending_tasks(self):
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM tasks
                WHERE status = 'pending'
                ORDER BY due_at ASC
                """
            ).fetchall()

        return [
            self._task_from_row(row)
            for row in rows
        ]

    def complete_task(self, task_id):
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE tasks
                SET status = 'completed',
                    completed_at = ?
                WHERE id = ?
                """,
                (
                    utc_now(),
                    task_id
                )
            )

    def list_memories(self, kind=None, limit=20):
        query = """
            SELECT *
            FROM memories
        """
        params = []

        if kind:
            query += " WHERE kind = ?"
            params.append(kind)

        query += " ORDER BY importance DESC, created_at DESC LIMIT ?"
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()

        return [self._memory_from_row(row) for row in rows]

    def recent_conversations(self, limit=5):
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM conversations
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,)
            ).fetchall()

        return [dict(row) for row in rows]

    def search(self, query, limit=8):
        if not query.strip():
            return self.list_memories(limit=limit)

        with self._connect() as conn:
            try:
                rows = conn.execute(
                    """
                    SELECT
                        memories.*,
                        bm25(memory_fts) AS rank
                    FROM memory_fts
                    JOIN memories ON memories.id = memory_fts.rowid
                    WHERE memory_fts MATCH ?
                    ORDER BY rank, memories.importance DESC
                    LIMIT ?
                    """,
                    (self._fts_query(query), limit)
                ).fetchall()
            except sqlite3.OperationalError:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM memories
                    WHERE lower(content) LIKE ?
                    ORDER BY importance DESC, created_at DESC
                    LIMIT ?
                    """,
                    (f"%{query.lower()}%", limit)
                ).fetchall()

            ids = [row["id"] for row in rows]

            if ids:
                placeholders = ",".join("?" for _ in ids)
                conn.execute(
                    f"""
                    UPDATE memories
                    SET last_accessed_at = ?
                    WHERE id IN ({placeholders})
                    """,
                    [utc_now(), *ids]
                )

        return [self._memory_from_row(row) for row in rows]

    def recall_context(self, query, limit=8):
        memories = self.search(query, limit=limit)
        conversations = self.recent_conversations(limit=3)

        return {
            "relevant_memories": memories,
            "recent_conversations": conversations
        }

    def _memory_from_row(self, row):
        item = dict(row)
        item["metadata"] = json.loads(item.get("metadata") or "{}")
        return item

    def _task_from_row(self, row):
        item = dict(row)
        item["metadata"] = json.loads(item.get("metadata") or "{}")
        return item

    def _fts_query(self, query):
        terms = [
            term.replace('"', "")
            for term in query.split()
            if len(term) > 2
        ]

        if not terms:
            return query

        return " OR ".join(f'"{term}"' for term in terms)
