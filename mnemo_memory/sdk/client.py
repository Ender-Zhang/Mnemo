from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..core.config import (
    ConfigOverrides,
    DEFAULT_AUTO_DREAM_INTERVAL_MINUTES,
    DEFAULT_AUTO_DREAM_LIMIT,
    DEFAULT_AUTO_DREAM_MIN_CONFIDENCE,
    DEFAULT_STATE_DIR,
    default_config_path,
    resolve_memory_config,
)
from ..core.ids import new_id
from ..memory import MemoryEngine
from ..memory.query import normalize_memory_dimension
from ..memory.wiki import materialize_memory_page
from ..storage import StateStore
from .schema import memory_api_schema

_MISSING = object()


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
        uid: str | None = None,
    ) -> dict[str, Any]:
        normalized_kind = str(kind or "all").strip().casefold()
        if normalized_kind not in {"all", "candidate", "page"}:
            raise ValueError(f"invalid memory list kind: {kind}")
        normalized_status = _optional_text(status)
        store = self._store()
        items: list[dict[str, Any]] = []
        bounded_limit = _limit(limit)
        normalized_uid = _optional_text(uid)

        if normalized_kind in {"all", "candidate"}:
            candidates = store.list_memory_candidates(status=normalized_status, limit=bounded_limit, uid=normalized_uid)
            items.extend(_typed_item("candidate", item) for item in candidates)
        if normalized_kind in {"all", "page"}:
            pages = store.list_memory_pages(status=normalized_status, limit=bounded_limit, uid=normalized_uid)
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
            "uid": normalized_uid,
            "include_tombstoned": include_tombstoned,
            "count": len(items),
            "items": items,
        }

    def stable_create(
        self,
        *,
        title: str,
        content: str,
        scope: str = "global",
        confidence: float = 0.7,
        status: str = "active",
        metadata: dict[str, Any] | None = None,
        dimension: str | None = None,
    ) -> dict[str, Any]:
        store = self._store()
        page_id = store.create_memory_page(
            _required_text(title, "title"),
            _required_text(content, "content"),
            scope=_scope_text(scope),
            confidence=_stable_confidence(confidence),
            status=_status_text(status),
            metadata=_stable_metadata(metadata, dimension=dimension),
        )
        page = _require_page(store, page_id)
        wiki = materialize_memory_page(store.state_dir, page)
        return {
            "kind": "stable_memory_create",
            "version": "mnemo_memory.stable.v1",
            "memory_id": page_id,
            "item": page,
            "wiki": wiki,
        }

    def stable_read(self, memory_id: str) -> dict[str, Any]:
        store = self._store()
        page = _require_page(store, memory_id)
        return {
            "kind": "stable_memory_read",
            "version": "mnemo_memory.stable.v1",
            "memory_id": page["id"],
            "item": page,
        }

    def stable_update(
        self,
        memory_id: str,
        *,
        title: str | None = None,
        content: str | None = None,
        scope: str | None = None,
        confidence: float | int | str | None = None,
        status: str | None = None,
        metadata: dict[str, Any] | None | object = _MISSING,
        dimension: str | None = None,
    ) -> dict[str, Any]:
        store = self._store()
        existing = _require_page(store, memory_id)
        next_metadata = (
            dict(existing.get("metadata") if isinstance(existing.get("metadata"), dict) else {})
            if metadata is _MISSING
            else _stable_metadata(metadata if isinstance(metadata, dict) else None, dimension=None)
        )
        if dimension is not None:
            next_metadata["dimension"] = normalize_memory_dimension(dimension, fallback="context")
        store.update_memory_page(
            existing["id"],
            title=_required_text(title, "title") if title is not None else str(existing.get("title") or ""),
            content=_required_text(content, "content") if content is not None else str(existing.get("content") or ""),
            scope=_scope_text(scope) if scope is not None else str(existing.get("scope") or "global"),
            source_candidate_id=existing.get("source_candidate_id"),
            confidence=_stable_confidence(confidence if confidence is not None else existing.get("confidence", 0.7)),
            status=_status_text(status) if status is not None else str(existing.get("status") or "active"),
            metadata=next_metadata,
        )
        page = _require_page(store, existing["id"])
        wiki = materialize_memory_page(store.state_dir, page)
        return {
            "kind": "stable_memory_update",
            "version": "mnemo_memory.stable.v1",
            "memory_id": page["id"],
            "item": page,
            "wiki": wiki,
        }

    def stable_search(
        self,
        query: str = "",
        *,
        limit: int | None = None,
        all_items: bool = False,
        uid: str | None = None,
        status: str | None = "active",
        include_inactive: bool = False,
    ) -> dict[str, Any]:
        store = self._store()
        clean_query = " ".join(str(query or "").split())
        status_filter = None if include_inactive else (_optional_text(status) or "active")
        fetch_all = bool(all_items or not clean_query)
        if fetch_all:
            items = store.list_memory_pages(
                status=status_filter,
                limit=_stable_limit(limit, default=None),
                uid=_optional_text(uid),
            )
        else:
            items = store.search_memory_pages(
                clean_query,
                limit=_stable_limit(limit, default=50),
                uid=_optional_text(uid),
                status=status_filter,
            )
        return {
            "kind": "stable_memory_search",
            "version": "mnemo_memory.stable.v1",
            "query": clean_query,
            "all": fetch_all,
            "status": status_filter,
            "uid": _optional_text(uid),
            "count": len(items),
            "items": items,
        }

    def stable_delete(
        self,
        memory_id: str,
        *,
        mode: str = "tombstone",
        reason: str = "deleted",
        delete_related: bool = True,
    ) -> dict[str, Any]:
        normalized_mode = _stable_delete_mode(mode)
        if normalized_mode == "tombstone":
            result = self.tombstone(memory_id, reason or "deleted", target_type="page")
        elif normalized_mode == "forget":
            result = self.forget(memory_id, reason=reason or "private_delete", target_type="page")
        else:
            result = self.hard_delete(memory_id, target_type="page", delete_related=delete_related)
        return {
            "kind": "stable_memory_delete",
            "version": "mnemo_memory.stable.v1",
            "memory_id": memory_id,
            "mode": normalized_mode,
            "result": result,
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

    def ingest_event(
        self,
        *,
        text: str,
        source: str = "sdk",
        actor: str | None = None,
        event_type: str = "message",
        context: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
        run_id: str | None = None,
        mission_id: str | None = None,
        conversation_id: str | None = None,
        message_id: str | None = None,
        agent_id: str | None = None,
        event_at: float | int | str | None = None,
        observed_at: float | int | str | None = None,
        scope: str | None = None,
        auto_promote: bool = False,
        min_confidence: float = 0.7,
        use_provider: bool = False,
        config: ConfigOverrides | None = None,
    ) -> dict[str, Any]:
        clean_text = _normalize_event_text(text)
        if not clean_text:
            raise ValueError("event text is required")

        store = self._store()
        engine = MemoryEngine(store)
        effective_run_id = run_id or new_id("memrun")
        effective_mission_id = mission_id or "memory-service"
        normalized_context = _normalize_context(context)
        effective_scope = str(scope or "").strip() or "global"

        event = store.add_memory_event(
            source=source,
            event_at=event_at,
            observed_at=observed_at,
            agent_id=agent_id,
            run_id=effective_run_id,
            mission_id=effective_mission_id,
            conversation_id=conversation_id,
            message_id=message_id,
            actor=actor,
            excerpt=clean_text,
            raw={"text": clean_text, "context": normalized_context},
            metadata={
                "event_type": event_type or "message",
                "scope": effective_scope,
                "context": normalized_context,
            },
        )

        extraction = _extract_event_memory(
            clean_text,
            context=normalized_context,
            scope=effective_scope,
            mission_id=effective_mission_id,
        )
        if use_provider:
            from ..providers.openai import OpenAICompatibleMemoryMaintainer

            resolved = resolve_memory_config(config or ConfigOverrides(state_dir=self.state_dir))
            provider_extraction = OpenAICompatibleMemoryMaintainer(resolved).extract_event_memory(
                event={
                    "text": clean_text,
                    "source": source,
                    "actor": actor,
                    "event_type": event_type,
                    "scope": effective_scope,
                    "run_id": effective_run_id,
                    "mission_id": effective_mission_id,
                    "conversation_id": conversation_id,
                    "message_id": message_id,
                },
                context=normalized_context,
            )
            extraction = _merge_event_extractions(extraction, provider_extraction)

        memory_candidates: list[dict[str, Any]] = []
        working_notes: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []

        for fact in extraction["facts"]:
            normalized = _normalize_fact(
                {
                    **fact,
                    "event_at": event.get("event_at"),
                    "observed_at": event.get("observed_at"),
                    "actor": actor,
                    "agent_id": agent_id,
                    "conversation_id": conversation_id,
                    "message_id": message_id,
                    "excerpt": clean_text,
                }
            )
            if not normalized["claim"]:
                skipped.append({"kind": "fact", "reason": "empty_claim"})
                continue
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

        for observation in extraction["observations"]:
            content, metadata = _normalize_observation(
                {
                    **observation,
                    "metadata": {
                        **(observation.get("metadata") if isinstance(observation.get("metadata"), dict) else {}),
                        "event_id": event["id"],
                        "event_type": event_type or "message",
                    },
                },
                source,
            )
            if not content:
                skipped.append({"kind": "observation", "reason": "empty_content"})
                continue
            note_id = store.add_working_note(effective_mission_id, effective_run_id, content, metadata=metadata)
            working_notes.append({"note_id": note_id, "status": "open", "retention": metadata["retention"]})

        promotions: list[dict[str, Any]] = []
        if auto_promote:
            for candidate in memory_candidates:
                if candidate.get("status") == "draft":
                    promotions.append(
                        engine.promote_candidate(
                            str(candidate["candidate_id"]),
                            min_confidence=min_confidence,
                        )
                    )

        return {
            "kind": "memory_event_ingest",
            "version": "mnemo_memory.ingest_event.v1",
            "run_id": effective_run_id,
            "mission_id": effective_mission_id,
            "event": event,
            "extraction": extraction,
            "memory_candidates": memory_candidates,
            "working_notes": working_notes,
            "promotions": promotions,
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

    def provider_config(self) -> dict[str, Any]:
        config = resolve_memory_config(ConfigOverrides(state_dir=self.state_dir))
        save_path = default_config_path(self.state_dir)
        return {
            "kind": "memory_provider_config",
            "version": "mnemo_memory.provider_config.v1",
            "configured": bool(config.base_url and config.model),
            "api_key_configured": bool(config.api_key),
            "save_path": str(save_path),
            "config": config.redacted(),
        }

    def save_provider_config(
        self,
        *,
        provider: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        api_key: Any = _MISSING,
        api_key_env: str | None = None,
        timeout_s: float | int | str | None = None,
        thinking_enabled: bool | int | str | None = None,
        clear_api_key: bool = False,
    ) -> dict[str, Any]:
        path = default_config_path(self.state_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        config = _read_client_config(path)

        _set_optional_config_str(config, "provider", provider)
        _set_optional_config_str(config, "base_url", base_url)
        _set_optional_config_str(config, "model", model)
        _set_optional_config_str(config, "api_key_env", api_key_env)

        if clear_api_key:
            config.pop("api_key", None)
        elif api_key is not _MISSING:
            clean_key = str(api_key or "").strip()
            if clean_key and clean_key != "***":
                config["api_key"] = clean_key

        if timeout_s is not None and timeout_s != "":
            try:
                config["timeout_s"] = max(0.1, float(timeout_s))
            except (TypeError, ValueError) as exc:
                raise ValueError("timeout_s must be a number") from exc
        _set_optional_config_bool(config, "thinking_enabled", thinking_enabled)

        path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return self.provider_config()

    def auto_dream_config(self) -> dict[str, Any]:
        config = resolve_memory_config(ConfigOverrides(state_dir=self.state_dir))
        save_path = default_config_path(self.state_dir)
        return {
            "kind": "memory_auto_dream_config",
            "version": "mnemo_memory.auto_dream_config.v1",
            "enabled": bool(config.auto_dream_enabled),
            "interval_minutes": int(config.auto_dream_interval_minutes),
            "limit": int(config.auto_dream_limit),
            "min_confidence": float(config.auto_dream_min_confidence),
            "save_path": str(save_path),
        }

    def save_auto_dream_config(
        self,
        *,
        enabled: bool | int | str | None = None,
        interval_minutes: int | str | None = None,
        limit: int | str | None = None,
        min_confidence: float | int | str | None = None,
    ) -> dict[str, Any]:
        path = default_config_path(self.state_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        config = _read_client_config(path)
        _set_optional_config_bool(config, "auto_dream_enabled", enabled)
        if interval_minutes is not None and interval_minutes != "":
            config["auto_dream_interval_minutes"] = max(5, int(interval_minutes))
        if limit is not None and limit != "":
            config["auto_dream_limit"] = max(1, min(50, int(limit)))
        if min_confidence is not None and min_confidence != "":
            config["auto_dream_min_confidence"] = max(0.0, min(1.0, float(min_confidence)))
        config.setdefault("auto_dream_interval_minutes", DEFAULT_AUTO_DREAM_INTERVAL_MINUTES)
        config.setdefault("auto_dream_limit", DEFAULT_AUTO_DREAM_LIMIT)
        config.setdefault("auto_dream_min_confidence", DEFAULT_AUTO_DREAM_MIN_CONFIDENCE)
        path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return self.auto_dream_config()

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

    def hard_delete(
        self,
        memory_id: str | None = None,
        *,
        target_type: str = "auto",
        tombstone_id: str | None = None,
        delete_related: bool = True,
    ) -> dict[str, Any]:
        return self._engine().hard_delete_memory(
            memory_id,
            target_type=target_type,
            tombstone_id=tombstone_id,
            delete_related=delete_related,
        )

    def dream_run(
        self,
        *,
        limit: int = 20,
        min_confidence: float = 0.7,
        actions: list[dict[str, Any]] | None = None,
        use_provider: bool = False,
        advanced_dreaming: bool = False,
        execution_policy: str = "semi_auto",
        config: ConfigOverrides | None = None,
    ) -> dict[str, Any]:
        engine = self._engine()
        if use_provider and actions is None:
            from ..providers.openai import OpenAICompatibleMemoryMaintainer

            resolved = resolve_memory_config(config or ConfigOverrides(state_dir=self.state_dir))
            maintainer = OpenAICompatibleMemoryMaintainer(resolved)
            delta = engine.collect_dream_delta(limit=limit)
            plan = engine.build_dream_plan(delta, limit=limit, advanced_dreaming=advanced_dreaming)
            actions = maintainer.propose_actions(delta=delta, plan=plan)
        return engine.dream_maintenance(
            limit=limit,
            min_confidence=min_confidence,
            actions=actions,
            advanced_dreaming=advanced_dreaming,
            execution_policy=execution_policy,
        )

    def dream_status(self, *, limit: int = 20) -> dict[str, Any]:
        return self._engine().dream_status(limit=limit)

    def dream_report(self, report_id: str | None = None, *, latest: bool = False) -> dict[str, Any] | None:
        return self._engine().load_dream_report(report_id, latest=latest)

    def dream_proposals(self, *, status: str | None = "pending", limit: int = 50) -> dict[str, Any]:
        return self._engine().dream_proposals(status=status, limit=limit)

    def apply_dream_proposal(self, proposal_id: str) -> dict[str, Any]:
        return self._engine().apply_dream_proposal(proposal_id)

    def reject_dream_proposal(self, proposal_id: str, reason: str = "operator_rejected") -> dict[str, Any]:
        return self._engine().reject_dream_proposal(proposal_id, reason=reason)

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


def _required_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if field == "title":
        text = " ".join(text.split())
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _scope_text(value: Any) -> str:
    return str(value or "").strip() or "global"


def _status_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("status is required")
    return text


def _stable_confidence(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("confidence must be a number") from exc
    return max(0.0, min(1.0, parsed))


def _stable_metadata(metadata: dict[str, Any] | None, *, dimension: str | None = None) -> dict[str, Any]:
    result = dict(metadata or {})
    if dimension is not None:
        result["dimension"] = normalize_memory_dimension(dimension, fallback="context")
    return result


def _stable_limit(value: Any, *, default: int | None) -> int | None:
    if value is None or value == "":
        return default
    parsed = int(value)
    if parsed <= 0:
        return None
    return parsed


def _require_page(store: StateStore, memory_id: str) -> dict[str, Any]:
    clean_id = str(memory_id or "").strip()
    if not clean_id:
        raise ValueError("stable memory id is required")
    page = store.get_memory_page(clean_id)
    if not page:
        raise ValueError(f"stable memory not found: {clean_id}")
    return page


def _stable_delete_mode(value: Any) -> str:
    normalized = str(value or "tombstone").strip().casefold().replace("_", "-")
    if normalized not in {"tombstone", "forget", "hard-delete"}:
        raise ValueError(f"invalid stable memory delete mode: {value}")
    return normalized


def _is_tombstoned_status(status: Any) -> bool:
    normalized = str(status or "").casefold()
    return "tombstone" in normalized or "private_delete" in normalized or "deleted" in normalized


def _read_client_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _set_optional_config_str(config: dict[str, Any], key: str, value: str | None) -> None:
    if value is None:
        return
    clean = str(value).strip()
    if clean:
        config[key] = clean
    else:
        config.pop(key, None)


def _set_optional_config_bool(config: dict[str, Any], key: str, value: bool | int | str | None) -> None:
    if value is None or value == "":
        return
    parsed = _config_bool(value)
    if parsed is None:
        raise ValueError(f"{key} must be a boolean")
    config[key] = parsed


def _config_bool(value: bool | int | str) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    normalized = str(value).strip().casefold()
    if normalized in {"1", "true", "yes", "y", "on", "enabled", "enable"}:
        return True
    if normalized in {"0", "false", "no", "n", "off", "disabled", "disable"}:
        return False
    return None


def _normalize_event_text(text: Any) -> str:
    return " ".join(str(text or "").split())


def _normalize_context(context: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for item in context or []:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or item.get("actor") or "").strip()
        content = _normalize_event_text(item.get("content") or item.get("text") or "")
        if not content:
            continue
        normalized.append({"role": role or "unknown", "content": content[:1000]})
    return normalized[-8:]


def _extract_event_memory(
    text: str,
    *,
    context: list[dict[str, str]],
    scope: str,
    mission_id: str,
) -> dict[str, Any]:
    fact = _heuristic_event_fact(text, scope=scope)
    if fact:
        return {
            "kind": "event_memory_extraction",
            "strategy": "heuristic",
            "facts": [fact],
            "observations": [],
        }
    return {
        "kind": "event_memory_extraction",
        "strategy": "heuristic",
        "facts": [],
        "observations": [
            {
                "content": _event_observation_text(text, context),
                "retention": "ephemeral",
                "dimension": "context",
                "scope": f"mission:{mission_id}" if mission_id else scope,
            }
        ],
    }


def _merge_event_extractions(local: dict[str, Any], provider: dict[str, Any]) -> dict[str, Any]:
    facts = _dict_list(provider.get("facts"))
    observations = _dict_list(provider.get("observations"))
    if not facts and not observations:
        return local
    return {
        "kind": "event_memory_extraction",
        "strategy": "provider",
        "fallback": local,
        "facts": facts,
        "observations": observations,
    }


def _heuristic_event_fact(text: str, *, scope: str) -> dict[str, Any] | None:
    if _has_preference_memory_marker(text) or (_has_future_memory_marker(text) and _known_preference_subject(text)):
        return {
            "claim": _preference_claim(text),
            "dimension": "preferences",
            "scope": scope,
            "confidence": 0.88,
        }
    if _has_goal_memory_marker(text):
        return {
            "claim": f"用户 目标：{_goal_subject(text)}。",
            "dimension": "goals",
            "scope": scope,
            "confidence": 0.82,
        }
    return None


def _has_preference_memory_marker(text: str) -> bool:
    lowered = f" {text.casefold()} "
    return any(marker in lowered for marker in _PREFERENCE_EVENT_MARKERS)


def _has_future_memory_marker(text: str) -> bool:
    lowered = f" {text.casefold()} "
    return any(marker in lowered for marker in _FUTURE_EVENT_MARKERS)


def _has_goal_memory_marker(text: str) -> bool:
    lowered = f" {text.casefold()} "
    return any(marker in lowered for marker in _GOAL_EVENT_MARKERS)


def _preference_claim(text: str) -> str:
    subject = _preference_subject(text)
    return f"用户 偏好：{subject}；通常作为长期默认偏好。"


def _preference_subject(text: str) -> str:
    normalized = _normalize_event_text(text).strip("。.!！?")
    for value, subject in _KNOWN_PREFERENCE_SUBJECTS:
        if value in normalized.casefold():
            return subject
    result = normalized
    for marker in _PREFERENCE_STRIP_MARKERS:
        result = result.replace(marker, "")
    result = _normalize_event_text(result).strip("，,。.!！?")
    return result or normalized


def _known_preference_subject(text: str) -> bool:
    lowered = text.casefold()
    return any(value in lowered for value, _subject in _KNOWN_PREFERENCE_SUBJECTS)


def _goal_subject(text: str) -> str:
    result = _normalize_event_text(text).strip("。.!！?")
    for marker in _GOAL_STRIP_MARKERS:
        result = result.replace(marker, "")
    result = _normalize_event_text(result).strip("，,。.!！?")
    return result or _normalize_event_text(text)


def _event_observation_text(text: str, context: list[dict[str, str]]) -> str:
    prompt = _last_assistant_prompt(context)
    if prompt:
        return f"当前任务中，用户针对“{prompt}”回答：{text}"
    return f"当前任务中，用户输入：{text}"


def _last_assistant_prompt(context: list[dict[str, str]]) -> str | None:
    for item in reversed(context):
        role = item.get("role", "").casefold()
        if role in {"assistant", "agent", "system"} and item.get("content"):
            return item["content"][:160]
    return None


def _dict_list(value: Any) -> list[dict[str, Any]]:
    return [item for item in value or [] if isinstance(item, dict)] if isinstance(value, list) else []


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
    extra_metadata = observation.get("metadata") if isinstance(observation.get("metadata"), dict) else {}
    return (
        content,
        {
            "source": source,
            "retention": retention,
            "dimension": str(observation.get("dimension") or "context"),
            "scope": str(observation.get("scope") or "global"),
            "confidence": _confidence(observation.get("confidence"), default=0.5),
            **extra_metadata,
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


_PREFERENCE_EVENT_MARKERS = (
    "默认",
    "通常",
    "一般",
    "每次",
    "总是",
    "一直",
    "习惯",
    "喜欢",
    "偏好",
    " prefer ",
    " prefers ",
    " preference ",
    " like ",
    " likes ",
    " usually ",
    " always ",
    " default ",
)

_FUTURE_EVENT_MARKERS = (
    "以后",
    "以后都",
    "长期",
    " from now on ",
)

_GOAL_EVENT_MARKERS = (
    "目标",
    "计划",
    "想要",
    "希望",
    "学习",
    " goal ",
    " goals ",
    " plan ",
    " plans ",
    " want to ",
    " wants to ",
    " hope to ",
    " learn ",
    " learning ",
)

_PREFERENCE_STRIP_MARKERS = (
    "我",
    "以后",
    "以后都",
    "默认",
    "都",
    "通常",
    "一般",
    "每次",
    "总是",
    "一直",
    "长期",
    "习惯",
    "喜欢",
    "偏好",
    "会",
    "喝",
    "要",
)

_KNOWN_PREFERENCE_SUBJECTS = (
    ("冰美式", "冰美式咖啡"),
    ("iced americano", "iced americano coffee"),
    ("热拿铁", "热拿铁咖啡"),
    ("拿铁", "拿铁咖啡"),
    ("latte", "latte coffee"),
    ("美式", "美式咖啡"),
    ("americano", "americano coffee"),
)

_GOAL_STRIP_MARKERS = (
    "我",
    "以后",
    "目标是",
    "计划",
    "想要",
    "希望",
    "准备",
    "会",
)


def _confidence(value: Any, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, parsed))
