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

    def add_planner_decision(
        self,
        input_text,
        channel,
        intent,
        confidence=0,
        tools=None,
        reason="",
        confirmation_required=False,
        outcome="planned",
        response="",
        metadata=None,
        decision_id=None
    ):
        decision_id = decision_id or str(uuid4())
        now = utc_now()

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO planner_decisions (
                    id,
                    input_text,
                    channel,
                    intent,
                    confidence,
                    tools,
                    reason,
                    confirmation_required,
                    outcome,
                    response,
                    metadata,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision_id,
                    input_text,
                    channel,
                    intent,
                    float(confidence or 0),
                    self._json(tools or []),
                    reason,
                    1 if confirmation_required else 0,
                    outcome,
                    response,
                    self._json(metadata or {}),
                    now,
                    now
                )
            )

        return decision_id

    def update_planner_decision(
        self,
        decision_id,
        outcome=None,
        response=None,
        metadata=None
    ):
        updates = []
        params = []

        if outcome is not None:
            updates.append("outcome = ?")
            params.append(outcome)

        if response is not None:
            updates.append("response = ?")
            params.append(response)

        if metadata is not None:
            updates.append("metadata = ?")
            params.append(self._json(metadata))

        if not updates:
            return

        updates.append("updated_at = ?")
        params.append(utc_now())
        params.append(decision_id)

        with self._connect() as conn:
            conn.execute(
                f"""
                UPDATE planner_decisions
                SET {", ".join(updates)}
                WHERE id = ?
                """,
                params
            )

    def recent_planner_decisions(self, limit=10):
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM planner_decisions
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,)
            ).fetchall()

        return [self._planner_decision_from_row(row) for row in rows]

    def last_planner_decision(self):
        decisions = self.recent_planner_decisions(limit=1)

        if not decisions:
            return None

        return decisions[0]

    def count_planner_decisions(self):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM planner_decisions"
            ).fetchone()

        return row["count"]

    def add_autonomous_goal(
        self,
        name,
        priority=1,
        message="",
        reason="",
        confidence=0,
        outcome="selected",
        metadata=None,
        goal_id=None
    ):
        goal_id = goal_id or str(uuid4())
        now = utc_now()

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO autonomous_goals (
                    id,
                    name,
                    priority,
                    message,
                    reason,
                    confidence,
                    outcome,
                    metadata,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    goal_id,
                    name,
                    priority,
                    message,
                    reason,
                    float(confidence or 0),
                    outcome,
                    self._json(metadata or {}),
                    now,
                    now
                )
            )

        return goal_id

    def recent_autonomous_goals(self, limit=10):
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM autonomous_goals
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,)
            ).fetchall()

        return [self._autonomous_goal_from_row(row) for row in rows]

    def count_autonomous_goals(self):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM autonomous_goals"
            ).fetchone()

        return row["count"]

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

    def get_geocode(self, query, provider):
        key = self._geocode_key(query)

        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM geocodes
                WHERE query = ?
                  AND provider = ?
                """,
                (
                    key,
                    provider
                )
            ).fetchone()

            if not row:
                return None

            conn.execute(
                """
                UPDATE geocodes
                SET last_accessed_at = ?
                WHERE query = ?
                  AND provider = ?
                """,
                (
                    utc_now(),
                    key,
                    provider
                )
            )

        return {
            "query": row["query"],
            "longitude": row["longitude"],
            "latitude": row["latitude"],
            "provider": row["provider"],
            "formatted": row["formatted"],
            "created_at": row["created_at"],
            "last_accessed_at": row["last_accessed_at"]
        }

    def set_geocode(
        self,
        query,
        provider,
        longitude,
        latitude,
        formatted=""
    ):
        key = self._geocode_key(query)
        now = utc_now()

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO geocodes (
                    query,
                    longitude,
                    latitude,
                    provider,
                    formatted,
                    created_at,
                    last_accessed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(query)
                DO UPDATE SET
                    longitude = excluded.longitude,
                    latitude = excluded.latitude,
                    provider = excluded.provider,
                    formatted = excluded.formatted,
                    last_accessed_at = excluded.last_accessed_at
                """,
                (
                    key,
                    longitude,
                    latitude,
                    provider,
                    formatted,
                    now,
                    now
                )
            )

    def count_geocodes(self):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM geocodes"
            ).fetchone()

        return row["count"]

    def count_memories(self, kind=None, source=None):
        query = "SELECT COUNT(*) AS count FROM memories"
        clauses = []
        params = []

        if kind:
            clauses.append("kind = ?")
            params.append(kind)

        if source:
            clauses.append("source = ?")
            params.append(source)

        if clauses:
            query += " WHERE " + " AND ".join(clauses)

        with self._connect() as conn:
            row = conn.execute(query, params).fetchone()

        return row["count"]

    def get_state(self, key, default=None):
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT value
                FROM state
                WHERE key = ?
                """,
                (key,)
            ).fetchone()

        if not row:
            return default

        return json.loads(row["value"])

    def set_state(self, key, value):
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO state (
                    key,
                    value,
                    updated_at
                )
                VALUES (?, ?, ?)
                ON CONFLICT(key)
                DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (
                    key,
                    json.dumps(value),
                    utc_now()
                )
            )

    def _geocode_key(self, query):
        return " ".join(query.lower().strip().split())

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

    def _planner_decision_from_row(self, row):
        item = dict(row)
        item["tools"] = json.loads(item.get("tools") or "[]")
        item["metadata"] = json.loads(item.get("metadata") or "{}")
        item["confirmation_required"] = bool(
            item.get("confirmation_required")
        )
        return item

    def _autonomous_goal_from_row(self, row):
        item = dict(row)
        item["metadata"] = json.loads(item.get("metadata") or "{}")
        return item

    def _task_from_row(self, row):
        item = dict(row)
        item["metadata"] = json.loads(item.get("metadata") or "{}")
        return item

    def _json(self, value):
        return json.dumps(value, default=str)

    def _fts_query(self, query):
        terms = [
            term.replace('"', "")
            for term in query.split()
            if len(term) > 2
        ]

        if not terms:
            return query

        return " OR ".join(f'"{term}"' for term in terms)
