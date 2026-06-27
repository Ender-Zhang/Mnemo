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
    describe_effective_config,
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

    def context(self, intent: str = "", *, limit: int = 8, scope: str = "memory", uid: str | None = None) -> dict[str, Any]:
        engine = self._engine()
        query = intent.strip() or "memory context"
        clean_uid = _optional_text(uid)
        cards = [_api_card(card) for card in engine.context_cards(query, limit=_limit(limit), search_scope=scope, uid=clean_uid)]
        snapshot = engine.load_l1_snapshot()
        if clean_uid and isinstance(snapshot, dict):
            snapshot = _scope_l1_snapshot(snapshot, clean_uid)
        return {
            "kind": "memory_context",
            "version": "mnemo_memory.context.v1",
            "intent": intent,
            "uid": clean_uid,
            "cards": cards,
            "profile": engine.compile_l0(uid=clean_uid),
            "snapshot": snapshot,
        }

    def recall(self, seed: str, *, context: str = "", depth: int = 2, limit: int = 8, uid: str | None = None) -> dict[str, Any]:
        query = " ".join(part for part in [seed.strip(), context.strip()] if part)
        if not query:
            raise ValueError("recall seed is required")
        search = self._engine().search_with_plan(query, limit=_limit(limit), search_scope="memory", uid=_optional_text(uid))
        return {
            "kind": "memory_recall",
            "version": "mnemo_memory.recall.v1",
            "seed": seed,
            "context": context,
            "uid": _optional_text(uid),
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
        uid: str | None = None,
    ) -> dict[str, Any]:
        result = self._engine().search_with_plan(
            query,
            limit=_limit(limit),
            search_scope=scope,
            include_tombstoned=include_tombstoned,
            uid=_optional_text(uid),
        )
        return {
            "kind": "memory_search",
            "version": "mnemo_memory.search.v1",
            "query": query,
            "scope": scope,
            "uid": _optional_text(uid),
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
            items.extend(_typed_item("candidate", _attach_conflict_context(store, item)) for item in candidates)
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

    def plan_create(
        self,
        *,
        kind: str,
        title: str,
        detail: str = "",
        scope: str = "global",
        uid: str | None = None,
        parent_id: str | None = None,
        status: str | None = None,
        priority: str = "normal",
        due_at: float | int | str | None = None,
        source: str = "manual",
        source_event_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._engine().create_plan_item(
            kind=kind,
            title=title,
            detail=detail,
            scope=_scope_from_uid(scope, uid),
            parent_id=parent_id,
            status=status,
            priority=priority,
            due_at=due_at,
            source=source,
            source_event_id=source_event_id,
            metadata=metadata,
        )

    def plan_read(self, plan_id: str) -> dict[str, Any]:
        return self._engine().read_plan_item(plan_id)

    def plan_update(
        self,
        plan_id: str,
        *,
        kind: str | None = None,
        title: str | None = None,
        detail: str | None = None,
        scope: str | None = None,
        uid: str | None = None,
        parent_id: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        due_at: float | int | str | None = None,
        source: str | None = None,
        source_event_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        fields: dict[str, Any] = {
            "kind": kind,
            "title": title,
            "detail": detail,
            "parent_id": parent_id,
            "status": status,
            "priority": priority,
            "due_at": due_at,
            "source": source,
            "source_event_id": source_event_id,
            "metadata": metadata,
        }
        if scope is not None or uid is not None:
            fields["scope"] = _scope_from_uid(scope or "global", uid)
        return self._engine().update_plan_item(plan_id, **fields)

    def plan_list(
        self,
        *,
        kind: str | None = None,
        status: str | list[str] | tuple[str, ...] | None = None,
        scope: str | None = None,
        uid: str | None = None,
        query: str = "",
        limit: int = 50,
        include_archived: bool = False,
    ) -> dict[str, Any]:
        return self._engine().list_plan_items(
            kind=_optional_text(kind),
            status=status,
            scope=_optional_text(scope),
            uid=_optional_text(uid),
            query=query,
            limit=_limit(limit),
            include_archived=include_archived,
        )

    def plan_complete(self, plan_id: str) -> dict[str, Any]:
        return self._engine().complete_plan_item(plan_id)

    def plan_cancel(self, plan_id: str, reason: str = "cancelled") -> dict[str, Any]:
        return self._engine().cancel_plan_item(plan_id, reason=reason)

    def plan_archive(self, plan_id: str) -> dict[str, Any]:
        return self._engine().archive_plan_item(plan_id)

    def plan_proposals(
        self,
        *,
        status: str | None = "pending",
        scope: str | None = None,
        uid: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        return self._engine().plan_proposals(
            status=status,
            scope=_optional_text(scope),
            uid=_optional_text(uid),
            limit=_limit(limit),
        )

    def user_goals(
        self,
        uid: str,
        *,
        status: str | list[str] | tuple[str, ...] | None = None,
        include_archived: bool = False,
        include_proposals: bool = True,
        limit: int = 100,
    ) -> dict[str, Any]:
        clean_uid = _clean_user_uid(uid)
        if not clean_uid:
            raise ValueError("uid is required")
        bounded_limit = _plan_result_limit(limit)
        engine = self._engine()
        listed = engine.list_plan_items(
            status=status,
            uid=clean_uid,
            limit=bounded_limit,
            include_archived=include_archived,
        )
        proposals = (
            engine.plan_proposals(status="pending", uid=clean_uid, limit=bounded_limit)["proposals"]
            if include_proposals
            else []
        )
        return {
            "kind": "user_goals",
            "version": "mnemo_memory.goals.v1",
            "uid": clean_uid,
            "scope": _scope_from_uid("global", clean_uid),
            "status": status,
            "include_archived": bool(include_archived),
            "count": len(listed["items"]),
            "goals": listed["items"],
            "proposal_count": len(proposals),
            "proposals": proposals,
        }

    def apply_plan_proposal(self, proposal_id: str, reason: str = "operator_accepted") -> dict[str, Any]:
        return self._engine().apply_plan_proposal(proposal_id, reason=reason)

    def reject_plan_proposal(self, proposal_id: str, reason: str = "operator_rejected") -> dict[str, Any]:
        return self._engine().reject_plan_proposal(proposal_id, reason=reason)

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
        engine = self._engine()
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
        engine = self._engine()
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
        plan_proposals: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []

        for proposal in extraction.get("plan_proposals", []):
            normalized_proposal = _normalize_plan_proposal(
                {
                    **proposal,
                    "scope": proposal.get("scope") or effective_scope,
                    "source_event_id": event["id"],
                    "metadata": {
                        **(proposal.get("metadata") if isinstance(proposal.get("metadata"), dict) else {}),
                        "event_id": event["id"],
                        "event_type": event_type or "message",
                    },
                }
            )
            if not normalized_proposal["title"]:
                skipped.append({"kind": "plan_proposal", "reason": "empty_title"})
                continue
            created = engine.create_plan_proposal(
                **normalized_proposal,
                source=source,
                source_event_id=event["id"],
            )
            plan_proposals.append(created["proposal"])

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
            "plan_proposals": plan_proposals,
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

    def versions(self, memory_id: str, *, limit: int = 20) -> dict[str, Any]:
        store = self._store()
        list_versions = getattr(store, "list_page_versions", None)
        if not list_versions:
            return {"kind": "memory_versions", "memory_id": memory_id, "versions": []}
        versions = list_versions(memory_id, limit=max(1, min(50, int(limit))))
        return {
            "kind": "memory_versions",
            "memory_id": memory_id,
            "count": len(versions),
            "versions": versions,
        }

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

    def profile(self, *, limit: int = 50, uid: str | None = None) -> dict[str, Any]:
        return self._engine().compile_l0(limit=limit, uid=_optional_text(uid))

    def known_uids(self, *, limit: int = 2000) -> dict[str, Any]:
        """Distinct uids seen across stored pages/candidates (scope=user:<uid>)."""
        store = self._store()
        scopes: set[str] = set()
        for page in store.list_memory_pages(status=None, limit=limit):
            scopes.add(str(page.get("scope") or ""))
        for candidate in store.list_memory_candidates(status=None, limit=limit):
            scopes.add(str(candidate.get("scope") or ""))
        uids = sorted(
            {scope[len("user:"):] for scope in scopes if scope.lower().startswith("user:") and scope[len("user:"):].strip()}
        )
        return {"kind": "memory_known_uids", "uids": uids}

    def event_flow(self, *, uid: str | None = None, limit: int = 50) -> dict[str, Any]:
        """Per-event flow: event -> derived candidates -> promoted pages (+ plans).

        Scoped by uid (matches derived items or the event's scope). Lets the UI
        show a user's event -> memory pipeline end to end.
        """
        from ..memory.utils import scope_matches_uid

        store = self._store()
        uid_clean = _optional_text(uid)
        bounded = max(1, int(limit))

        events_by_candidate: dict[str, list[dict[str, Any]]] = {}
        for candidate in store.list_memory_candidates(status=None, limit=2000):
            for event_id in _candidate_event_ids([candidate]):
                events_by_candidate.setdefault(event_id, []).append(candidate)

        pages_by_candidate: dict[str, list[dict[str, Any]]] = {}
        for page in store.list_memory_pages(status=None, limit=2000):
            for candidate_id in _page_source_candidate_ids(store, page):
                pages_by_candidate.setdefault(candidate_id, []).append(page)

        plans_by_event: dict[str, list[dict[str, Any]]] = {}
        for item in store.list_plan_items(status=None, limit=1000, include_archived=True):
            event_id = str(item.get("source_event_id") or "")
            if event_id:
                plans_by_event.setdefault(event_id, []).append(
                    {"id": item.get("id"), "title": item.get("title"), "kind": item.get("kind"),
                     "status": item.get("status"), "scope": item.get("scope"), "type": "plan"}
                )
        for proposal in store.list_plan_proposals(status=None, limit=1000):
            event_id = str(proposal.get("source_event_id") or "")
            if event_id:
                plans_by_event.setdefault(event_id, []).append(
                    {"id": proposal.get("id"), "title": proposal.get("title"), "kind": proposal.get("kind"),
                     "status": proposal.get("proposal_status"), "scope": proposal.get("scope"), "type": "plan_proposal"}
                )

        flows: list[dict[str, Any]] = []
        for event in store.list_recent_events(limit=bounded * 5):
            event_id = str(event.get("id") or "")
            event_scope = str((event.get("metadata") or {}).get("scope") or "")
            candidates = []
            scopes: list[str] = [event_scope]
            for candidate in events_by_candidate.get(event_id, []):
                candidate_id = str(candidate.get("id") or "")
                page_ids = [str(p.get("id")) for p in pages_by_candidate.get(candidate_id, [])]
                scopes.append(str(candidate.get("scope") or ""))
                scopes.extend(str(p.get("scope") or "") for p in pages_by_candidate.get(candidate_id, []))
                candidates.append(
                    {"id": candidate_id, "status": candidate.get("status"), "claim": candidate.get("claim"),
                     "scope": candidate.get("scope"), "dimension": candidate.get("dimension"), "page_ids": page_ids}
                )
            plans = plans_by_event.get(event_id, [])
            scopes.extend(str(p.get("scope") or "") for p in plans)
            if uid_clean and not any(scope_matches_uid(scope, uid_clean) for scope in scopes):
                continue
            flows.append(
                {
                    "event": {
                        "id": event_id,
                        "excerpt": event.get("excerpt"),
                        "source": event.get("source"),
                        "actor": event.get("actor"),
                        "event_at": event.get("event_at"),
                        "observed_at": event.get("observed_at"),
                        "scope": event_scope,
                    },
                    "candidates": candidates,
                    "plans": plans,
                }
            )
            if len(flows) >= bounded:
                break
        return {"kind": "memory_event_flow", "uid": uid_clean, "flows": flows}

    def memory_flow(self, *, uid: str | None = None, limit: int = 50) -> dict[str, Any]:
        """End-to-end lineage for an admin: event -> candidate -> stable page ->
        injection (L0 每轮 / L1 快照). Builds on event_flow and marks, per page,
        whether it currently feeds the agent's L0 profile and L1 snapshot.
        """
        store = self._store()
        engine = self._engine()
        clean_uid = _optional_text(uid)
        base = self.event_flow(uid=clean_uid, limit=limit)

        profile = engine.compile_l0(uid=clean_uid)
        l0_ids = {str(e.get("page_id")) for e in (profile.get("entries") or []) if e.get("page_id")}
        snapshot = engine.load_l1_snapshot()
        l1_ids: set[str] = set()
        if isinstance(snapshot, dict):
            l1_ids = {str(i.get("id")) for i in (snapshot.get("items") or []) if isinstance(i, dict) and i.get("id")}
        pages_by_id = {str(p.get("id")): p for p in store.list_memory_pages(status=None, limit=2000)}

        flows: list[dict[str, Any]] = []
        for flow in base.get("flows", []):
            candidates = []
            for cand in flow.get("candidates", []):
                pages = []
                for page_id in cand.get("page_ids", []):
                    page = pages_by_id.get(str(page_id))
                    if not page:
                        continue
                    pages.append({
                        "id": str(page_id),
                        "title": page.get("title"),
                        "status": page.get("status"),
                        "in_l0": str(page_id) in l0_ids,
                        "in_l1": str(page_id) in l1_ids,
                    })
                candidates.append({**cand, "pages": pages})
            flows.append({**flow, "candidates": candidates})

        return {
            "kind": "memory_flow",
            "version": "mnemo_memory.flow.v1",
            "uid": clean_uid,
            "l0_count": len(l0_ids),
            "l1_count": len(l1_ids),
            "flows": flows,
        }

    def memory_graph(self, *, limit: int = 200) -> dict[str, Any]:
        """Aggregate active pages into dimension counts + an association graph."""
        from ..memory.wiki import memory_page_dimension

        store = self._store()
        pages = store.list_memory_pages(status="active", limit=max(1, int(limit)))
        page_ids = {str(page.get("id") or "") for page in pages if page.get("id")}

        dimension_counts: dict[str, int] = {}
        degree: dict[str, int] = {}
        edges: list[dict[str, Any]] = []
        seen_edges: set[tuple[str, str]] = set()
        for page in pages:
            pid = str(page.get("id") or "")
            if not pid:
                continue
            dimension_counts[memory_page_dimension(page)] = dimension_counts.get(memory_page_dimension(page), 0) + 1
            for link in store.list_memory_links(pid):
                target = str(link.get("target_id") or "")
                if target not in page_ids or target == pid:
                    continue
                key = tuple(sorted((pid, target)))
                degree[pid] = degree.get(pid, 0) + 1
                degree[target] = degree.get(target, 0) + 1
                if key in seen_edges:
                    continue
                seen_edges.add(key)
                edges.append({"source": pid, "target": target, "relation": link.get("relation")})

        nodes = [
            {
                "id": str(page.get("id")),
                "title": str(page.get("title") or page.get("id") or "")[:80],
                "dimension": memory_page_dimension(page),
                "degree": degree.get(str(page.get("id")), 0),
                "orphan": degree.get(str(page.get("id")), 0) == 0,
            }
            for page in pages
            if page.get("id")
        ]
        dimensions = [
            {"dimension": dimension, "count": count}
            for dimension, count in sorted(dimension_counts.items(), key=lambda item: (-item[1], item[0]))
        ]
        return {
            "kind": "memory_graph",
            "version": "mnemo_memory.memory_graph.v1",
            "page_count": len(pages),
            "dimensions": dimensions,
            "nodes": nodes,
            "edges": edges,
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

    def embedding_config(self) -> dict[str, Any]:
        config = resolve_memory_config(ConfigOverrides(state_dir=self.state_dir))
        return {
            "kind": "memory_embedding_config",
            "version": "mnemo_memory.embedding_config.v1",
            "enabled": bool(config.embeddings_enabled),
            "configured": bool(config.embedding_base_url and config.embedding_model),
            "api_key_configured": bool(config.embedding_api_key),
            "base_url": config.embedding_base_url,
            "model": config.embedding_model,
            "api_key_env": config.embedding_api_key_env,
            "save_path": str(default_config_path(self.state_dir)),
        }

    def save_embedding_config(
        self,
        *,
        enabled: bool | int | str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        api_key: Any = _MISSING,
        api_key_env: str | None = None,
        clear_api_key: bool = False,
    ) -> dict[str, Any]:
        path = default_config_path(self.state_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        config = _read_client_config(path)
        _set_optional_config_bool(config, "embeddings_enabled", enabled)
        _set_optional_config_str(config, "embedding_base_url", base_url)
        _set_optional_config_str(config, "embedding_model", model)
        _set_optional_config_str(config, "embedding_api_key_env", api_key_env)
        if clear_api_key:
            config.pop("embedding_api_key", None)
        elif api_key is not _MISSING:
            clean_key = str(api_key or "").strip()
            if clean_key and clean_key != "***":
                config["embedding_api_key"] = clean_key
        path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return self.embedding_config()

    def embedding_status(self) -> dict[str, Any]:
        info = self.embedding_config()
        store = self._store()
        active = store.list_memory_pages(status="active", limit=10000)
        indexed_ids = {str(row.get("target_id")) for row in store.list_embeddings(target_type="page", limit=10000)}
        indexed = sum(1 for page in active if str(page.get("id")) in indexed_ids)
        return {
            "kind": "memory_embedding_status",
            "version": "mnemo_memory.embedding_status.v1",
            "enabled": info["enabled"],
            "configured": info["configured"],
            "active_count": len(active),
            "indexed_count": indexed,
            "stale_count": max(0, len(active) - indexed),
        }

    def reindex_embeddings(self, *, limit: int = 10000) -> dict[str, Any]:
        from ..memory.embedding import ensure_page_embeddings

        provider, model = self._embedding_runtime()
        if provider is None or not model:
            raise ValueError("embeddings are not enabled or not configured")
        store = self._store()
        pages = store.list_memory_pages(status="active", limit=max(1, int(limit)))
        reindexed = ensure_page_embeddings(store, provider, pages, str(model))
        status = self.embedding_status()
        status["reindexed"] = reindexed
        return status

    def effective_config(self) -> dict[str, Any]:
        return describe_effective_config(self.state_dir)

    def test_provider(self) -> dict[str, Any]:
        import time as _time

        config = resolve_memory_config(ConfigOverrides(state_dir=self.state_dir))
        if not config.base_url or not config.model:
            return {"kind": "memory_provider_test", "ok": False, "error": "provider not configured (base_url/model)"}
        started = _time.perf_counter()
        try:
            from ..providers.openai import OpenAICompatibleMemoryMaintainer

            OpenAICompatibleMemoryMaintainer(config).ping()
            return {"kind": "memory_provider_test", "ok": True, "model": config.model, "latency_ms": round((_time.perf_counter() - started) * 1000, 1)}
        except (ValueError, OSError) as exc:
            return {"kind": "memory_provider_test", "ok": False, "error": str(exc), "latency_ms": round((_time.perf_counter() - started) * 1000, 1)}

    def test_embedding(self) -> dict[str, Any]:
        import time as _time

        config = resolve_memory_config(ConfigOverrides(state_dir=self.state_dir))
        if not config.embedding_base_url or not config.embedding_model:
            return {"kind": "memory_embedding_test", "ok": False, "error": "embeddings not configured (base_url/model)"}
        started = _time.perf_counter()
        try:
            from ..providers.embeddings import OpenAICompatibleEmbeddingProvider

            dimensions = OpenAICompatibleEmbeddingProvider(config).ping()
            return {"kind": "memory_embedding_test", "ok": True, "model": config.embedding_model, "dimensions": dimensions, "latency_ms": round((_time.perf_counter() - started) * 1000, 1)}
        except (ValueError, OSError) as exc:
            return {"kind": "memory_embedding_test", "ok": False, "error": str(exc), "latency_ms": round((_time.perf_counter() - started) * 1000, 1)}

    def tuning_config(self) -> dict[str, Any]:
        config = resolve_memory_config(ConfigOverrides(state_dir=self.state_dir))
        return {
            "kind": "memory_tuning_config",
            "version": "mnemo_memory.tuning_config.v1",
            "quality_write_threshold": config.quality_write_threshold,
            "quality_draft_threshold": config.quality_draft_threshold,
            "promote_min_confidence": config.promote_min_confidence,
            "save_path": str(default_config_path(self.state_dir)),
        }

    def save_tuning_config(
        self,
        *,
        quality_write_threshold: float | int | str | None = None,
        quality_draft_threshold: float | int | str | None = None,
        promote_min_confidence: float | int | str | None = None,
    ) -> dict[str, Any]:
        path = default_config_path(self.state_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        config = _read_client_config(path)
        for key, value in (
            ("quality_write_threshold", quality_write_threshold),
            ("quality_draft_threshold", quality_draft_threshold),
            ("promote_min_confidence", promote_min_confidence),
        ):
            if value is not None and value != "":
                try:
                    config[key] = max(0.0, min(1.0, float(value)))
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"{key} must be a number between 0 and 1") from exc
        path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return self.tuning_config()

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
            "local_fallback": bool(config.auto_dream_local_fallback),
            "save_path": str(save_path),
        }

    def save_auto_dream_config(
        self,
        *,
        enabled: bool | int | str | None = None,
        interval_minutes: int | str | None = None,
        limit: int | str | None = None,
        min_confidence: float | int | str | None = None,
        local_fallback: bool | int | str | None = None,
    ) -> dict[str, Any]:
        path = default_config_path(self.state_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        config = _read_client_config(path)
        _set_optional_config_bool(config, "auto_dream_enabled", enabled)
        _set_optional_config_bool(config, "auto_dream_local_fallback", local_fallback)
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

    def promote_candidate(self, candidate_id: str, *, min_confidence: float | None = None) -> dict[str, Any]:
        return self._engine().promote_candidate(candidate_id, min_confidence=min_confidence)

    def force_promote_candidate(self, candidate_id: str) -> dict[str, Any]:
        return self._engine().force_promote_candidate(candidate_id)

    def reject_candidate(self, candidate_id: str, reason: str) -> dict[str, Any]:
        return self._engine().reject_candidate(candidate_id, reason)

    def resolve_conflict(self, candidate_id: str, *, resolution: str) -> dict[str, Any]:
        return self._engine().resolve_conflict(candidate_id, resolution=resolution)

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
        deterministic_fallback = False
        model_calls: int | None = None
        conflict_resolver = None
        if use_provider and actions is None:
            try:
                from ..providers.openai import OpenAICompatibleMemoryMaintainer

                resolved = resolve_memory_config(config or ConfigOverrides(state_dir=self.state_dir))
                maintainer = OpenAICompatibleMemoryMaintainer(resolved)
                delta = engine.collect_dream_delta(limit=limit)
                actions, model_calls = _propose_dream_actions_batched(
                    engine,
                    maintainer,
                    delta,
                    limit=limit,
                    advanced_dreaming=advanced_dreaming,
                    batch_size=resolved.dream_batch_size,
                    max_batches=resolved.dream_max_batches,
                )
                conflict_resolver = _make_conflict_resolver(maintainer)
            except (ValueError, OSError):
                deterministic_fallback = True
        elif not use_provider and actions is None:
            deterministic_fallback = True
        return engine.dream_maintenance(
            limit=limit,
            min_confidence=min_confidence,
            actions=actions,
            advanced_dreaming=advanced_dreaming,
            execution_policy=execution_policy,
            deterministic_fallback=deterministic_fallback,
            model_calls=model_calls,
            conflict_resolver=conflict_resolver,
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
        config = resolve_memory_config(ConfigOverrides(state_dir=self.state_dir))
        provider, model = self._embedding_runtime(config)
        return MemoryEngine(
            self._store(),
            embedding_provider=provider,
            embedding_model=model,
            quality_write_threshold=config.quality_write_threshold,
            quality_draft_threshold=config.quality_draft_threshold,
            promote_min_confidence=config.promote_min_confidence,
        )

    def _embedding_runtime(self, config: Any | None = None) -> tuple[Any | None, str | None]:
        if config is None:
            config = resolve_memory_config(ConfigOverrides(state_dir=self.state_dir))
        if not config.embeddings_enabled or not config.embedding_base_url or not config.embedding_model:
            return None, None
        try:
            from ..providers.embeddings import OpenAICompatibleEmbeddingProvider

            return OpenAICompatibleEmbeddingProvider(config), config.embedding_model
        except (ValueError, OSError):
            return None, None


def _api_card(card: dict[str, Any]) -> dict[str, Any]:
    result = dict(card)
    if result.get("type") == "page":
        result["type"] = "memory_page"
    if result.get("type") == "candidate":
        result["type"] = "memory_candidate"
    return result


def _limit(value: Any) -> int:
    return max(1, min(50, int(value)))


def _plan_result_limit(value: Any) -> int:
    return max(1, min(500, int(value or 100)))


def _typed_item(item_type: str, item: dict[str, Any]) -> dict[str, Any]:
    return {"type": item_type, **item}


def _attach_conflict_context(store: Any, candidate: dict[str, Any]) -> dict[str, Any]:
    """For a candidate in conflict status, attach the existing page it conflicts with.

    The conflict relationship is stored as a ``conflicts_with`` memory link; the
    candidate row itself does not carry it, so we hydrate it on the read path so
    the UI can show *which* memory the candidate clashes with.
    """
    status = str(candidate.get("status") or "")
    if not status.startswith("needs_review:conflict"):
        return candidate
    list_links = getattr(store, "list_memory_links", None)
    get_page = getattr(store, "get_memory_page", None)
    if not callable(list_links) or not callable(get_page):
        return candidate
    page: dict[str, Any] | None = None
    stale_link_ids: list[str] = []
    for link in list_links(candidate.get("id")):
        if link.get("relation") != "conflicts_with":
            continue
        linked = get_page(str(link.get("target_id") or ""))
        if linked and str(linked.get("status") or "") == "active":
            page = linked
            break
        # The page is gone or no longer active: this conflict link is dead.
        if link.get("id"):
            stale_link_ids.append(str(link.get("id")))
    if not page:
        # The memory this candidate clashed with no longer exists (or was
        # tombstoned), so the conflict is not real anymore. Self-heal on read:
        # release the candidate back to draft and drop the dead links so it
        # stops surfacing as an unresolvable conflict the user can't clear.
        _release_stranded_conflict(store, candidate, stale_link_ids)
        return candidate
    candidate["conflict_page_id"] = page.get("id")
    candidate["conflict_card"] = {
        "kind": "conflict_decision_card",
        "candidate_id": candidate.get("id"),
        "candidate_claim": candidate.get("claim"),
        "candidate_dimension": candidate.get("dimension"),
        "candidate_confidence": candidate.get("confidence"),
        "page_id": page.get("id"),
        "page_title": page.get("title"),
        "page_content": page.get("content"),
        "page_confidence": page.get("confidence"),
        "page_status": page.get("status"),
    }
    return candidate


def _release_stranded_conflict(store: Any, candidate: dict[str, Any], stale_link_ids: list[str]) -> None:
    """Reset a conflict candidate whose conflicting page is gone back to draft and
    drop the dead ``conflicts_with`` links, mutating ``candidate`` in place so the
    healed status is reflected to the caller."""
    update_status = getattr(store, "update_memory_candidate_status", None)
    if callable(update_status):
        update_status(str(candidate.get("id") or ""), "draft")
        candidate["status"] = "draft"
    candidate.pop("conflict_page_id", None)
    candidate.pop("conflict_card", None)
    delete_link = getattr(store, "delete_memory_link", None)
    if callable(delete_link):
        for link_id in stale_link_ids:
            delete_link(link_id)


def _scope_matches_uid(scope: Any, uid: str) -> bool:
    """Mirror storage._uid_scope_clause matching for in-memory snapshot filtering."""
    clean_uid = str(uid or "").strip()
    if not clean_uid:
        return True
    scope_text = str(scope or "").strip()
    # global / unscoped memories apply to every user
    if scope_text in ("", "global"):
        return True
    candidates = {clean_uid}
    if clean_uid.casefold().startswith("user:"):
        suffix = clean_uid.split(":", 1)[1].strip()
        if suffix:
            candidates.add(suffix)
    else:
        candidates.add(f"user:{clean_uid}")
    if scope_text in candidates:
        return True
    return clean_uid in scope_text


def _scope_l1_snapshot(snapshot: dict[str, Any], uid: str) -> dict[str, Any]:
    """Filter a global L1 snapshot down to one user's pages for the preview."""
    items = [item for item in snapshot.get("items", []) if isinstance(item, dict) and _scope_matches_uid(item.get("scope"), uid)]
    allowed_ids = {str(item.get("id")) for item in items if item.get("id")}
    scoped = dict(snapshot)
    scoped["items"] = items
    scoped["page_count"] = len(items)
    pointers = snapshot.get("pointers")
    if isinstance(pointers, list):
        scoped["pointers"] = [p for p in pointers if isinstance(p, dict) and str(p.get("page_id")) in allowed_ids]
    hubs = snapshot.get("association_hubs")
    if isinstance(hubs, list):
        scoped["association_hubs"] = [h for h in hubs if isinstance(h, dict) and str(h.get("page_id")) in allowed_ids]
    return scoped


def _make_conflict_resolver(maintainer: Any) -> Any:
    """Adapt a maintenance provider into a (candidate, page) -> resolution dict
    callback for the engine's conflict sweep. Returns None if the provider can't
    reconcile, so the engine falls back to the deterministic rule."""
    reconcile = getattr(maintainer, "reconcile_conflict", None)
    if not callable(reconcile):
        return None

    def _resolver(candidate: dict[str, Any], page: dict[str, Any]) -> dict[str, Any] | None:
        try:
            return reconcile(candidate=candidate, page=page)
        except (ValueError, OSError, KeyError):
            return None

    return _resolver


def _propose_dream_actions_batched(
    engine: Any,
    maintainer: Any,
    delta: dict[str, Any],
    *,
    limit: int,
    advanced_dreaming: bool,
    batch_size: int,
    max_batches: int,
) -> tuple[list[dict[str, Any]], int]:
    """Drive model-based Dream in batches for precision.

    Instead of dumping the whole inventory into one model call, the unresolved
    memory candidates are split into batches of ``batch_size``. Each batch is
    proposed against the full shared context (pages / goals / health) so the
    model can still merge and dedupe, but only reasons over a handful of
    candidates at a time. Actions are merged and de-duplicated by identity, and
    the number of model calls is returned for observability.
    """
    candidates = delta.get("memory_candidates")
    candidates = candidates if isinstance(candidates, list) else []
    bounded_batch = max(1, int(batch_size))
    # Small backlog (or a single batch) → keep the original single-call behaviour.
    if len(candidates) <= bounded_batch:
        plan = engine.build_dream_plan(delta, limit=limit, advanced_dreaming=advanced_dreaming)
        return list(maintainer.propose_actions(delta=delta, plan=plan) or []), 1

    batches = [candidates[i : i + bounded_batch] for i in range(0, len(candidates), bounded_batch)]
    batches = batches[: max(1, int(max_batches))]
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    calls = 0
    for index, batch in enumerate(batches):
        sub_delta = dict(delta)
        sub_delta["memory_candidates"] = batch
        sub_delta["candidate_ids"] = [
            str(item.get("id")) for item in batch if item.get("status") == "draft"
        ]
        counts = dict(delta.get("counts") or {})
        counts["memory_candidates"] = len(batch)
        counts["draft_candidates"] = len(sub_delta["candidate_ids"])
        # Non-candidate work (plan proposals, associations, pending notes) only
        # needs proposing once; keep it on the first batch so the model does not
        # re-propose the same page/plan actions for every chunk.
        if index > 0:
            for key in ("pending_plan_proposals", "association_suggestions", "w0_pending", "changed_plan_items"):
                sub_delta[key] = []
                if key in counts:
                    counts[key] = 0
        sub_delta["counts"] = counts
        plan = engine.build_dream_plan(sub_delta, limit=limit, advanced_dreaming=advanced_dreaming)
        proposed = maintainer.propose_actions(delta=sub_delta, plan=plan) or []
        calls += 1
        for action in proposed:
            key = _dream_action_identity(action)
            if key in seen:
                continue
            seen.add(key)
            merged.append(action)
    return merged, calls


def _dream_action_identity(action: dict[str, Any]) -> str:
    if not isinstance(action, dict):
        return repr(action)
    tool = str(action.get("tool") or "")
    for field in ("candidate_id", "page_id", "proposal_id", "plan_proposal_id", "memory_id", "id"):
        value = action.get(field)
        if value:
            return f"{tool}:{field}:{value}"
    source, target = action.get("source_id"), action.get("target_id")
    if source or target:
        return f"{tool}:link:{source}->{target}"
    title = action.get("title") or action.get("claim")
    if title:
        return f"{tool}:title:{' '.join(str(title).split()).casefold()}"
    return f"{tool}:{sorted((str(k), str(v)) for k, v in action.items() if k != 'tool')}"


def _item_timestamp(item: dict[str, Any]) -> float:
    value = item.get("updated_at", item.get("created_at", 0.0))
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _clean_user_uid(value: Any) -> str:
    text = str(value or "").strip()
    if text.casefold().startswith("user:"):
        text = text.split(":", 1)[1].strip()
    return text


def _required_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if field == "title":
        text = " ".join(text.split())
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _scope_text(value: Any) -> str:
    return str(value or "").strip() or "global"


def _scope_from_uid(scope: Any, uid: str | None) -> str:
    clean_uid = str(uid or "").strip()
    if clean_uid:
        return clean_uid if clean_uid.casefold().startswith("user:") else f"user:{clean_uid}"
    return _scope_text(scope)


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
    plan_proposal = _heuristic_event_plan_proposal(text, scope=scope)
    if plan_proposal:
        return {
            "kind": "event_memory_extraction",
            "strategy": "heuristic",
            "facts": [],
            "observations": [],
            "plan_proposals": [plan_proposal],
        }
    fact = _heuristic_event_fact(text, scope=scope)
    if fact:
        return {
            "kind": "event_memory_extraction",
            "strategy": "heuristic",
            "facts": [fact],
            "observations": [],
            "plan_proposals": [],
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
        "plan_proposals": [],
    }


def _merge_event_extractions(local: dict[str, Any], provider: dict[str, Any]) -> dict[str, Any]:
    facts = _dict_list(provider.get("facts"))
    observations = _dict_list(provider.get("observations"))
    provider_plans = _dict_list(provider.get("plan_proposals")) or _dict_list(provider.get("plans"))
    if not facts and not observations and not provider_plans:
        return local
    local_facts = _dict_list(local.get("facts"))
    local_observations = _dict_list(local.get("observations"))
    local_plans = _dict_list(local.get("plan_proposals")) or _dict_list(local.get("plans"))
    return {
        "kind": "event_memory_extraction",
        "strategy": "provider",
        "fallback": local,
        "facts": _dedupe_extraction_items([*facts, *local_facts], "claim"),
        "observations": _dedupe_extraction_items([*observations, *local_observations], "content"),
        "plan_proposals": _dedupe_extraction_items([*provider_plans, *local_plans], "title"),
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


def _heuristic_event_plan_proposal(text: str, *, scope: str) -> dict[str, Any] | None:
    if not _has_plan_memory_marker(text):
        return None
    title = _plan_subject(text)
    kind = "todo" if _has_todo_memory_marker(text) else "goal"
    return {
        "kind": kind,
        "title": title,
        "detail": _normalize_event_text(text),
        "scope": scope,
        "priority": "high" if _has_high_priority_marker(text) else "normal",
        "confidence": 0.78,
        "reason": "explicit_user_plan_or_todo",
        "metadata": {"extraction": "heuristic"},
    }


def _has_preference_memory_marker(text: str) -> bool:
    lowered = f" {text.casefold()} "
    return any(marker in lowered for marker in _PREFERENCE_EVENT_MARKERS)


def _has_future_memory_marker(text: str) -> bool:
    lowered = f" {text.casefold()} "
    return any(marker in lowered for marker in _FUTURE_EVENT_MARKERS)


def _has_goal_memory_marker(text: str) -> bool:
    lowered = f" {text.casefold()} "
    return any(marker in lowered for marker in _GOAL_EVENT_MARKERS)


def _has_plan_memory_marker(text: str) -> bool:
    lowered = f" {text.casefold()} "
    return any(marker in lowered for marker in (*_GOAL_EVENT_MARKERS, *_TODO_EVENT_MARKERS))


def _has_todo_memory_marker(text: str) -> bool:
    lowered = f" {text.casefold()} "
    return any(marker in lowered for marker in _TODO_EVENT_MARKERS)


def _has_high_priority_marker(text: str) -> bool:
    lowered = f" {text.casefold()} "
    return any(marker in lowered for marker in _HIGH_PRIORITY_MARKERS)


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


def _plan_subject(text: str) -> str:
    result = _normalize_event_text(text).strip("。.!！?")
    for marker in (*_PLAN_STRIP_MARKERS, *_GOAL_STRIP_MARKERS):
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


def _dedupe_extraction_items(items: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        value = _normalize_event_text(item.get(key) or item.get("title") or item.get("claim") or item.get("content"))
        fingerprint = value.casefold()
        if fingerprint and fingerprint in seen:
            continue
        if fingerprint:
            seen.add(fingerprint)
        result.append(item)
    return result


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


def _normalize_plan_proposal(proposal: Any) -> dict[str, Any]:
    if not isinstance(proposal, dict):
        return {
            "kind": "todo",
            "title": "",
            "detail": "",
            "scope": "global",
            "priority": "normal",
            "confidence": 0.5,
            "reason": "",
            "metadata": {},
        }
    title = _normalize_event_text(proposal.get("title") or proposal.get("task") or proposal.get("goal") or "")
    kind = str(proposal.get("kind") or ("todo" if proposal.get("task") else "goal")).strip().casefold()
    if kind not in {"goal", "todo"}:
        kind = "todo"
    priority = str(proposal.get("priority") or "normal").strip().casefold()
    if priority not in {"low", "normal", "high"}:
        priority = "normal"
    metadata = proposal.get("metadata") if isinstance(proposal.get("metadata"), dict) else {}
    return {
        "kind": kind,
        "title": title,
        "detail": _normalize_event_text(proposal.get("detail") or proposal.get("description") or ""),
        "scope": str(proposal.get("scope") or "global"),
        "parent_id": _optional_text(proposal.get("parent_id")),
        "status": _optional_text(proposal.get("status")),
        "priority": priority,
        "due_at": proposal.get("due_at"),
        "confidence": _confidence(proposal.get("confidence"), default=0.5),
        "reason": _normalize_event_text(proposal.get("reason") or proposal.get("rationale") or ""),
        "metadata": metadata,
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

_TODO_EVENT_MARKERS = (
    "待办",
    "todo",
    "to-do",
    "todolist",
    "要做",
    "需要做",
    "准备做",
    "提醒我",
    "记得",
    "安排",
    "任务",
    " next step ",
    " follow up ",
    " remind me ",
)

_HIGH_PRIORITY_MARKERS = (
    "紧急",
    "尽快",
    "马上",
    "今天",
    " priority high ",
    " urgent ",
    " asap ",
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

_PLAN_STRIP_MARKERS = (
    "我的",
    "请",
    "帮我",
    "待办是",
    "待办",
    "todo",
    "to-do",
    "需要做",
    "要做",
    "准备做",
    "提醒我",
    "记得",
    "安排",
    "任务是",
)


def _confidence(value: Any, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, parsed))
