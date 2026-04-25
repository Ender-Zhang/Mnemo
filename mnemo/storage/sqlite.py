from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import shutil
import sqlite3
import time
import zipfile
from pathlib import Path
from typing import Any, Iterable

from ..core.ids import new_id
from ..core.jsonutil import dumps, loads


SCHEMA_VERSION = 5
EXPORT_KIND = "mnemo_state_export"
EXPORT_MANIFEST = "manifest.json"
MANAGED_STATE_DIRS = ("wiki", "skills", "runs", "artifacts")
MANAGED_STATE_FILES = ("state.db",)
QUEUE_STATUSES = ("pending", "running", "completed", "failed", "cancelled")


@dataclass(frozen=True)
class SchemaMigration:
    version: int
    name: str
    apply: Callable[[sqlite3.Connection], None]


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
        for child in MANAGED_STATE_DIRS:
            (self.state_dir / child).mkdir(parents=True, exist_ok=True)

        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at REAL NOT NULL
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
                    metadata_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    processed_at REAL,
                    result_json TEXT NOT NULL,
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

                CREATE TABLE IF NOT EXISTS skill_usage_events (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES runs(id),
                    skill_id TEXT REFERENCES skills(id),
                    skill_name TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    outcome TEXT,
                    score REAL,
                    evidence_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tool_candidates (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES runs(id),
                    name TEXT NOT NULL,
                    spec_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS generated_tools (
                    id TEXT PRIMARY KEY,
                    candidate_id TEXT REFERENCES tool_candidates(id),
                    name TEXT NOT NULL UNIQUE,
                    description TEXT NOT NULL,
                    risk TEXT NOT NULL,
                    input_schema_json TEXT NOT NULL,
                    implementation_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS eval_cases (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES runs(id),
                    name TEXT NOT NULL,
                    case_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT,
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
                CREATE INDEX IF NOT EXISTS idx_skill_usage_skill_name ON skill_usage_events(skill_name, created_at);
                CREATE INDEX IF NOT EXISTS idx_skill_usage_run ON skill_usage_events(run_id);
                CREATE INDEX IF NOT EXISTS idx_generated_tools_status_name ON generated_tools(status, name);
                """
            )
            _apply_schema_migrations(conn)

    def export_state(self, archive_path: str | Path) -> dict[str, Any]:
        self.initialize()
        target = Path(archive_path).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        files = list(_iter_export_files(self.state_dir, target))
        manifest = {
            "kind": EXPORT_KIND,
            "schema_version": self.schema_version(),
            "exported_at": time.time(),
            "files": [item.as_posix() for item in files],
        }
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(EXPORT_MANIFEST, dumps(manifest))
            for relative_path in files:
                archive.write(self.state_dir / relative_path, relative_path.as_posix())
        return {
            "archive_path": str(target),
            "schema_version": manifest["schema_version"],
            "file_count": len(files),
            "manifest": manifest,
        }

    def import_state(self, archive_path: str | Path, *, replace: bool = False) -> dict[str, Any]:
        source = Path(archive_path).expanduser().resolve()
        if not source.exists():
            raise ValueError(f"backup archive not found: {source}")
        self.state_dir.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(source, "r") as archive:
                manifest = _read_export_manifest(archive)
                members = _safe_archive_members(archive, self.state_dir, manifest)
                if _has_managed_state(self.state_dir) and not replace:
                    raise ValueError("state directory is not empty; pass replace=True to import")
                if replace:
                    _remove_managed_state(self.state_dir)
                extracted = _safe_extract_archive(archive, self.state_dir, members)
        except zipfile.BadZipFile as exc:
            raise ValueError("backup archive is not a valid zip file") from exc
        self.initialize()
        return {
            "archive_path": str(source),
            "schema_version": self.schema_version(),
            "file_count": len(extracted),
            "manifest": manifest,
        }

    def schema_version(self) -> int:
        with self.connect() as conn:
            try:
                row = conn.execute("SELECT value FROM schema_meta WHERE key = ?", ("schema_version",)).fetchone()
            except sqlite3.OperationalError:
                return 0
        if not row:
            return 0
        try:
            return int(row["value"])
        except (TypeError, ValueError):
            return 0

    def applied_migrations(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            try:
                rows = conn.execute(
                    "SELECT version, name, applied_at FROM schema_migrations ORDER BY version ASC"
                ).fetchall()
            except sqlite3.OperationalError:
                return []
        return [dict(row) for row in rows]

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

    def list_conversations(self, *, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, title, created_at, updated_at
                FROM conversations
                ORDER BY updated_at DESC, created_at DESC
                LIMIT ?
                """,
                (max(0, int(limit)),),
            ).fetchall()
        return [dict(row) for row in rows]

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

    def list_missions(
        self,
        *,
        conversation_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT id, conversation_id, status, brief, created_at, updated_at
            FROM missions
        """
        filters: list[str] = []
        params: list[Any] = []
        if conversation_id:
            filters.append("conversation_id = ?")
            params.append(conversation_id)
        if status:
            filters.append("status = ?")
            params.append(status)
        if filters:
            sql += " WHERE " + " AND ".join(filters)
        sql += " ORDER BY updated_at DESC, created_at DESC LIMIT ?"
        params.append(max(0, int(limit)))
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

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

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT id, conversation_id, mission_id, status, input_text, output_text, created_at, completed_at
                FROM runs
                WHERE id = ?
                """,
                (run_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_runs(
        self,
        *,
        status: str | None = None,
        conversation_id: str | None = None,
        mission_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT id, conversation_id, mission_id, status, input_text, output_text, created_at, completed_at
            FROM runs
        """
        filters: list[str] = []
        params: list[Any] = []
        if status:
            filters.append("status = ?")
            params.append(status)
        if conversation_id:
            filters.append("conversation_id = ?")
            params.append(conversation_id)
        if mission_id:
            filters.append("mission_id = ?")
            params.append(mission_id)
        if filters:
            sql += " WHERE " + " AND ".join(filters)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(0, int(limit)))
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_run_summary_from_row(row) for row in rows]

    def cancel_run(self, run_id: str, *, reason: str = "cancelled") -> dict[str, Any]:
        now = time.time()
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT id, conversation_id, mission_id, status, input_text, output_text, created_at, completed_at
                FROM runs
                WHERE id = ?
                """,
                (run_id,),
            ).fetchone()
            if not row:
                raise ValueError(f"run not found: {run_id}")
            status = str(row["status"])
            if status in {"completed", "failed", "cancelled"}:
                result = dict(row)
                result["changed"] = False
                return result
            conn.execute(
                """
                UPDATE runs
                SET status = 'cancelled', output_text = ?, completed_at = ?
                WHERE id = ?
                """,
                (reason, now, run_id),
            )
            updated = conn.execute(
                """
                SELECT id, conversation_id, mission_id, status, input_text, output_text, created_at, completed_at
                FROM runs
                WHERE id = ?
                """,
                (run_id,),
            ).fetchone()
        result = dict(updated)
        result["changed"] = True
        return result

    def is_run_cancelled(self, run_id: str) -> bool:
        with self.connect() as conn:
            row = conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
        return bool(row and row["status"] == "cancelled")

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
            _insert_outbox_event(
                conn,
                topic=event_type,
                aggregate_id=run_id,
                payload={
                    "run_id": run_id,
                    "seq": seq,
                    "event_type": event_type,
                    "payload": payload,
                    "created_at": now,
                },
                now=now,
            )
        return seq

    def enqueue_outbox_event(
        self,
        topic: str,
        payload: dict[str, Any],
        *,
        aggregate_id: str | None = None,
        available_at: float | None = None,
    ) -> str:
        clean_topic = topic.strip()
        if not clean_topic:
            raise ValueError("outbox topic is required")
        now = time.time()
        with self.connect() as conn:
            return _insert_outbox_event(
                conn,
                topic=clean_topic,
                aggregate_id=aggregate_id,
                payload=payload,
                now=now,
                available_at=available_at,
            )

    def list_outbox_events(self, status: str | None = "pending", *, limit: int = 50) -> list[dict[str, Any]]:
        sql = """
            SELECT id, topic, aggregate_id, payload_json, status, attempts, available_at, last_error, created_at, updated_at
            FROM event_outbox
        """
        params: list[Any] = []
        clauses: list[str] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
            if status == "pending":
                clauses.append("available_at <= ?")
                params.append(time.time())
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY available_at ASC, created_at ASC, id ASC LIMIT ?"
        params.append(max(0, int(limit)))

        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_outbox_event_from_row(row) for row in rows]

    def mark_outbox_event(self, event_id: str, status: str, *, error: str | None = None) -> None:
        if status not in {"pending", "sent", "failed"}:
            raise ValueError(f"invalid outbox status: {status}")
        attempts_expr = "attempts + 1" if status == "failed" else "attempts"
        with self.connect() as conn:
            conn.execute(
                f"""
                UPDATE event_outbox
                SET status = ?, attempts = {attempts_expr}, last_error = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, error, time.time(), event_id),
            )

    def enqueue_run_request(
        self,
        message: str,
        *,
        conversation_id: str | None = None,
        mission_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        available_at: float | None = None,
    ) -> str:
        clean_message = " ".join(message.strip().split())
        if not clean_message:
            raise ValueError("queue message is required")
        now = time.time()
        queue_id = new_id("queue")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO run_queue(
                    id, message, conversation_id, mission_id, metadata_json, status, attempts,
                    worker_id, run_id, available_at, claimed_at, heartbeat_at, completed_at,
                    last_error, created_at, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    queue_id,
                    clean_message,
                    conversation_id,
                    mission_id,
                    dumps(metadata or {}),
                    "pending",
                    0,
                    None,
                    None,
                    now if available_at is None else available_at,
                    None,
                    None,
                    None,
                    None,
                    now,
                    now,
                ),
            )
        return queue_id

    def list_queue_items(self, status: str | None = None, *, limit: int = 50) -> list[dict[str, Any]]:
        sql = """
            SELECT id, message, conversation_id, mission_id, metadata_json, status, attempts,
                   worker_id, run_id, available_at, claimed_at, heartbeat_at, completed_at,
                   last_error, created_at, updated_at
            FROM run_queue
        """
        params: list[Any] = []
        if status:
            if status not in QUEUE_STATUSES:
                raise ValueError(f"invalid queue status: {status}")
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY created_at ASC, id ASC LIMIT ?"
        params.append(max(0, int(limit)))
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_queue_item_from_row(row) for row in rows]

    def claim_next_queue_item(self, worker_id: str) -> dict[str, Any] | None:
        clean_worker_id = worker_id.strip() or "worker"
        now = time.time()
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT id
                FROM run_queue
                WHERE status = 'pending' AND available_at <= ?
                ORDER BY available_at ASC, created_at ASC, id ASC
                LIMIT 1
                """,
                (now,),
            ).fetchone()
            if not row:
                return None
            queue_id = str(row["id"])
            cursor = conn.execute(
                """
                UPDATE run_queue
                SET status = 'running', attempts = attempts + 1, worker_id = ?, claimed_at = ?,
                    heartbeat_at = ?, last_error = NULL, updated_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (clean_worker_id, now, now, now, queue_id),
            )
            if cursor.rowcount != 1:
                return None
            claimed = conn.execute(
                """
                SELECT id, message, conversation_id, mission_id, metadata_json, status, attempts,
                       worker_id, run_id, available_at, claimed_at, heartbeat_at, completed_at,
                       last_error, created_at, updated_at
                FROM run_queue
                WHERE id = ?
                """,
                (queue_id,),
            ).fetchone()
        return _queue_item_from_row(claimed) if claimed else None

    def heartbeat_queue_item(self, queue_id: str) -> None:
        now = time.time()
        with self.connect() as conn:
            conn.execute(
                "UPDATE run_queue SET heartbeat_at = ?, updated_at = ? WHERE id = ? AND status = 'running'",
                (now, now, queue_id),
            )

    def complete_queue_item(
        self,
        queue_id: str,
        status: str,
        *,
        run_id: str | None = None,
        error: str | None = None,
    ) -> None:
        if status not in {"completed", "failed"}:
            raise ValueError(f"invalid queue completion status: {status}")
        now = time.time()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE run_queue
                SET status = ?, run_id = COALESCE(?, run_id), completed_at = ?, last_error = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, run_id, now, None if status == "completed" else error, now, queue_id),
            )

    def cancel_queue_item(self, queue_id: str, *, reason: str = "cancelled") -> dict[str, Any]:
        now = time.time()
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT id, message, conversation_id, mission_id, metadata_json, status, attempts,
                       worker_id, run_id, available_at, claimed_at, heartbeat_at, completed_at,
                       last_error, created_at, updated_at
                FROM run_queue
                WHERE id = ?
                """,
                (queue_id,),
            ).fetchone()
            if not row:
                raise ValueError(f"queue item not found: {queue_id}")
            status = str(row["status"])
            if status != "pending":
                result = _queue_item_from_row(row)
                result["changed"] = False
                return result
            cursor = conn.execute(
                """
                UPDATE run_queue
                SET status = 'cancelled', completed_at = ?, last_error = ?, updated_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (now, reason, now, queue_id),
            )
            updated = conn.execute(
                """
                SELECT id, message, conversation_id, mission_id, metadata_json, status, attempts,
                       worker_id, run_id, available_at, claimed_at, heartbeat_at, completed_at,
                       last_error, created_at, updated_at
                FROM run_queue
                WHERE id = ?
                """,
                (queue_id,),
            ).fetchone()
        result = _queue_item_from_row(updated)
        result["changed"] = cursor.rowcount == 1
        return result

    def recover_stale_queue_items(self, stale_after_s: float = 900.0) -> list[dict[str, Any]]:
        now = time.time()
        cutoff = now - max(0.0, float(stale_after_s))
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, message, conversation_id, mission_id, metadata_json, status, attempts,
                       worker_id, run_id, available_at, claimed_at, heartbeat_at, completed_at,
                       last_error, created_at, updated_at
                FROM run_queue
                WHERE status = 'running' AND COALESCE(heartbeat_at, claimed_at, updated_at) <= ?
                ORDER BY claimed_at ASC, created_at ASC
                """,
                (cutoff,),
            ).fetchall()
            recovered_ids = [str(row["id"]) for row in rows]
            for queue_id in recovered_ids:
                conn.execute(
                    """
                    UPDATE run_queue
                    SET status = 'pending', worker_id = NULL, claimed_at = NULL, heartbeat_at = NULL,
                        last_error = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    ("recovered stale running job", now, queue_id),
                )
            if not recovered_ids:
                return []
            placeholders = ",".join("?" for _ in recovered_ids)
            updated = conn.execute(
                f"""
                SELECT id, message, conversation_id, mission_id, metadata_json, status, attempts,
                       worker_id, run_id, available_at, claimed_at, heartbeat_at, completed_at,
                       last_error, created_at, updated_at
                FROM run_queue
                WHERE id IN ({placeholders})
                ORDER BY updated_at DESC, id ASC
                """,
                recovered_ids,
            ).fetchall()
        return [_queue_item_from_row(row) for row in updated]

    def queue_stats(self) -> dict[str, Any]:
        counts = {status: 0 for status in QUEUE_STATUSES}
        with self.connect() as conn:
            rows = conn.execute("SELECT status, COUNT(*) AS count FROM run_queue GROUP BY status").fetchall()
            oldest = conn.execute(
                "SELECT MIN(created_at) AS oldest_pending_at FROM run_queue WHERE status = 'pending'"
            ).fetchone()
        for row in rows:
            status = str(row["status"])
            if status in counts:
                counts[status] = int(row["count"])
        return {
            "counts": counts,
            "total": sum(counts.values()),
            "oldest_pending_at": oldest["oldest_pending_at"] if oldest else None,
        }

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

    def add_working_note(
        self,
        mission_id: str,
        run_id: str,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        note_id = new_id("note")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO working_notes(
                    id, mission_id, run_id, content, metadata_json, status, processed_at, result_json, created_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (note_id, mission_id, run_id, content, dumps(metadata or {}), "open", None, dumps({}), time.time()),
            )
        return note_id

    def list_working_notes(self, status: str | None = "open", limit: int = 50) -> list[dict[str, Any]]:
        sql = """
            SELECT id, mission_id, run_id, content, metadata_json, status, processed_at, result_json, created_at
            FROM working_notes
        """
        params: list[Any] = []
        if status:
            sql += " WHERE COALESCE(status, 'open') = ?"
            params.append(status)
        sql += " ORDER BY created_at ASC LIMIT ?"
        params.append(max(0, int(limit)))
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_working_note_from_row(row) for row in rows]

    def update_working_note_status(
        self,
        note_id: str,
        status: str,
        *,
        result: dict[str, Any] | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE working_notes
                SET status = ?, processed_at = ?, result_json = COALESCE(?, result_json)
                WHERE id = ?
                """,
                (status, time.time(), dumps(result) if result is not None else None, note_id),
            )

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

    def list_memory_pages(self, status: str | None = "active", limit: int = 50) -> list[dict[str, Any]]:
        limit_value = max(0, int(limit))
        sql = """
            SELECT id, title, content, scope, confidence, status, source_candidate_id, created_at, updated_at
            FROM memory_pages
        """
        params: list[Any] = []
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit_value)

        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
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

    def list_memory_backlinks(self, target_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, source_id, target_id, relation, weight, created_at
                FROM memory_links
                WHERE target_id = ?
                ORDER BY weight DESC, created_at DESC
                """,
                (target_id,),
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

    def record_skill_usage(
        self,
        run_id: str,
        skill_name: str,
        event_type: str,
        *,
        outcome: str | None = None,
        score: float | None = None,
        evidence: Iterable[dict[str, Any]] | None = None,
    ) -> str:
        event_id = new_id("skuse")
        with self.connect() as conn:
            skill = conn.execute("SELECT id FROM skills WHERE name = ?", (skill_name,)).fetchone()
            conn.execute(
                """
                INSERT INTO skill_usage_events(
                    id, run_id, skill_id, skill_name, event_type, outcome, score, evidence_json, created_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    run_id,
                    skill["id"] if skill else None,
                    skill_name,
                    event_type,
                    outcome,
                    score,
                    dumps(list(evidence or [])),
                    time.time(),
                ),
            )
        return event_id

    def list_skill_usage(
        self,
        skill_name: str | None = None,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT id, run_id, skill_id, skill_name, event_type, outcome, score, evidence_json, created_at
            FROM skill_usage_events
        """
        params: list[Any] = []
        if skill_name:
            sql += " WHERE skill_name = ?"
            params.append(skill_name)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_skill_usage_from_row(row) for row in rows]

    def skill_usage_stats(self) -> dict[str, dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT skill_name, event_type, outcome, score, created_at
                FROM skill_usage_events
                ORDER BY created_at ASC
                """
            ).fetchall()

        stats: dict[str, dict[str, Any]] = {}
        for row in rows:
            skill_name = str(row["skill_name"])
            item = stats.setdefault(
                skill_name,
                {
                    "uses": 0,
                    "views": 0,
                    "outcomes": 0,
                    "successes": 0,
                    "failures": 0,
                    "neutral": 0,
                    "score_total": 0.0,
                    "score_count": 0,
                    "last_used_at": None,
                },
            )
            item["uses"] += 1
            if row["event_type"] == "viewed":
                item["views"] += 1
            if row["outcome"]:
                item["outcomes"] += 1
                if row["outcome"] == "success":
                    item["successes"] += 1
                elif row["outcome"] == "failure":
                    item["failures"] += 1
                elif row["outcome"] == "neutral":
                    item["neutral"] += 1
            if row["score"] is not None:
                item["score_total"] += float(row["score"])
                item["score_count"] += 1
            item["last_used_at"] = row["created_at"]

        for item in stats.values():
            score_count = int(item.pop("score_count"))
            score_total = float(item.pop("score_total"))
            item["avg_score"] = score_total / score_count if score_count else 0.0
        return stats

    def add_tool_candidate(self, run_id: str, name: str, spec: dict[str, Any]) -> str:
        candidate_id = new_id("tc")
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO tool_candidates(id, run_id, name, spec_json, status, created_at) VALUES(?, ?, ?, ?, ?, ?)",
                (candidate_id, run_id, name, dumps(spec), "draft", time.time()),
            )
        return candidate_id

    def get_tool_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT id, run_id, name, spec_json, status, created_at
                FROM tool_candidates
                WHERE id = ?
                """,
                (candidate_id,),
            ).fetchone()
        return _tool_candidate_from_row(row) if row else None

    def list_tool_candidates(self, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        sql = """
            SELECT id, run_id, name, spec_json, status, created_at
            FROM tool_candidates
        """
        params: list[Any] = []
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_tool_candidate_from_row(row) for row in rows]

    def update_tool_candidate_status(self, candidate_id: str, status: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE tool_candidates SET status = ? WHERE id = ?",
                (status, candidate_id),
            )

    def upsert_generated_tool(
        self,
        *,
        candidate_id: str,
        name: str,
        description: str,
        risk: str,
        input_schema: dict[str, Any],
        implementation: dict[str, Any],
        status: str = "active",
    ) -> str:
        now = time.time()
        tool_id = new_id("gentool")
        with self.connect() as conn:
            existing = conn.execute("SELECT id FROM generated_tools WHERE name = ?", (name,)).fetchone()
            if existing:
                tool_id = str(existing["id"])
                conn.execute(
                    """
                    UPDATE generated_tools
                    SET candidate_id = ?, description = ?, risk = ?, input_schema_json = ?,
                        implementation_json = ?, status = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        candidate_id,
                        description,
                        risk,
                        dumps(input_schema),
                        dumps(implementation),
                        status,
                        now,
                        tool_id,
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO generated_tools(
                        id, candidate_id, name, description, risk, input_schema_json,
                        implementation_json, status, created_at, updated_at
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tool_id,
                        candidate_id,
                        name,
                        description,
                        risk,
                        dumps(input_schema),
                        dumps(implementation),
                        status,
                        now,
                        now,
                    ),
                )
        return tool_id

    def get_generated_tool(self, name: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT id, candidate_id, name, description, risk, input_schema_json,
                       implementation_json, status, created_at, updated_at
                FROM generated_tools
                WHERE name = ?
                """,
                (name,),
            ).fetchone()
        return _generated_tool_from_row(row) if row else None

    def list_generated_tools(self, status: str | None = "active", limit: int = 50) -> list[dict[str, Any]]:
        sql = """
            SELECT id, candidate_id, name, description, risk, input_schema_json,
                   implementation_json, status, created_at, updated_at
            FROM generated_tools
        """
        params: list[Any] = []
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY updated_at DESC, name ASC LIMIT ?"
        params.append(max(0, int(limit)))
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_generated_tool_from_row(row) for row in rows]

    def update_generated_tool_status(self, name: str, status: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE generated_tools SET status = ?, updated_at = ? WHERE name = ?",
                (status, time.time(), name),
            )

    def add_eval_case(self, run_id: str, name: str, case: dict[str, Any]) -> str:
        case_id = new_id("eval")
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO eval_cases(id, run_id, name, case_json, status, created_at) VALUES(?, ?, ?, ?, ?, ?)",
                (case_id, run_id, name, dumps(case), "draft", time.time()),
            )
        return case_id

    def get_eval_case(self, case_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT id, run_id, name, case_json, status, result_json, created_at
                FROM eval_cases
                WHERE id = ?
                """,
                (case_id,),
            ).fetchone()
        return _eval_case_from_row(row) if row else None

    def list_eval_cases(
        self,
        status: str | None = None,
        *,
        tool_name: str | None = None,
        skill_name: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT id, run_id, name, case_json, status, result_json, created_at
            FROM eval_cases
        """
        params: list[Any] = []
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        cases = [_eval_case_from_row(row) for row in rows]
        if tool_name:
            cases = [case for case in cases if _eval_case_targets_tool(case, tool_name)]
        if skill_name:
            cases = [case for case in cases if _eval_case_targets_skill(case, skill_name)]
        return cases

    def update_eval_case_status(
        self,
        case_id: str,
        status: str,
        *,
        result: dict[str, Any] | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE eval_cases SET status = ?, result_json = COALESCE(?, result_json) WHERE id = ?",
                (status, dumps(result) if result is not None else None, case_id),
            )

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

    def get_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT id, mission_id, run_id, kind, title, body, created_at, updated_at
                FROM artifacts
                WHERE id = ?
                """,
                (artifact_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_artifacts(
        self,
        *,
        mission_id: str | None = None,
        run_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT id, mission_id, run_id, kind, title, created_at, updated_at
            FROM artifacts
        """
        filters: list[str] = []
        params: list[Any] = []
        if mission_id:
            filters.append("mission_id = ?")
            params.append(mission_id)
        if run_id:
            filters.append("run_id = ?")
            params.append(run_id)
        if filters:
            sql += " WHERE " + " AND ".join(filters)
        sql += " ORDER BY updated_at DESC, created_at DESC LIMIT ?"
        params.append(max(0, int(limit)))
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

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


def _run_summary_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    input_text = str(result.pop("input_text", "") or "")
    result.pop("output_text", None)
    result["input_preview"] = _preview_text(input_text)
    return result


def _preview_text(value: str, limit: int = 120) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 1)]}..."


def _working_note_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["metadata"] = loads(result.pop("metadata_json", None), {})
    result["result"] = loads(result.pop("result_json", None), {})
    result["status"] = result.get("status") or "open"
    return result


def _skill_usage_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["evidence"] = loads(result.pop("evidence_json"), [])
    return result


def _tool_candidate_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["spec"] = loads(result.pop("spec_json"), {})
    return result


def _generated_tool_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["input_schema"] = loads(result.pop("input_schema_json"), {})
    result["implementation"] = loads(result.pop("implementation_json"), {})
    return result


def _eval_case_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["case"] = loads(result.pop("case_json"), {})
    raw_result = result.pop("result_json", None)
    result["result"] = loads(raw_result, {}) if raw_result else {}
    return result


def _outbox_event_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["payload"] = loads(result.pop("payload_json"), {})
    return result


def _queue_item_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["metadata"] = loads(result.pop("metadata_json"), {})
    return result


def _iter_export_files(state_dir: Path, archive_path: Path) -> Iterable[Path]:
    archive_path = archive_path.resolve()
    for filename in MANAGED_STATE_FILES:
        path = state_dir / filename
        if path.is_file() and path.resolve() != archive_path:
            yield Path(filename)
    for dirname in MANAGED_STATE_DIRS:
        root = state_dir / dirname
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.resolve() != archive_path:
                yield path.relative_to(state_dir)


def _read_export_manifest(archive: zipfile.ZipFile) -> dict[str, Any]:
    try:
        raw_manifest = archive.read(EXPORT_MANIFEST).decode("utf-8")
    except KeyError as exc:
        raise ValueError("backup archive is missing manifest.json") from exc
    manifest = loads(raw_manifest, {})
    if not isinstance(manifest, dict) or manifest.get("kind") != EXPORT_KIND:
        raise ValueError("backup archive manifest is invalid")
    schema_version = manifest.get("schema_version")
    if not isinstance(schema_version, int):
        raise ValueError("backup archive schema_version is invalid")
    if schema_version > SCHEMA_VERSION:
        raise ValueError("backup archive schema_version is newer than this runtime")
    files = manifest.get("files")
    if not isinstance(files, list) or any(not isinstance(item, str) for item in files):
        raise ValueError("backup archive file list is invalid")
    return manifest


def _has_managed_state(state_dir: Path) -> bool:
    return any((state_dir / filename).exists() for filename in MANAGED_STATE_FILES) or any(
        (state_dir / dirname).exists() and any((state_dir / dirname).iterdir())
        for dirname in MANAGED_STATE_DIRS
    )


def _remove_managed_state(state_dir: Path) -> None:
    for filename in MANAGED_STATE_FILES:
        path = state_dir / filename
        if path.exists():
            path.unlink()
    for dirname in MANAGED_STATE_DIRS:
        path = state_dir / dirname
        if path.exists():
            shutil.rmtree(path)


def _safe_archive_members(archive: zipfile.ZipFile, state_dir: Path, manifest: dict[str, Any]) -> list[zipfile.ZipInfo]:
    root = state_dir.resolve()
    members: list[zipfile.ZipInfo] = []
    expected_files = set(manifest["files"])
    actual_files: set[str] = set()
    for member in archive.infolist():
        if member.filename == EXPORT_MANIFEST or member.is_dir():
            continue
        relative_path = Path(member.filename)
        if not _is_managed_export_path(relative_path):
            raise ValueError(f"backup archive contains unsupported path: {member.filename}")
        target = (root / relative_path).resolve()
        if not target.is_relative_to(root):
            raise ValueError(f"backup archive contains unsafe path: {member.filename}")
        actual_files.add(relative_path.as_posix())
        members.append(member)
    if actual_files != expected_files:
        raise ValueError("backup archive manifest does not match archive contents")
    return members


def _safe_extract_archive(
    archive: zipfile.ZipFile,
    state_dir: Path,
    members: list[zipfile.ZipInfo],
) -> list[str]:
    extracted: list[str] = []
    for member in members:
        relative_path = Path(member.filename)
        target = state_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(member, "r") as source, target.open("wb") as destination:
            shutil.copyfileobj(source, destination)
        extracted.append(relative_path.as_posix())
    return extracted


def _is_managed_export_path(path: Path) -> bool:
    if path.is_absolute() or ".." in path.parts or not path.parts:
        return False
    if len(path.parts) == 1:
        return path.parts[0] in MANAGED_STATE_FILES
    return path.parts[0] in MANAGED_STATE_DIRS


def _eval_case_targets_tool(case: dict[str, Any], tool_name: str) -> bool:
    payload = case.get("case") or {}
    return tool_name in {
        payload.get("tool_candidate"),
        payload.get("tool_name"),
        payload.get("name"),
    }


def _eval_case_targets_skill(case: dict[str, Any], skill_name: str) -> bool:
    payload = case.get("case") or {}
    return skill_name in {
        payload.get("skill_candidate"),
        payload.get("skill_name"),
        payload.get("skill"),
        payload.get("name"),
    }


def _apply_schema_migrations(conn: sqlite3.Connection) -> None:
    applied = {
        int(row["version"])
        for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
    }
    for migration in MIGRATIONS:
        if migration.version in applied:
            continue
        migration.apply(conn)
        conn.execute(
            "INSERT OR REPLACE INTO schema_migrations(version, name, applied_at) VALUES(?, ?, ?)",
            (migration.version, migration.name, time.time()),
        )
    conn.execute(
        "INSERT OR REPLACE INTO schema_meta(key, value) VALUES(?, ?)",
        ("schema_version", str(SCHEMA_VERSION)),
    )


def _migration_initial_schema(conn: sqlite3.Connection) -> None:
    # The current initialize() path creates the full base schema before migrations run.
    return None


def _migration_post_v1_generated_lifecycle_columns(conn: sqlite3.Connection) -> None:
    _ensure_column(conn, "skills", "path", "TEXT")
    _ensure_column(conn, "eval_cases", "result_json", "TEXT")
    _ensure_column(conn, "working_notes", "metadata_json", "TEXT")
    _ensure_column(conn, "working_notes", "status", "TEXT")
    _ensure_column(conn, "working_notes", "processed_at", "REAL")
    _ensure_column(conn, "working_notes", "result_json", "TEXT")


def _migration_event_outbox(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS event_outbox (
            id TEXT PRIMARY KEY,
            topic TEXT NOT NULL,
            aggregate_id TEXT,
            payload_json TEXT NOT NULL,
            status TEXT NOT NULL,
            attempts INTEGER NOT NULL,
            available_at REAL NOT NULL,
            last_error TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_event_outbox_status_available
            ON event_outbox(status, available_at, created_at);
        CREATE INDEX IF NOT EXISTS idx_event_outbox_aggregate
            ON event_outbox(aggregate_id, created_at);
        """
    )


def _migration_run_queue(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS run_queue (
            id TEXT PRIMARY KEY,
            message TEXT NOT NULL,
            conversation_id TEXT,
            mission_id TEXT,
            metadata_json TEXT NOT NULL,
            status TEXT NOT NULL,
            attempts INTEGER NOT NULL,
            worker_id TEXT,
            run_id TEXT,
            available_at REAL NOT NULL,
            claimed_at REAL,
            heartbeat_at REAL,
            completed_at REAL,
            last_error TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_run_queue_status_available
            ON run_queue(status, available_at, created_at);
        CREATE INDEX IF NOT EXISTS idx_run_queue_status_heartbeat
            ON run_queue(status, heartbeat_at, claimed_at);
        """
    )


def _migration_generated_tools(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS generated_tools (
            id TEXT PRIMARY KEY,
            candidate_id TEXT REFERENCES tool_candidates(id),
            name TEXT NOT NULL UNIQUE,
            description TEXT NOT NULL,
            risk TEXT NOT NULL,
            input_schema_json TEXT NOT NULL,
            implementation_json TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_generated_tools_status_name
            ON generated_tools(status, name);
        """
    )


MIGRATIONS = (
    SchemaMigration(1, "initial_schema", _migration_initial_schema),
    SchemaMigration(2, "post_v1_generated_lifecycle_columns", _migration_post_v1_generated_lifecycle_columns),
    SchemaMigration(3, "event_outbox", _migration_event_outbox),
    SchemaMigration(4, "run_queue", _migration_run_queue),
    SchemaMigration(5, "generated_tools", _migration_generated_tools),
)


def _insert_outbox_event(
    conn: sqlite3.Connection,
    *,
    topic: str,
    payload: dict[str, Any],
    now: float,
    aggregate_id: str | None = None,
    available_at: float | None = None,
) -> str:
    event_id = new_id("outbox")
    conn.execute(
        """
        INSERT INTO event_outbox(
            id, topic, aggregate_id, payload_json, status, attempts, available_at, last_error, created_at, updated_at
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            topic,
            aggregate_id,
            dumps(payload),
            "pending",
            0,
            now if available_at is None else available_at,
            None,
            now,
            now,
        ),
    )
    return event_id


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
