from __future__ import annotations

import hashlib
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import time
from typing import Any, Iterable, Iterator

from ..core.ids import new_id
from ..core.jsonutil import dumps, loads


SCHEMA_VERSION = 4
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
                CREATE TABLE IF NOT EXISTS dream_proposals (
                    id TEXT PRIMARY KEY,
                    report_id TEXT,
                    tool TEXT NOT NULL,
                    title TEXT NOT NULL,
                    rationale TEXT NOT NULL DEFAULT '',
                    risk TEXT NOT NULL DEFAULT 'high',
                    status TEXT NOT NULL DEFAULT 'pending',
                    action_json TEXT NOT NULL DEFAULT '{}',
                    before_json TEXT NOT NULL DEFAULT '{}',
                    after_json TEXT NOT NULL DEFAULT '{}',
                    decision_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    decided_at REAL
                );
                CREATE TABLE IF NOT EXISTS plan_items (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    parent_id TEXT,
                    title TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    scope TEXT NOT NULL DEFAULT 'global',
                    status TEXT NOT NULL,
                    priority TEXT NOT NULL DEFAULT 'normal',
                    due_at REAL,
                    source TEXT NOT NULL DEFAULT 'manual',
                    source_event_id TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    completed_at REAL
                );
                CREATE TABLE IF NOT EXISTS plan_proposals (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    action TEXT NOT NULL DEFAULT 'create',
                    target_id TEXT,
                    parent_id TEXT,
                    title TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    scope TEXT NOT NULL DEFAULT 'global',
                    status TEXT,
                    priority TEXT NOT NULL DEFAULT 'normal',
                    due_at REAL,
                    confidence REAL NOT NULL DEFAULT 0.5,
                    reason TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'auto',
                    source_event_id TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    proposal_status TEXT NOT NULL DEFAULT 'pending',
                    created_at REAL NOT NULL,
                    decided_at REAL,
                    decision_reason TEXT
                );
                CREATE TABLE IF NOT EXISTS memory_embeddings (
                    id TEXT PRIMARY KEY,
                    target_id TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    embedding BLOB NOT NULL,
                    model TEXT NOT NULL,
                    dimensions INTEGER NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memory_page_versions (
                    id TEXT PRIMARY KEY,
                    page_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    scope TEXT NOT NULL DEFAULT 'global',
                    confidence REAL NOT NULL DEFAULT 0.7,
                    status TEXT NOT NULL DEFAULT 'active',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    change_reason TEXT NOT NULL DEFAULT '',
                    changed_by TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_memory_embeddings_target ON memory_embeddings(target_id);
                CREATE INDEX IF NOT EXISTS idx_memory_page_versions_page ON memory_page_versions(page_id, version DESC);
                CREATE INDEX IF NOT EXISTS idx_memory_candidates_status ON memory_candidates(status);
                CREATE INDEX IF NOT EXISTS idx_memory_pages_status ON memory_pages(status);
                CREATE INDEX IF NOT EXISTS idx_memory_links_source ON memory_links(source_id);
                CREATE INDEX IF NOT EXISTS idx_memory_links_target ON memory_links(target_id);
                CREATE INDEX IF NOT EXISTS idx_memory_tombstones_target ON memory_tombstones(target_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_memory_events_run ON memory_events(run_id);
                CREATE INDEX IF NOT EXISTS idx_memory_events_observed ON memory_events(observed_at DESC);
                CREATE INDEX IF NOT EXISTS idx_dream_proposals_status ON dream_proposals(status, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_plan_items_scope_status ON plan_items(scope, status, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_plan_items_parent ON plan_items(parent_id, status);
                CREATE INDEX IF NOT EXISTS idx_plan_proposals_status ON plan_proposals(proposal_status, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_plan_proposals_scope ON plan_proposals(scope, proposal_status, created_at DESC);
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

    def list_recent_events(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id, event_at, observed_at, source, agent_id, run_id, mission_id, "
                "conversation_id, message_id, actor, excerpt, raw_hash, metadata_json, created_at "
                "FROM memory_events ORDER BY observed_at DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [_memory_event_from_row(row) for row in rows]

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

    def delete_memory_link(self, link_id: str) -> int:
        clean_id = str(link_id or "").strip()
        if not clean_id:
            return 0
        with self.connect() as conn:
            return int(conn.execute("DELETE FROM memory_links WHERE id = ?", (clean_id,)).rowcount)

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

    def add_dream_proposal(
        self,
        *,
        report_id: str | None,
        tool: str,
        title: str,
        rationale: str = "",
        risk: str = "high",
        status: str = "pending",
        action: dict[str, Any] | None = None,
        before: dict[str, Any] | list[Any] | None = None,
        after: dict[str, Any] | list[Any] | None = None,
    ) -> dict[str, Any]:
        clean_tool = str(tool or "").strip()
        clean_title = " ".join(str(title or "").split())
        clean_status = str(status or "pending").strip().casefold()
        if not clean_tool:
            raise ValueError("dream proposal tool is required")
        if not clean_title:
            clean_title = clean_tool.replace("_", " ")
        if clean_status not in {"pending", "applied", "rejected"}:
            raise ValueError(f"invalid dream proposal status: {status}")
        proposal_id = new_id("dprop")
        now = time.time()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO dream_proposals(
                    id, report_id, tool, title, rationale, risk, status,
                    action_json, before_json, after_json, decision_json, created_at, decided_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', ?, ?)
                """,
                (
                    proposal_id,
                    _optional_str(report_id),
                    clean_tool,
                    clean_title[:240],
                    " ".join(str(rationale or "").split())[:1000],
                    str(risk or "high").strip().casefold() or "high",
                    clean_status,
                    dumps(action or {}),
                    dumps(before or {}),
                    dumps(after or {}),
                    now,
                    now if clean_status in {"applied", "rejected"} else None,
                ),
            )
        proposal = self.get_dream_proposal(proposal_id)
        if not proposal:
            raise RuntimeError(f"dream proposal was not stored: {proposal_id}")
        return proposal

    def list_dream_proposals(self, status: str | None = "pending", limit: int = 50) -> list[dict[str, Any]]:
        sql = """
            SELECT id, report_id, tool, title, rationale, risk, status,
                   action_json, before_json, after_json, decision_json, created_at, decided_at
            FROM dream_proposals
        """
        params: list[Any] = []
        clean_status = str(status or "").strip().casefold()
        if clean_status:
            sql += " WHERE status = ?"
            params.append(clean_status)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(0, int(limit)))
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_dream_proposal_from_row(row) for row in rows]

    def get_dream_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT id, report_id, tool, title, rationale, risk, status,
                       action_json, before_json, after_json, decision_json, created_at, decided_at
                FROM dream_proposals
                WHERE id = ?
                """,
                (str(proposal_id or "").strip(),),
            ).fetchone()
        return _dream_proposal_from_row(row) if row else None

    def update_dream_proposal_status(
        self,
        proposal_id: str,
        status: str,
        *,
        decision: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        clean_status = str(status or "").strip().casefold()
        if clean_status not in {"pending", "applied", "rejected"}:
            raise ValueError(f"invalid dream proposal status: {status}")
        decided_at = time.time() if clean_status in {"applied", "rejected"} else None
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE dream_proposals
                SET status = ?, decision_json = ?, decided_at = ?
                WHERE id = ?
                """,
                (clean_status, dumps(decision or {}), decided_at, str(proposal_id or "").strip()),
            )
        proposal = self.get_dream_proposal(proposal_id)
        if not proposal:
            raise ValueError(f"dream proposal not found: {proposal_id}")
        return proposal

    def add_plan_item(
        self,
        *,
        kind: str,
        title: str,
        detail: str = "",
        scope: str = "global",
        parent_id: str | None = None,
        status: str | None = None,
        priority: str = "normal",
        due_at: float | int | str | None = None,
        source: str = "manual",
        source_event_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        created_at: float | int | str | None = None,
    ) -> dict[str, Any]:
        clean_kind = _plan_kind(kind)
        clean_title = _required_single_line(title, "plan item title")[:240]
        now = time.time()
        created = _timestamp(created_at, default=now)
        item_id = new_id("plan")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO plan_items(
                    id, kind, parent_id, title, detail, scope, status, priority,
                    due_at, source, source_event_id, metadata_json, created_at, updated_at, completed_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    clean_kind,
                    _optional_str(parent_id),
                    clean_title,
                    _clean_detail(detail),
                    _scope_or_global(scope),
                    _plan_status(clean_kind, status),
                    _plan_priority(priority),
                    _nullable_timestamp(due_at),
                    str(source or "manual").strip() or "manual",
                    _optional_str(source_event_id),
                    dumps(metadata or {}),
                    created,
                    created,
                    created if _is_plan_done_status(clean_kind, status) else None,
                ),
            )
        item = self.get_plan_item(item_id)
        if not item:
            raise RuntimeError(f"plan item was not stored: {item_id}")
        return item

    def get_plan_item(self, item_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT id, kind, parent_id, title, detail, scope, status, priority,
                       due_at, source, source_event_id, metadata_json, created_at, updated_at, completed_at
                FROM plan_items
                WHERE id = ?
                """,
                (str(item_id or "").strip(),),
            ).fetchone()
        return _plan_item_from_row(row) if row else None

    def list_plan_items(
        self,
        *,
        kind: str | None = None,
        status: str | Iterable[str] | None = None,
        scope: str | None = None,
        uid: str | None = None,
        limit: int | None = 50,
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT id, kind, parent_id, title, detail, scope, status, priority,
                   due_at, source, source_event_id, metadata_json, created_at, updated_at, completed_at
            FROM plan_items
        """
        params: list[Any] = []
        clauses: list[str] = []
        clean_kind = _optional_plan_kind(kind)
        if clean_kind:
            clauses.append("kind = ?")
            params.append(clean_kind)
        _append_status_clause(clauses, params, "status", status)
        clean_scope = str(scope or "").strip()
        if clean_scope:
            clauses.append("scope = ?")
            params.append(clean_scope)
        scope_clause, scope_params = _uid_scope_clause(uid)
        if scope_clause:
            clauses.append(scope_clause)
            params.extend(scope_params)
        if not include_archived:
            clauses.append("status != 'archived'")
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY COALESCE(due_at, updated_at) ASC, updated_at DESC"
        sql = _apply_limit(sql, params, limit)
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_plan_item_from_row(row) for row in rows]

    def search_plan_items(
        self,
        query: str,
        *,
        kind: str | None = None,
        status: str | Iterable[str] | None = None,
        uid: str | None = None,
        limit: int | None = 10,
    ) -> list[dict[str, Any]]:
        clean_query = " ".join(str(query or "").split())
        if not clean_query:
            return self.list_plan_items(kind=kind, status=status, uid=uid, limit=limit)
        sql = """
            SELECT id, kind, parent_id, title, detail, scope, status, priority,
                   due_at, source, source_event_id, metadata_json, created_at, updated_at, completed_at
            FROM plan_items
        """
        params: list[Any] = []
        clauses: list[str] = ["(title LIKE ? OR detail LIKE ? OR scope LIKE ?)"]
        pattern = f"%{clean_query}%"
        params.extend([pattern, pattern, pattern])
        clean_kind = _optional_plan_kind(kind)
        if clean_kind:
            clauses.append("kind = ?")
            params.append(clean_kind)
        _append_status_clause(clauses, params, "status", status)
        scope_clause, scope_params = _uid_scope_clause(uid)
        if scope_clause:
            clauses.append(scope_clause)
            params.extend(scope_params)
        sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY updated_at DESC"
        sql = _apply_limit(sql, params, limit)
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_plan_item_from_row(row) for row in rows]

    def update_plan_item(self, item_id: str, **fields: Any) -> dict[str, Any]:
        existing = self.get_plan_item(item_id)
        if not existing:
            raise ValueError(f"plan item not found: {item_id}")
        clean_kind = _plan_kind(fields.get("kind", existing["kind"]))
        updates: dict[str, Any] = {}
        for key in ("kind", "parent_id", "title", "detail", "scope", "status", "priority", "due_at", "source", "source_event_id"):
            if key not in fields:
                continue
            value = fields[key]
            if key == "kind":
                updates[key] = clean_kind
            elif key == "title":
                updates[key] = _required_single_line(value, "plan item title")[:240]
            elif key == "detail":
                updates[key] = _clean_detail(value)
            elif key == "scope":
                updates[key] = _scope_or_global(value)
            elif key == "status":
                updates[key] = _plan_status(clean_kind, value)
            elif key == "priority":
                updates[key] = _plan_priority(value)
            elif key == "due_at":
                updates[key] = _nullable_timestamp(value)
            elif key in {"parent_id", "source_event_id"}:
                updates[key] = _optional_str(value)
            else:
                updates[key] = str(value or "").strip() or "manual"
        if "metadata" in fields:
            updates["metadata_json"] = dumps(fields["metadata"] if isinstance(fields["metadata"], dict) else {})
        if "kind" in updates and "status" not in updates:
            updates["status"] = _plan_status(clean_kind, None)
        status_value = str(updates.get("status", existing.get("status") or "")).strip()
        completed_at = fields.get("completed_at") if "completed_at" in fields else None
        if status_value and _is_plan_done_status(clean_kind, status_value):
            updates["completed_at"] = _nullable_timestamp(completed_at) or existing.get("completed_at") or time.time()
        elif "status" in updates and not _is_plan_done_status(clean_kind, status_value):
            updates["completed_at"] = None
        if not updates:
            return existing
        updates["updated_at"] = time.time()
        assignments = ", ".join(f"{key} = ?" for key in updates)
        params = [*updates.values(), str(item_id or "").strip()]
        with self.connect() as conn:
            conn.execute(f"UPDATE plan_items SET {assignments} WHERE id = ?", params)
        updated = self.get_plan_item(item_id)
        if not updated:
            raise ValueError(f"plan item not found: {item_id}")
        return updated

    def delete_plan_item(self, item_id: str) -> int:
        clean_id = str(item_id or "").strip()
        if not clean_id:
            raise ValueError("plan item id is required")
        with self.connect() as conn:
            rows = conn.execute("DELETE FROM plan_items WHERE id = ?", (clean_id,)).rowcount
        return int(rows)

    def add_plan_proposal(
        self,
        *,
        kind: str,
        title: str,
        detail: str = "",
        scope: str = "global",
        action: str = "create",
        target_id: str | None = None,
        parent_id: str | None = None,
        status: str | None = None,
        priority: str = "normal",
        due_at: float | int | str | None = None,
        confidence: float = 0.5,
        reason: str = "",
        source: str = "auto",
        source_event_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        proposal_status: str = "pending",
        created_at: float | int | str | None = None,
    ) -> dict[str, Any]:
        clean_kind = _plan_kind(kind)
        clean_action = _plan_proposal_action(action)
        clean_proposal_status = _plan_proposal_status(proposal_status)
        proposal_id = new_id("plprop")
        now = time.time()
        created = _timestamp(created_at, default=now)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO plan_proposals(
                    id, kind, action, target_id, parent_id, title, detail, scope, status,
                    priority, due_at, confidence, reason, source, source_event_id, metadata_json,
                    proposal_status, created_at, decided_at, decision_reason
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    proposal_id,
                    clean_kind,
                    clean_action,
                    _optional_str(target_id),
                    _optional_str(parent_id),
                    _required_single_line(title, "plan proposal title")[:240],
                    _clean_detail(detail),
                    _scope_or_global(scope),
                    _optional_str(status),
                    _plan_priority(priority),
                    _nullable_timestamp(due_at),
                    _bounded_float(confidence, default=0.5, minimum=0.0, maximum=1.0),
                    _clean_detail(reason)[:1000],
                    str(source or "auto").strip() or "auto",
                    _optional_str(source_event_id),
                    dumps(metadata or {}),
                    clean_proposal_status,
                    created,
                    created if clean_proposal_status in {"accepted", "rejected"} else None,
                    None,
                ),
            )
        proposal = self.get_plan_proposal(proposal_id)
        if not proposal:
            raise RuntimeError(f"plan proposal was not stored: {proposal_id}")
        return proposal

    def get_plan_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT id, kind, action, target_id, parent_id, title, detail, scope, status,
                       priority, due_at, confidence, reason, source, source_event_id,
                       metadata_json, proposal_status, created_at, decided_at, decision_reason
                FROM plan_proposals
                WHERE id = ?
                """,
                (str(proposal_id or "").strip(),),
            ).fetchone()
        return _plan_proposal_from_row(row) if row else None

    def list_plan_proposals(
        self,
        *,
        status: str | None = "pending",
        scope: str | None = None,
        uid: str | None = None,
        limit: int | None = 50,
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT id, kind, action, target_id, parent_id, title, detail, scope, status,
                   priority, due_at, confidence, reason, source, source_event_id,
                   metadata_json, proposal_status, created_at, decided_at, decision_reason
            FROM plan_proposals
        """
        params: list[Any] = []
        clauses: list[str] = []
        clean_status = str(status or "").strip().casefold()
        if clean_status and clean_status != "all":
            clauses.append("proposal_status = ?")
            params.append(_plan_proposal_status(clean_status))
        clean_scope = str(scope or "").strip()
        if clean_scope:
            clauses.append("scope = ?")
            params.append(clean_scope)
        scope_clause, scope_params = _uid_scope_clause(uid)
        if scope_clause:
            clauses.append(scope_clause)
            params.extend(scope_params)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC, id DESC"
        sql = _apply_limit(sql, params, limit)
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_plan_proposal_from_row(row) for row in rows]

    def update_plan_proposal_status(
        self,
        proposal_id: str,
        status: str,
        *,
        reason: str = "",
    ) -> dict[str, Any]:
        clean_status = _plan_proposal_status(status)
        decided_at = time.time() if clean_status in {"accepted", "rejected"} else None
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE plan_proposals
                SET proposal_status = ?, decided_at = ?, decision_reason = ?
                WHERE id = ?
                """,
                (
                    clean_status,
                    decided_at,
                    _clean_detail(reason)[:1000] if reason else None,
                    str(proposal_id or "").strip(),
                ),
            )
        proposal = self.get_plan_proposal(proposal_id)
        if not proposal:
            raise ValueError(f"plan proposal not found: {proposal_id}")
        return proposal

    # ── Embedding storage ──

    def store_embedding(
        self,
        target_id: str,
        target_type: str,
        content_hash: str,
        embedding_bytes: bytes,
        model: str,
        dimensions: int,
    ) -> str:
        import struct

        embedding_id = new_id("emb")
        now = time.time()
        with self.connect() as conn:
            conn.execute("DELETE FROM memory_embeddings WHERE target_id = ?", (target_id,))
            conn.execute(
                """
                INSERT INTO memory_embeddings(id, target_id, target_type, content_hash, embedding, model, dimensions, created_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (embedding_id, target_id, target_type, content_hash, embedding_bytes, model, dimensions, now),
            )
        return embedding_id

    def get_embedding(self, target_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT id, target_id, target_type, content_hash, embedding, model, dimensions, created_at FROM memory_embeddings WHERE target_id = ?",
                (target_id,),
            ).fetchone()
        if not row:
            return None
        return dict(row)

    def list_embeddings(self, target_type: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if target_type:
                rows = conn.execute(
                    "SELECT id, target_id, target_type, content_hash, embedding, model, dimensions, created_at FROM memory_embeddings WHERE target_type = ? ORDER BY created_at DESC LIMIT ?",
                    (target_type, max(0, int(limit))),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, target_id, target_type, content_hash, embedding, model, dimensions, created_at FROM memory_embeddings ORDER BY created_at DESC LIMIT ?",
                    (max(0, int(limit)),),
                ).fetchall()
        return [dict(row) for row in rows]

    def delete_embedding(self, target_id: str) -> int:
        with self.connect() as conn:
            cursor = conn.execute("DELETE FROM memory_embeddings WHERE target_id = ?", (target_id,))
        return cursor.rowcount

    # ── Page version history ──

    def snapshot_page_version(
        self,
        page_id: str,
        *,
        change_reason: str = "",
        changed_by: str = "",
    ) -> str | None:
        page = self.get_memory_page(page_id)
        if not page:
            return None
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(version), 0) FROM memory_page_versions WHERE page_id = ?",
                (page_id,),
            ).fetchone()
            next_version = (row[0] if row else 0) + 1
            version_id = new_id("pgver")
            metadata = page.get("metadata") if isinstance(page.get("metadata"), dict) else {}
            conn.execute(
                """
                INSERT INTO memory_page_versions(id, page_id, version, title, content, scope, confidence, status, metadata_json, change_reason, changed_by, created_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    version_id,
                    page_id,
                    next_version,
                    str(page.get("title") or ""),
                    str(page.get("content") or ""),
                    str(page.get("scope") or "global"),
                    float(page.get("confidence") or 0.7),
                    str(page.get("status") or "active"),
                    dumps(metadata),
                    str(change_reason or ""),
                    str(changed_by or ""),
                    time.time(),
                ),
            )
        return version_id

    def list_page_versions(self, page_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, page_id, version, title, content, scope, confidence, status, metadata_json, change_reason, changed_by, created_at
                FROM memory_page_versions
                WHERE page_id = ?
                ORDER BY version DESC
                LIMIT ?
                """,
                (page_id, max(0, int(limit))),
            ).fetchall()
        return [_page_version_from_row(row) for row in rows]

    def get_page_version(self, version_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT id, page_id, version, title, content, scope, confidence, status, metadata_json, change_reason, changed_by, created_at
                FROM memory_page_versions
                WHERE id = ?
                """,
                (version_id,),
            ).fetchone()
        return _page_version_from_row(row) if row else None


def _page_version_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["metadata"] = loads(result.pop("metadata_json", None), {})
    return result


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


def _dream_proposal_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["action"] = loads(result.pop("action_json"), {})
    result["before"] = loads(result.pop("before_json"), {})
    result["after"] = loads(result.pop("after_json"), {})
    result["decision"] = loads(result.pop("decision_json"), {})
    return result


def _plan_item_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["metadata"] = loads(result.pop("metadata_json"), {})
    return result


def _plan_proposal_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["metadata"] = loads(result.pop("metadata_json"), {})
    return result


def _append_status_clause(clauses: list[str], params: list[Any], field: str, status: str | Iterable[str] | None) -> None:
    if status is None:
        return
    if isinstance(status, str):
        values = [status]
    else:
        values = [str(item or "").strip() for item in status]
    clean_values = [value for value in values if value]
    if not clean_values:
        return
    placeholders = ", ".join("?" for _ in clean_values)
    clauses.append(f"{field} IN ({placeholders})")
    params.extend(clean_values)


def _plan_kind(value: Any) -> str:
    clean = str(value or "").strip().casefold()
    if clean not in {"goal", "todo"}:
        raise ValueError(f"invalid plan kind: {value}")
    return clean


def _optional_plan_kind(value: Any) -> str | None:
    clean = str(value or "").strip()
    if not clean:
        return None
    return _plan_kind(clean)


def _plan_status(kind: str, value: Any) -> str:
    clean_kind = _plan_kind(kind)
    default = "active" if clean_kind == "goal" else "open"
    clean = str(value or default).strip().casefold()
    allowed = {"active", "paused", "completed", "cancelled", "archived"} if clean_kind == "goal" else {
        "open",
        "doing",
        "done",
        "cancelled",
        "archived",
    }
    if clean not in allowed:
        raise ValueError(f"invalid {clean_kind} plan status: {value}")
    return clean


def _is_plan_done_status(kind: str, value: Any) -> bool:
    try:
        clean_kind = _plan_kind(kind)
    except ValueError:
        return False
    clean_status = str(value or "").strip().casefold()
    return clean_status == ("completed" if clean_kind == "goal" else "done")


def _plan_priority(value: Any) -> str:
    clean = str(value or "normal").strip().casefold()
    if clean not in {"low", "normal", "high"}:
        raise ValueError(f"invalid plan priority: {value}")
    return clean


def _plan_proposal_action(value: Any) -> str:
    clean = str(value or "create").strip().casefold()
    if clean not in {"create", "update"}:
        raise ValueError(f"invalid plan proposal action: {value}")
    return clean


def _plan_proposal_status(value: Any) -> str:
    clean = str(value or "pending").strip().casefold()
    if clean == "applied":
        clean = "accepted"
    if clean not in {"pending", "accepted", "rejected"}:
        raise ValueError(f"invalid plan proposal status: {value}")
    return clean


def _required_single_line(value: Any, field: str) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _clean_detail(value: Any) -> str:
    return " ".join(str(value or "").split())


def _scope_or_global(value: Any) -> str:
    return str(value or "").strip() or "global"


def _nullable_timestamp(value: float | int | str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bounded_float(value: Any, *, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


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
    # A user's view = that user's scoped memories PLUS global/unscoped memories,
    # because global memories apply to (and are injected for) every user.
    candidates = {clean_uid, "global"}
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
    clauses.append("scope IS NULL OR scope = ''")
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
