from __future__ import annotations

import hashlib
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import time
from typing import Any, Iterable, Iterator

from ..core.ids import new_id
from ..core.jsonutil import dumps, loads


SCHEMA_VERSION = 2
_DEFAULT_TOMBSTONE_RULE = "do_not_resurrect"


class StateStore:
    def __init__(self, state_dir: str | Path):
        self.state_dir = Path(state_dir).expanduser()
        self.db_path = self.state_dir / "state.db"

    def initialize(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.state_dir / "wiki").mkdir(parents=True, exist_ok=True)
        (self.state_dir / "runs" / "dream-reports").mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memory_candidates (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    claim TEXT NOT NULL,
                    dimension TEXT,
                    scope TEXT NOT NULL DEFAULT 'global',
                    confidence REAL NOT NULL DEFAULT 0.5,
                    evidence_json TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'draft',
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memory_pages (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    scope TEXT NOT NULL DEFAULT 'global',
                    confidence REAL NOT NULL DEFAULT 0.7,
                    status TEXT NOT NULL DEFAULT 'active',
                    source_candidate_id TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memory_links (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    weight REAL NOT NULL DEFAULT 1.0,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memory_tombstones (
                    id TEXT PRIMARY KEY,
                    target_id TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    target_hash TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    evidence_run_id TEXT,
                    rule TEXT NOT NULL DEFAULT 'do_not_resurrect',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS working_notes (
                    id TEXT PRIMARY KEY,
                    mission_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'open',
                    result_json TEXT,
                    created_at REAL NOT NULL,
                    processed_at REAL
                );
                CREATE TABLE IF NOT EXISTS memory_events (
                    id TEXT PRIMARY KEY,
                    event_at REAL,
                    observed_at REAL NOT NULL,
                    source TEXT NOT NULL,
                    agent_id TEXT,
                    run_id TEXT,
                    mission_id TEXT,
                    conversation_id TEXT,
                    message_id TEXT,
                    actor TEXT,
                    excerpt TEXT NOT NULL DEFAULT '',
                    raw_hash TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_memory_candidates_status ON memory_candidates(status);
                CREATE INDEX IF NOT EXISTS idx_memory_pages_status ON memory_pages(status);
                CREATE INDEX IF NOT EXISTS idx_memory_links_source ON memory_links(source_id);
                CREATE INDEX IF NOT EXISTS idx_memory_links_target ON memory_links(target_id);
                CREATE INDEX IF NOT EXISTS idx_memory_tombstones_target ON memory_tombstones(target_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_memory_events_run ON memory_events(run_id);
                CREATE INDEX IF NOT EXISTS idx_memory_events_observed ON memory_events(observed_at DESC);
                """
            )
            conn.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def schema_version(self) -> int:
        if not self.db_path.exists():
            return 0
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM schema_meta WHERE key = 'schema_version'").fetchone()
        return int(row["value"]) if row else 0

    def add_working_note(
        self,
        mission_id: str,
        run_id: str,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        note_id = new_id("note")
        now = time.time()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO working_notes(id, mission_id, run_id, content, metadata_json, status, created_at)
                VALUES(?, ?, ?, ?, ?, 'open', ?)
                """,
                (note_id, mission_id, run_id, content, dumps(metadata or {}), now),
            )
        return note_id

    def list_working_notes(self, status: str | None = "open", limit: int = 50) -> list[dict[str, Any]]:
        sql = """
            SELECT id, mission_id, run_id, content, metadata_json, status, result_json, created_at, processed_at
            FROM working_notes
        """
        params: list[Any] = []
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY created_at DESC LIMIT ?"
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

    def add_memory_event(
        self,
        *,
        source: str,
        event_at: float | int | str | None = None,
        observed_at: float | int | str | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
        mission_id: str | None = None,
        conversation_id: str | None = None,
        message_id: str | None = None,
        actor: str | None = None,
        excerpt: str = "",
        raw_hash: str | None = None,
        raw: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        observed = _timestamp(observed_at, default=now)
        event = _timestamp(event_at, default=observed)
        event_id = new_id("mevt")
        clean_excerpt = " ".join(str(excerpt or "").split())[:500]
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_events(
                    id, event_at, observed_at, source, agent_id, run_id, mission_id,
                    conversation_id, message_id, actor, excerpt, raw_hash, metadata_json, created_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    event,
                    observed,
                    str(source or "unknown"),
                    _optional_str(agent_id),
                    _optional_str(run_id),
                    _optional_str(mission_id),
                    _optional_str(conversation_id),
                    _optional_str(message_id),
                    _optional_str(actor),
                    clean_excerpt,
                    _event_hash(raw_hash, raw if raw is not None else clean_excerpt),
                    dumps(metadata or {}),
                    now,
                ),
            )
        stored = self.get_memory_event(event_id)
        if not stored:
            raise RuntimeError(f"memory event was not stored: {event_id}")
        return stored

    def get_memory_event(self, event_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT id, event_at, observed_at, source, agent_id, run_id, mission_id,
                       conversation_id, message_id, actor, excerpt, raw_hash, metadata_json, created_at
                FROM memory_events
                WHERE id = ?
                """,
                (event_id,),
            ).fetchone()
        return _memory_event_from_row(row) if row else None

    def list_memory_events(self, event_ids: Iterable[str]) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        seen: set[str] = set()
        for event_id in event_ids:
            clean_id = str(event_id or "").strip()
            if not clean_id or clean_id in seen:
                continue
            seen.add(clean_id)
            event = self.get_memory_event(clean_id)
            if event:
                events.append(event)
        return events

    def add_memory_candidate(
        self,
        run_id: str,
        claim: str,
        *,
        dimension: str | None = None,
        scope: str = "global",
        confidence: float = 0.5,
        evidence: Iterable[dict[str, Any]] | None = None,
        created_at: float | int | str | None = None,
    ) -> str:
        candidate_id = new_id("mem")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_candidates(id, run_id, claim, dimension, scope, confidence, evidence_json, status, created_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, 'draft', ?)
                """,
                (
                    candidate_id,
                    run_id,
                    claim,
                    dimension,
                    scope,
                    confidence,
                    dumps(list(evidence or [])),
                    _timestamp(created_at, default=time.time()),
                ),
            )
        return candidate_id

    def search_memory_candidates(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        pattern = f"%{query}%"
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, run_id, claim, dimension, scope, confidence, status, evidence_json, created_at
                FROM memory_candidates
                WHERE claim LIKE ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (pattern, max(0, int(limit))),
            ).fetchall()
        return [_memory_candidate_from_row(row) for row in rows]

    def list_memory_candidates(
        self,
        status: str | None = None,
        limit: int = 50,
        *,
        uid: str | None = None,
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT id, run_id, claim, dimension, scope, confidence, status, evidence_json, created_at
            FROM memory_candidates
        """
        params: list[Any] = []
        clauses: list[str] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        scope_clause, scope_params = _uid_scope_clause(uid)
        if scope_clause:
            clauses.append(scope_clause)
            params.extend(scope_params)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(0, int(limit)))
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_memory_candidate_from_row(row) for row in rows]

    def update_memory_candidate_status(self, candidate_id: str, status: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE memory_candidates SET status = ? WHERE id = ?", (status, candidate_id))

    def redact_memory_candidate(
        self,
        candidate_id: str,
        *,
        claim: str,
        status: str,
        evidence: Iterable[dict[str, Any]] | None = None,
        confidence: float = 0.0,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE memory_candidates
                SET claim = ?, confidence = ?, evidence_json = ?, status = ?
                WHERE id = ?
                """,
                (claim, confidence, dumps(list(evidence or [])), status, candidate_id),
            )

    def delete_memory_candidate(self, candidate_id: str) -> dict[str, int]:
        clean_id = str(candidate_id or "").strip()
        if not clean_id:
            raise ValueError("memory candidate id is required")
        with self.connect() as conn:
            candidate_rows = conn.execute("DELETE FROM memory_candidates WHERE id = ?", (clean_id,)).rowcount
            link_rows = conn.execute(
                "DELETE FROM memory_links WHERE source_id = ? OR target_id = ?",
                (clean_id, clean_id),
            ).rowcount
            tombstone_rows = conn.execute(
                "DELETE FROM memory_tombstones WHERE target_id = ? AND target_type = 'candidate'",
                (clean_id,),
            ).rowcount
        return {
            "candidates": int(candidate_rows),
            "pages": 0,
            "links": int(link_rows),
            "tombstones": int(tombstone_rows),
        }

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
        return _memory_candidate_from_row(row) if row else None

    def create_memory_page(
        self,
        title: str,
        content: str,
        *,
        scope: str = "global",
        source_candidate_id: str | None = None,
        confidence: float = 0.7,
        status: str = "active",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        page_id = new_id("mempg")
        now = time.time()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_pages(
                    id, title, content, scope, confidence, status, source_candidate_id, metadata_json, created_at, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    page_id,
                    title,
                    content,
                    scope,
                    confidence,
                    status,
                    source_candidate_id,
                    dumps(metadata or {}),
                    now,
                    now,
                ),
            )
        return page_id

    def upsert_memory_page(
        self,
        title: str,
        content: str,
        *,
        scope: str = "global",
        source_candidate_id: str | None = None,
        confidence: float = 0.7,
        status: str = "active",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        now = time.time()
        metadata_json = dumps(metadata) if metadata is not None else None
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
                    SET content = ?, confidence = ?, status = ?,
                        source_candidate_id = COALESCE(?, source_candidate_id),
                        metadata_json = COALESCE(?, metadata_json),
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (content, confidence, status, source_candidate_id, metadata_json, now, page_id),
                )
            else:
                page_id = new_id("mempg")
                conn.execute(
                    """
                    INSERT INTO memory_pages(
                        id, title, content, scope, confidence, status, source_candidate_id, metadata_json, created_at, updated_at
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (page_id, title, content, scope, confidence, status, source_candidate_id, metadata_json or "{}", now, now),
                )
        return page_id

    def update_memory_page(
        self,
        page_id: str,
        *,
        title: str,
        content: str,
        scope: str = "global",
        source_candidate_id: str | None = None,
        confidence: float = 0.7,
        status: str = "active",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE memory_pages
                SET title = ?, content = ?, scope = ?, confidence = ?, status = ?,
                    source_candidate_id = COALESCE(?, source_candidate_id),
                    metadata_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (title, content, scope, confidence, status, source_candidate_id, dumps(metadata or {}), time.time(), page_id),
            )

    def update_memory_page_status(self, page_id: str, status: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE memory_pages SET status = ?, updated_at = ? WHERE id = ?", (status, time.time(), page_id))

    def update_memory_page_confidence(self, page_id: str, confidence: float) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE memory_pages SET confidence = ?, updated_at = ? WHERE id = ?",
                (confidence, time.time(), page_id),
            )

    def redact_memory_page(
        self,
        page_id: str,
        *,
        title: str,
        content: str,
        status: str,
        metadata: dict[str, Any] | None = None,
        confidence: float = 0.0,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE memory_pages
                SET title = ?, content = ?, confidence = ?, status = ?, metadata_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (title, content, confidence, status, dumps(metadata or {}), time.time(), page_id),
            )

    def delete_memory_page(self, page_id: str) -> dict[str, int]:
        clean_id = str(page_id or "").strip()
        if not clean_id:
            raise ValueError("memory page id is required")
        with self.connect() as conn:
            page_rows = conn.execute("DELETE FROM memory_pages WHERE id = ?", (clean_id,)).rowcount
            link_rows = conn.execute(
                "DELETE FROM memory_links WHERE source_id = ? OR target_id = ?",
                (clean_id, clean_id),
            ).rowcount
            tombstone_rows = conn.execute(
                "DELETE FROM memory_tombstones WHERE target_id = ? AND target_type = 'page'",
                (clean_id,),
            ).rowcount
        return {
            "candidates": 0,
            "pages": int(page_rows),
            "links": int(link_rows),
            "tombstones": int(tombstone_rows),
        }

    def search_memory_pages(
        self,
        query: str,
        limit: int | None = 5,
        *,
        uid: str | None = None,
        status: str | None = "active",
    ) -> list[dict[str, Any]]:
        pattern = f"%{query}%"
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        clauses.append("(title LIKE ? OR content LIKE ?)")
        params.extend([pattern, pattern])
        scope_clause, scope_params = _uid_scope_clause(uid)
        if scope_clause:
            clauses.append(scope_clause)
            params.extend(scope_params)
        sql = """
            SELECT id, title, content, scope, confidence, status, source_candidate_id, metadata_json, created_at, updated_at
            FROM memory_pages
        """
        sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY updated_at DESC"
        sql = _apply_limit(sql, params, limit)
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_memory_page_from_row(row) for row in rows]

    def list_memory_pages(
        self,
        status: str | None = "active",
        limit: int | None = 50,
        *,
        uid: str | None = None,
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT id, title, content, scope, confidence, status, source_candidate_id, metadata_json, created_at, updated_at
            FROM memory_pages
        """
        params: list[Any] = []
        clauses: list[str] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        scope_clause, scope_params = _uid_scope_clause(uid)
        if scope_clause:
            clauses.append(scope_clause)
            params.extend(scope_params)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY updated_at DESC"
        sql = _apply_limit(sql, params, limit)
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_memory_page_from_row(row) for row in rows]

    def get_memory_page(self, page_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT id, title, content, scope, confidence, status, source_candidate_id, metadata_json, created_at, updated_at
                FROM memory_pages
                WHERE id = ?
                """,
                (page_id,),
            ).fetchone()
        return _memory_page_from_row(row) if row else None

    def add_memory_link(self, source_id: str, target_id: str, relation: str, *, weight: float = 1.0) -> str:
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

    def add_memory_tombstone(
        self,
        target_id: str,
        target_type: str,
        reason: str,
        *,
        summary: str = "",
        target_hash: str | None = None,
        evidence_run_id: str | None = None,
        rule: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        clean_target_id = str(target_id or "").strip()
        clean_target_type = str(target_type or "").strip().casefold()
        clean_reason = str(reason or "").strip()
        if not clean_target_id:
            raise ValueError("memory tombstone target_id is required")
        if clean_target_type not in {"candidate", "page"}:
            raise ValueError(f"invalid memory tombstone target_type: {target_type}")
        if not clean_reason:
            raise ValueError("memory tombstone reason is required")
        clean_summary = " ".join(str(summary or "").split())
        tombstone_id = new_id("tomb")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_tombstones(
                    id, target_id, target_type, target_hash, reason, summary,
                    evidence_run_id, rule, metadata_json, created_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tombstone_id,
                    clean_target_id,
                    clean_target_type,
                    _target_hash(target_hash, clean_summary or clean_target_id),
                    clean_reason,
                    clean_summary,
                    evidence_run_id,
                    rule or _DEFAULT_TOMBSTONE_RULE,
                    dumps(metadata or {}),
                    time.time(),
                ),
            )
        return tombstone_id

    def get_memory_tombstone(self, tombstone_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT id, target_id, target_type, target_hash, reason, summary,
                       evidence_run_id, rule, metadata_json, created_at
                FROM memory_tombstones
                WHERE id = ?
                """,
                (tombstone_id,),
            ).fetchone()
        return _memory_tombstone_from_row(row) if row else None

    def list_memory_tombstones(
        self,
        *,
        target_id: str | None = None,
        target_type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT id, target_id, target_type, target_hash, reason, summary,
                   evidence_run_id, rule, metadata_json, created_at
            FROM memory_tombstones
        """
        params: list[Any] = []
        clauses: list[str] = []
        if target_id:
            clauses.append("target_id = ?")
            params.append(target_id)
        if target_type:
            clean_target_type = str(target_type).strip().casefold()
            if clean_target_type not in {"candidate", "page"}:
                raise ValueError(f"invalid memory tombstone target_type: {target_type}")
            clauses.append("target_type = ?")
            params.append(clean_target_type)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(max(0, int(limit)))
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_memory_tombstone_from_row(row) for row in rows]

    def delete_memory_tombstone(self, tombstone_id: str) -> int:
        clean_id = str(tombstone_id or "").strip()
        if not clean_id:
            raise ValueError("memory tombstone id is required")
        with self.connect() as conn:
            rows = conn.execute("DELETE FROM memory_tombstones WHERE id = ?", (clean_id,)).rowcount
        return int(rows)


def _working_note_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["metadata"] = loads(result.pop("metadata_json", None), {})
    result["result"] = loads(result.pop("result_json", None), None)
    return result


def _memory_candidate_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["evidence"] = loads(result.pop("evidence_json"), [])
    return result


def _memory_event_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["metadata"] = loads(result.pop("metadata_json", None), {})
    return result


def _memory_page_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["metadata"] = loads(result.pop("metadata_json", None), {})
    return result


def _memory_tombstone_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["metadata"] = loads(result.pop("metadata_json"), {})
    return result


def _target_hash(explicit_hash: str | None, fallback: str) -> str:
    clean_hash = str(explicit_hash or "").strip()
    if clean_hash:
        return clean_hash
    return hashlib.sha256(str(fallback or "").encode("utf-8")).hexdigest()


def _apply_limit(sql: str, params: list[Any], limit: int | None) -> str:
    if limit is None:
        return sql
    params.append(max(0, int(limit)))
    return sql + " LIMIT ?"


def _uid_scope_clause(uid: str | None) -> tuple[str, list[Any]]:
    clean_uid = str(uid or "").strip()
    if not clean_uid:
        return "", []
    candidates = {clean_uid}
    if clean_uid.casefold().startswith("user:"):
        suffix = clean_uid.split(":", 1)[1].strip()
        if suffix:
            candidates.add(suffix)
    else:
        candidates.add(f"user:{clean_uid}")
    exact_values = sorted(value for value in candidates if value)
    placeholders = ", ".join("?" for _ in exact_values)
    clauses = [f"scope IN ({placeholders})"] if placeholders else []
    params: list[Any] = [*exact_values]
    clauses.append("scope LIKE ? ESCAPE '!'")
    params.append(_scope_like_pattern(clean_uid))
    return "(" + " OR ".join(clauses) + ")", params


def _scope_like_pattern(value: str) -> str:
    escaped = value.replace("!", "!!").replace("%", "!%").replace("_", "!_")
    return f"%{escaped}%"


def _event_hash(explicit_hash: str | None, fallback: Any) -> str:
    clean_hash = str(explicit_hash or "").strip()
    if clean_hash:
        return clean_hash if ":" in clean_hash else f"sha256:{clean_hash}"
    if isinstance(fallback, (dict, list, tuple)):
        payload = dumps(fallback)
    else:
        payload = str(fallback or "")
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _timestamp(value: float | int | str | None, *, default: float) -> float:
    if value is None or value == "":
        return float(default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _optional_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
