from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.config import ConfigOverrides, DEFAULT_STATE_DIR, resolve_memory_config
from ..core.ids import new_id
from ..memory import MemoryEngine
from ..providers.openai import OpenAICompatibleMemoryMaintainer
from ..storage import StateStore
from .schema import memory_api_schema


class MemoryClient:
    def __init__(self, *, state_dir: str | Path = DEFAULT_STATE_DIR) -> None:
        self.state_dir = str(state_dir)

    def context(self, intent: str = "", *, limit: int = 8, scope: str = "memory") -> dict[str, Any]:
        engine = self._engine()
        query = intent.strip() or "memory context"
        cards = [_api_card(card) for card in engine.context_cards(query, limit=_limit(limit), search_scope=scope)]
        return {
            "kind": "memory_context",
            "version": "mnemo_memory.context.v1",
            "intent": intent,
            "cards": cards,
            "snapshot": engine.load_l1_snapshot(),
        }

    def recall(self, seed: str, *, context: str = "", depth: int = 2, limit: int = 8) -> dict[str, Any]:
        query = " ".join(part for part in [seed.strip(), context.strip()] if part)
        if not query:
            raise ValueError("recall seed is required")
        search = self._engine().search_with_plan(query, limit=_limit(limit), search_scope="memory")
        return {
            "kind": "memory_recall",
            "version": "mnemo_memory.recall.v1",
            "seed": seed,
            "context": context,
            "depth": max(1, min(4, int(depth))),
            "query_plan": search["query_plan"],
            "items": search["matches"],
        }

    def search(
        self,
        query: str,
        *,
        limit: int = 8,
        scope: str = "memory",
        include_tombstoned: bool = False,
    ) -> dict[str, Any]:
        result = self._engine().search_with_plan(
            query,
            limit=_limit(limit),
            search_scope=scope,
            include_tombstoned=include_tombstoned,
        )
        return {
            "kind": "memory_search",
            "version": "mnemo_memory.search.v1",
            "query": query,
            "scope": scope,
            **result,
        }

    def list(
        self,
        *,
        kind: str = "all",
        status: str | None = None,
        limit: int = 50,
        include_tombstoned: bool = False,
    ) -> dict[str, Any]:
        normalized_kind = str(kind or "all").strip().casefold()
        if normalized_kind not in {"all", "candidate", "page"}:
            raise ValueError(f"invalid memory list kind: {kind}")
        normalized_status = _optional_text(status)
        store = self._store()
        items: list[dict[str, Any]] = []
        bounded_limit = _limit(limit)

        if normalized_kind in {"all", "candidate"}:
            candidates = store.list_memory_candidates(status=normalized_status, limit=bounded_limit)
            items.extend(_typed_item("candidate", item) for item in candidates)
        if normalized_kind in {"all", "page"}:
            pages = store.list_memory_pages(status=normalized_status, limit=bounded_limit)
            items.extend(_typed_item("page", item) for item in pages)

        if not include_tombstoned:
            items = [item for item in items if not _is_tombstoned_status(item.get("status"))]
        items.sort(key=_item_timestamp, reverse=True)
        items = items[:bounded_limit]
        return {
            "kind": "memory_list",
            "version": "mnemo_memory.list.v1",
            "item_kind": normalized_kind,
            "status": normalized_status,
            "include_tombstoned": include_tombstoned,
            "count": len(items),
            "items": items,
        }

    def update(
        self,
        *,
        facts: list[Any] | tuple[Any, ...] | None = None,
        observations: list[Any] | tuple[Any, ...] | None = None,
        source: str = "sdk",
        run_id: str | None = None,
        mission_id: str | None = None,
    ) -> dict[str, Any]:
        store = self._store()
        engine = MemoryEngine(store)
        effective_run_id = run_id or new_id("memrun")
        effective_mission_id = mission_id or "memory-service"
        memory_candidates: list[dict[str, Any]] = []
        working_notes: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []

        for fact in facts or []:
            normalized = _normalize_fact(fact)
            if not normalized["claim"]:
                skipped.append({"kind": "fact", "reason": "empty_claim"})
                continue
            event = store.add_memory_event(
                source=_fact_text(fact, "source") or source,
                event_at=_fact_value(fact, "event_at"),
                observed_at=_fact_value(fact, "observed_at"),
                agent_id=_fact_text(fact, "agent_id") or _fact_text(fact, "agent"),
                run_id=_fact_text(fact, "run_id") or effective_run_id,
                mission_id=_fact_text(fact, "mission_id") or effective_mission_id,
                conversation_id=_fact_text(fact, "conversation_id"),
                message_id=_fact_text(fact, "message_id"),
                actor=_fact_text(fact, "actor"),
                excerpt=_fact_excerpt(fact, normalized["claim"]),
                raw_hash=_fact_text(fact, "raw_hash"),
                raw=fact,
                metadata=_fact_event_metadata(fact, normalized),
            )
            result = engine.write_candidate(
                effective_run_id,
                normalized["claim"],
                dimension=normalized["dimension"],
                scope=normalized["scope"],
                confidence=normalized["confidence"],
                evidence=[_evidence(source, fact, event)],
                created_at=event["observed_at"],
            )
            memory_candidates.append(
                {
                    "candidate_id": result["candidate_id"],
                    "event_id": event["id"],
                    "status": result["status"],
                    "dimension": normalized["dimension"],
                    "scope": normalized["scope"],
                    "safety": result["safety"],
                    "quality": result["quality"],
                }
            )

        for observation in observations or []:
            content, metadata = _normalize_observation(observation, source)
            if not content:
                skipped.append({"kind": "observation", "reason": "empty_content"})
                continue
            note_id = store.add_working_note(effective_mission_id, effective_run_id, content, metadata=metadata)
            working_notes.append({"note_id": note_id, "status": "open", "retention": metadata["retention"]})

        return {
            "kind": "memory_update",
            "version": "mnemo_memory.update.v1",
            "run_id": effective_run_id,
            "mission_id": effective_mission_id,
            "memory_candidates": memory_candidates,
            "working_notes": working_notes,
            "skipped": skipped,
        }

    def read(self, memory_id: str) -> dict[str, Any]:
        store = self._store()
        candidate = store.get_memory_candidate(memory_id)
        if candidate:
            return {"kind": "memory_item", "type": "candidate", "item": candidate}
        page = store.get_memory_page(memory_id)
        if page:
            return {"kind": "memory_item", "type": "page", "item": page}
        raise ValueError(f"memory not found: {memory_id}")

    def links(self, memory_id: str, *, direction: str = "both") -> dict[str, Any]:
        store = self._store()
        return {
            "kind": "memory_links",
            "memory_id": memory_id,
            "outgoing": store.list_memory_links(memory_id) if direction in {"outgoing", "both"} else [],
            "incoming": store.list_memory_backlinks(memory_id) if direction in {"incoming", "both"} else [],
        }

    def provenance(self, memory_id: str) -> dict[str, Any]:
        store = self._store()
        candidate = store.get_memory_candidate(memory_id)
        page = None
        memory_type = "candidate"
        candidates: list[dict[str, Any]]
        if candidate:
            candidates = [_typed_item("candidate", candidate)]
        else:
            page = store.get_memory_page(memory_id)
            if not page:
                raise ValueError(f"memory not found: {memory_id}")
            memory_type = "page"
            candidates = []
            for candidate_id in _page_source_candidate_ids(store, page):
                source_candidate = store.get_memory_candidate(candidate_id)
                if source_candidate:
                    candidates.append(_typed_item("candidate", source_candidate))

        events = store.list_memory_events(_candidate_event_ids(candidates))
        return {
            "kind": "memory_provenance",
            "version": "mnemo_memory.provenance.v1",
            "memory_id": memory_id,
            "memory_type": memory_type,
            "page": _typed_item("page", page) if page else None,
            "candidates": candidates,
            "events": events,
        }

    def snapshot(self, *, compile: bool = False, limit: int = 50) -> dict[str, Any]:
        engine = self._engine()
        snapshot = engine.compile_l1_snapshot(limit=limit) if compile else engine.load_l1_snapshot()
        return {"kind": "memory_snapshot", "exists": snapshot is not None, "snapshot": snapshot}

    def health(self, *, limit: int = 20) -> dict[str, Any]:
        return self._engine().health_report(limit=limit)

    def tombstones(
        self,
        *,
        target_id: str | None = None,
        target_type: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        return {
            "kind": "memory_tombstones",
            "tombstones": self._store().list_memory_tombstones(
                target_id=target_id,
                target_type=target_type,
                limit=limit,
            ),
        }

    def promote_candidate(self, candidate_id: str, *, min_confidence: float = 0.7) -> dict[str, Any]:
        return self._engine().promote_candidate(candidate_id, min_confidence=min_confidence)

    def force_promote_candidate(self, candidate_id: str) -> dict[str, Any]:
        return self._engine().force_promote_candidate(candidate_id)

    def reject_candidate(self, candidate_id: str, reason: str) -> dict[str, Any]:
        return self._engine().reject_candidate(candidate_id, reason)

    def tombstone(
        self,
        memory_id: str,
        reason: str,
        *,
        target_type: str = "auto",
        replacement_id: str | None = None,
    ) -> dict[str, Any]:
        return self._engine().tombstone_memory(
            memory_id,
            reason,
            target_type=target_type,
            replacement_id=replacement_id,
        )

    def forget(self, memory_id: str, *, reason: str = "private_delete", target_type: str = "auto") -> dict[str, Any]:
        return self._engine().private_delete_memory(memory_id, reason, target_type=target_type)

    def dream_run(
        self,
        *,
        limit: int = 20,
        min_confidence: float = 0.7,
        actions: list[dict[str, Any]] | None = None,
        use_provider: bool = False,
        config: ConfigOverrides | None = None,
    ) -> dict[str, Any]:
        engine = self._engine()
        if use_provider and actions is None:
            resolved = resolve_memory_config(config or ConfigOverrides(state_dir=self.state_dir))
            maintainer = OpenAICompatibleMemoryMaintainer(resolved)
            delta = engine.collect_dream_delta(limit=limit)
            plan = engine.build_dream_plan(delta, limit=limit)
            actions = maintainer.propose_actions(delta=delta, plan=plan)
        return engine.dream_maintenance(limit=limit, min_confidence=min_confidence, actions=actions)

    def dream_status(self, *, limit: int = 20) -> dict[str, Any]:
        return self._engine().dream_status(limit=limit)

    def dream_report(self, report_id: str | None = None, *, latest: bool = False) -> dict[str, Any] | None:
        return self._engine().load_dream_report(report_id, latest=latest)

    def schema(self) -> dict[str, Any]:
        return memory_api_schema()

    def _store(self) -> StateStore:
        store = StateStore(self.state_dir)
        store.initialize()
        return store

    def _engine(self) -> MemoryEngine:
        return MemoryEngine(self._store())


def _api_card(card: dict[str, Any]) -> dict[str, Any]:
    result = dict(card)
    if result.get("type") == "page":
        result["type"] = "memory_page"
    if result.get("type") == "candidate":
        result["type"] = "memory_candidate"
    return result


def _limit(value: Any) -> int:
    return max(1, min(50, int(value)))


def _typed_item(item_type: str, item: dict[str, Any]) -> dict[str, Any]:
    return {"type": item_type, **item}


def _item_timestamp(item: dict[str, Any]) -> float:
    value = item.get("updated_at", item.get("created_at", 0.0))
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _is_tombstoned_status(status: Any) -> bool:
    normalized = str(status or "").casefold()
    return "tombstone" in normalized or "private_delete" in normalized or "deleted" in normalized


def _normalize_fact(fact: Any) -> dict[str, Any]:
    if isinstance(fact, str):
        return {"claim": " ".join(fact.split()), "dimension": "context", "scope": "global", "confidence": 0.5}
    if not isinstance(fact, dict):
        return {"claim": "", "dimension": "context", "scope": "global", "confidence": 0.5}
    return {
        "claim": " ".join(str(fact.get("claim") or fact.get("text") or "").split()),
        "dimension": str(fact.get("dimension") or "context"),
        "scope": str(fact.get("scope") or "global"),
        "confidence": _confidence(fact.get("confidence"), default=0.5),
    }


def _normalize_observation(observation: Any, source: str) -> tuple[str, dict[str, Any]]:
    if isinstance(observation, str):
        return (
            " ".join(observation.split()),
            {"source": source, "retention": "memory_candidate", "dimension": "context", "scope": "global"},
        )
    if not isinstance(observation, dict):
        return "", {"source": source, "retention": "ephemeral"}
    content = " ".join(str(observation.get("content") or observation.get("text") or "").split())
    retention = str(observation.get("retention") or "ephemeral")
    if retention not in {"ephemeral", "memory_candidate"}:
        retention = "ephemeral"
    return (
        content,
        {
            "source": source,
            "retention": retention,
            "dimension": str(observation.get("dimension") or "context"),
            "scope": str(observation.get("scope") or "global"),
            "confidence": _confidence(observation.get("confidence"), default=0.5),
        },
    )


def _evidence(source: str, raw: Any, event: dict[str, Any] | None = None) -> dict[str, Any]:
    evidence = {
        "kind": "agent_memory_update",
        "source": source,
        "summary": str(raw)[:220],
    }
    if event:
        evidence.update(
            {
                "event_id": event.get("id"),
                "event_at": event.get("event_at"),
                "observed_at": event.get("observed_at"),
                "run_id": event.get("run_id"),
                "message_id": event.get("message_id"),
            }
        )
    return evidence


def _fact_value(fact: Any, key: str) -> Any:
    if isinstance(fact, dict):
        return fact.get(key)
    return None


def _fact_text(fact: Any, key: str) -> str | None:
    value = _fact_value(fact, key)
    text = str(value or "").strip()
    return text or None


def _fact_excerpt(fact: Any, claim: str) -> str:
    if isinstance(fact, dict):
        for key in ("excerpt", "summary", "quote", "text"):
            text = str(fact.get(key) or "").strip()
            if text:
                return text
    return claim


def _fact_event_metadata(fact: Any, normalized: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(fact.get("metadata") or {}) if isinstance(fact, dict) and isinstance(fact.get("metadata"), dict) else {}
    metadata.setdefault("dimension", normalized["dimension"])
    metadata.setdefault("scope", normalized["scope"])
    return metadata


def _candidate_event_ids(candidates: list[dict[str, Any]]) -> list[str]:
    event_ids: list[str] = []
    for candidate in candidates:
        evidence = candidate.get("evidence")
        if not isinstance(evidence, list):
            continue
        for item in evidence:
            if isinstance(item, dict) and str(item.get("event_id") or "").strip():
                event_ids.append(str(item["event_id"]))
    return _dedupe_strings(event_ids)


def _page_source_candidate_ids(store: StateStore, page: dict[str, Any]) -> list[str]:
    candidate_ids: list[str] = []
    if page.get("source_candidate_id"):
        candidate_ids.append(str(page["source_candidate_id"]))
    metadata = page.get("metadata") if isinstance(page.get("metadata"), dict) else {}
    source_ids = metadata.get("source_candidate_ids")
    if isinstance(source_ids, list):
        candidate_ids.extend(str(item) for item in source_ids)
    for link in store.list_memory_backlinks(str(page.get("id") or "")):
        if link.get("relation") == "promoted_to" and link.get("source_id"):
            candidate_ids.append(str(link["source_id"]))
    return _dedupe_strings(candidate_ids)


def _dedupe_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = str(value or "").strip()
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result


def _confidence(value: Any, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, parsed))
