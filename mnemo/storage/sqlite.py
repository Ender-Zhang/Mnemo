from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable

from ..core.ids import new_id
from ..core.jsonutil import dumps, loads


SCHEMA_VERSION = 1


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> bool:
        result = super().__exit__(exc_type, exc_value, traceback)
        self.close()
        return result


class StateStore:
    def __init__(self, state_dir: str | Path):
        self.state_dir = Path(state_dir).expanduser().resolve()
        self.db_path = self.state_dir / "state.db"

    def connect(self) -> sqlite3.Connection:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, factory=ClosingConnection)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def initialize(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        for child in ("wiki", "skills", "runs", "artifacts"):
            (self.state_dir / child).mkdir(parents=True, exist_ok=True)

        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS missions (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id),
                    status TEXT NOT NULL,
                    brief TEXT NOT NULL,
                    checkpoint_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id),
                    mission_id TEXT NOT NULL REFERENCES missions(id),
                    status TEXT NOT NULL,
                    input_text TEXT NOT NULL,
                    output_text TEXT,
                    created_at REAL NOT NULL,
                    completed_at REAL
                );

                CREATE TABLE IF NOT EXISTS run_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES runs(id),
                    seq INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    UNIQUE(run_id, seq)
                );

                CREATE TABLE IF NOT EXISTS tool_calls (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES runs(id),
                    provider TEXT NOT NULL,
                    provider_call_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    args_json TEXT NOT NULL,
                    risk TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT,
                    error_message TEXT,
                    started_at REAL NOT NULL,
                    ended_at REAL
                );

                CREATE TABLE IF NOT EXISTS working_notes (
                    id TEXT PRIMARY KEY,
                    mission_id TEXT NOT NULL REFERENCES missions(id),
                    run_id TEXT NOT NULL REFERENCES runs(id),
                    content TEXT NOT NULL,
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS memory_candidates (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES runs(id),
                    claim TEXT NOT NULL,
                    dimension TEXT,
                    scope TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    evidence_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS memory_pages (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    status TEXT NOT NULL,
                    source_candidate_id TEXT REFERENCES memory_candidates(id),
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS memory_links (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    weight REAL NOT NULL,
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS skills (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT NOT NULL,
                    body TEXT NOT NULL,
                    status TEXT NOT NULL,
                    source TEXT NOT NULL,
                    path TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tool_candidates (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES runs(id),
                    name TEXT NOT NULL,
                    spec_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS eval_cases (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES runs(id),
                    name TEXT NOT NULL,
                    case_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY,
                    mission_id TEXT NOT NULL REFERENCES missions(id),
                    run_id TEXT NOT NULL REFERENCES runs(id),
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_run_events_run ON run_events(run_id, seq);
                CREATE INDEX IF NOT EXISTS idx_memory_candidates_claim ON memory_candidates(claim);
                CREATE INDEX IF NOT EXISTS idx_memory_candidates_status ON memory_candidates(status);
                CREATE INDEX IF NOT EXISTS idx_memory_pages_title ON memory_pages(title);
                CREATE INDEX IF NOT EXISTS idx_memory_pages_content ON memory_pages(content);
                CREATE INDEX IF NOT EXISTS idx_memory_links_source ON memory_links(source_id);
                CREATE INDEX IF NOT EXISTS idx_skills_name ON skills(name);
                """
            )
            conn.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES(?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )
            _ensure_column(conn, "skills", "path", "TEXT")

    def create_conversation(self, title: str | None = None) -> str:
        now = time.time()
        conversation_id = new_id("conv")
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO conversations(id, title, created_at, updated_at) VALUES(?, ?, ?, ?)",
                (conversation_id, title, now, now),
            )
        return conversation_id

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT id, title, created_at, updated_at FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
        return dict(row) if row else None

    def create_mission(self, conversation_id: str, brief: str) -> str:
        now = time.time()
        mission_id = new_id("mis")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO missions(id, conversation_id, status, brief, checkpoint_json, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (mission_id, conversation_id, "active", brief, dumps({}), now, now),
            )
        return mission_id

    def get_mission(self, mission_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM missions WHERE id = ?", (mission_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["checkpoint"] = loads(result.pop("checkpoint_json"), {})
        return result

    def latest_active_mission(self, conversation_id: str) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT * FROM missions
                WHERE conversation_id = ? AND status = 'active'
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (conversation_id,),
            ).fetchone()

    def create_run(self, conversation_id: str, mission_id: str, input_text: str) -> str:
        now = time.time()
        run_id = new_id("run")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO runs(id, conversation_id, mission_id, status, input_text, created_at)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (run_id, conversation_id, mission_id, "running", input_text, now),
            )
        return run_id

    def complete_run(self, run_id: str, output_text: str, status: str = "completed") -> None:
        now = time.time()
        with self.connect() as conn:
            conn.execute(
                "UPDATE runs SET status = ?, output_text = ?, completed_at = ? WHERE id = ?",
                (status, output_text, now, run_id),
            )

    def update_mission_checkpoint(self, mission_id: str, checkpoint: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE missions SET checkpoint_json = ?, updated_at = ? WHERE id = ?",
                (dumps(checkpoint), time.time(), mission_id),
            )

    def append_event(self, run_id: str, event_type: str, payload: dict[str, Any]) -> int:
        now = time.time()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 AS next_seq FROM run_events WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            seq = int(row["next_seq"])
            conn.execute(
                "INSERT INTO run_events(run_id, seq, event_type, payload_json, created_at) VALUES(?, ?, ?, ?, ?)",
                (run_id, seq, event_type, dumps(payload), now),
            )
        return seq

    def record_tool_call(
        self,
        *,
        run_id: str,
        provider: str,
        provider_call_id: str,
        tool_name: str,
        args: dict[str, Any],
        risk: str,
        status: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        started_at: float | None = None,
        ended_at: float | None = None,
    ) -> str:
        call_id = new_id("tool")
        now = time.time()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO tool_calls(
                    id, run_id, provider, provider_call_id, tool_name, args_json, risk,
                    status, result_json, error_message, started_at, ended_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    call_id,
                    run_id,
                    provider,
                    provider_call_id,
                    tool_name,
                    dumps(args),
                    risk,
                    status,
                    dumps(result or {}),
                    error,
                    started_at or now,
                    ended_at or now,
                ),
            )
        return call_id

    def add_working_note(self, mission_id: str, run_id: str, content: str) -> str:
        note_id = new_id("note")
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO working_notes(id, mission_id, run_id, content, created_at) VALUES(?, ?, ?, ?, ?)",
                (note_id, mission_id, run_id, content, time.time()),
            )
        return note_id

    def add_memory_candidate(
        self,
        run_id: str,
        claim: str,
        *,
        dimension: str | None = None,
        scope: str = "global",
        confidence: float = 0.5,
        evidence: Iterable[dict[str, Any]] | None = None,
    ) -> str:
        candidate_id = new_id("mem")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_candidates(id, run_id, claim, dimension, scope, confidence, evidence_json, status, created_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate_id,
                    run_id,
                    claim,
                    dimension,
                    scope,
                    confidence,
                    dumps(list(evidence or [])),
                    "draft",
                    time.time(),
                ),
            )
        return candidate_id

    def search_memory_candidates(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        pattern = f"%{query}%"
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, claim, dimension, scope, confidence, status, evidence_json
                FROM memory_candidates
                WHERE claim LIKE ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (pattern, limit),
            ).fetchall()
        return [
            _memory_candidate_from_row(row)
            for row in rows
        ]

    def list_memory_candidates(self, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        sql = """
            SELECT id, run_id, claim, dimension, scope, confidence, status, evidence_json, created_at
            FROM memory_candidates
        """
        params: list[Any] = []
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_memory_candidate_from_row(row) for row in rows]

    def update_memory_candidate_status(self, candidate_id: str, status: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE memory_candidates SET status = ? WHERE id = ?",
                (status, candidate_id),
            )

    def update_memory_page_confidence(self, page_id: str, confidence: float) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE memory_pages SET confidence = ?, updated_at = ? WHERE id = ?",
                (confidence, time.time(), page_id),
            )

    def get_memory_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT id, run_id, claim, dimension, scope, confidence, status, evidence_json, created_at
                FROM memory_candidates
                WHERE id = ?
                """,
                (candidate_id,),
            ).fetchone()
        if not row:
            return None
        return _memory_candidate_from_row(row)

    def upsert_memory_page(
        self,
        title: str,
        content: str,
        *,
        scope: str = "global",
        source_candidate_id: str | None = None,
        confidence: float = 0.7,
        status: str = "active",
    ) -> str:
        now = time.time()
        with self.connect() as conn:
            existing = None
            if source_candidate_id:
                existing = conn.execute(
                    "SELECT id FROM memory_pages WHERE source_candidate_id = ?",
                    (source_candidate_id,),
                ).fetchone()
            if not existing:
                existing = conn.execute(
                    "SELECT id FROM memory_pages WHERE title = ? AND scope = ?",
                    (title, scope),
                ).fetchone()

            if existing:
                page_id = str(existing["id"])
                conn.execute(
                    """
                    UPDATE memory_pages
                    SET content = ?, confidence = ?, status = ?, source_candidate_id = COALESCE(?, source_candidate_id),
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (content, confidence, status, source_candidate_id, now, page_id),
                )
            else:
                page_id = new_id("mempg")
                conn.execute(
                    """
                    INSERT INTO memory_pages(
                        id, title, content, scope, confidence, status, source_candidate_id, created_at, updated_at
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (page_id, title, content, scope, confidence, status, source_candidate_id, now, now),
                )
        return page_id

    def search_memory_pages(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        pattern = f"%{query}%"
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, title, content, scope, confidence, status, source_candidate_id, created_at, updated_at
                FROM memory_pages
                WHERE status = 'active' AND (title LIKE ? OR content LIKE ?)
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (pattern, pattern, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_memory_page(self, page_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT id, title, content, scope, confidence, status, source_candidate_id, created_at, updated_at
                FROM memory_pages
                WHERE id = ?
                """,
                (page_id,),
            ).fetchone()
        return dict(row) if row else None

    def add_memory_link(
        self,
        source_id: str,
        target_id: str,
        relation: str,
        *,
        weight: float = 1.0,
    ) -> str:
        link_id = new_id("mlink")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_links(id, source_id, target_id, relation, weight, created_at)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (link_id, source_id, target_id, relation, weight, time.time()),
            )
        return link_id

    def list_memory_links(self, source_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, source_id, target_id, relation, weight, created_at
                FROM memory_links
                WHERE source_id = ?
                ORDER BY weight DESC, created_at DESC
                """,
                (source_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_skill(
        self,
        name: str,
        description: str,
        body: str,
        source: str = "generated",
        *,
        status: str = "draft",
        path: str | None = None,
    ) -> str:
        now = time.time()
        skill_id = new_id("skill")
        with self.connect() as conn:
            existing = conn.execute("SELECT id FROM skills WHERE name = ?", (name,)).fetchone()
            if existing:
                skill_id = existing["id"]
                conn.execute(
                    """
                    UPDATE skills SET description = ?, body = ?, source = ?, status = ?, path = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (description, body, source, status, path, now, skill_id),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO skills(id, name, description, body, status, source, path, created_at, updated_at)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (skill_id, name, description, body, status, source, path, now, now),
                )
        return skill_id

    def update_skill_status(
        self,
        name: str,
        status: str,
        *,
        source: str | None = None,
        path: str | None = None,
    ) -> None:
        updates = ["status = ?", "updated_at = ?"]
        params: list[Any] = [status, time.time()]
        if source is not None:
            updates.append("source = ?")
            params.append(source)
        if path is not None:
            updates.append("path = ?")
            params.append(path)
        params.append(name)
        with self.connect() as conn:
            conn.execute(
                f"UPDATE skills SET {', '.join(updates)} WHERE name = ?",
                params,
            )

    def list_skills(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id, name, description, status, source, path FROM skills ORDER BY name"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_skill(self, name: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT id, name, description, body, status, source, path FROM skills WHERE name = ?",
                (name,),
            ).fetchone()
        return dict(row) if row else None

    def add_tool_candidate(self, run_id: str, name: str, spec: dict[str, Any]) -> str:
        candidate_id = new_id("tc")
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO tool_candidates(id, run_id, name, spec_json, status, created_at) VALUES(?, ?, ?, ?, ?, ?)",
                (candidate_id, run_id, name, dumps(spec), "draft", time.time()),
            )
        return candidate_id

    def add_eval_case(self, run_id: str, name: str, case: dict[str, Any]) -> str:
        case_id = new_id("eval")
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO eval_cases(id, run_id, name, case_json, status, created_at) VALUES(?, ?, ?, ?, ?, ?)",
                (case_id, run_id, name, dumps(case), "draft", time.time()),
            )
        return case_id

    def upsert_artifact(self, mission_id: str, run_id: str, title: str, body: str, kind: str = "markdown") -> str:
        artifact_id = new_id("art")
        now = time.time()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO artifacts(id, mission_id, run_id, kind, title, body, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (artifact_id, mission_id, run_id, kind, title, body, now, now),
            )
        return artifact_id

    def get_run_events(self, run_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT seq, event_type, payload_json, created_at FROM run_events WHERE run_id = ? ORDER BY seq",
                (run_id,),
            ).fetchall()
        return [
            {
                "seq": row["seq"],
                "event_type": row["event_type"],
                "payload": loads(row["payload_json"], {}),
                "created_at": row["created_at"],
            }
            for row in rows
        ]


def _memory_candidate_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["evidence"] = loads(result.pop("evidence_json"), [])
    return result


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
