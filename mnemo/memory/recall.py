from __future__ import annotations

from typing import Any

from .cards import _candidate_result, _context_card, _is_prompt_context_item, _page_result, _session_result
from .constants import PRIVATE_DELETE_TOMBSTONE_REASON
from .query import MemoryQueryPlan, annotate_memory_match, build_memory_query_plan, fuse_ranked_batches
from .utils import _is_tombstone_status, _keywords, _normalize_search_scope, _normalize_space


class MemoryRecallMixin:
    def plan_query(self, query: str) -> MemoryQueryPlan:
        return build_memory_query_plan(query, l1_snapshot=self.load_l1_snapshot())

    def search_with_plan(
        self,
        query: str,
        limit: int = 5,
        *,
        search_scope: str = "memory",
        include_tombstoned: bool = False,
    ) -> dict[str, Any]:
        plan = self.plan_query(query)
        if not plan.original:
            return {"query_plan": plan.metadata(), "matches": []}
        matches, recall_policy = self._search_from_plan(
            plan,
            limit=limit,
            search_scope=search_scope,
            include_tombstoned=include_tombstoned,
        )
        return {
            "query_plan": plan.metadata(),
            "matches": matches,
            "recall_policy": recall_policy,
        }

    def search(
        self,
        query: str,
        limit: int = 5,
        *,
        search_scope: str = "memory",
        include_tombstoned: bool = False,
    ) -> list[dict[str, Any]]:
        return self.search_with_plan(
            query,
            limit=limit,
            search_scope=search_scope,
            include_tombstoned=include_tombstoned,
        )["matches"]

    def _search_from_plan(
        self,
        plan: MemoryQueryPlan,
        *,
        limit: int,
        search_scope: str,
        include_tombstoned: bool,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        normalized_scope = _normalize_search_scope(search_scope)
        bounded_limit = max(1, int(limit))

        results: list[dict[str, Any]] = []
        recall_policy: dict[str, Any] = {}
        if normalized_scope in {"memory", "all"}:
            memory_results = self._search_memory_routes(plan, limit=bounded_limit)
            results.extend(memory_results)
            page_seeds = [item for item in memory_results if item["type"] == "page"]
            results.extend(
                self._associated_pages(
                    page_seeds,
                    seen_ids={item["id"] for item in results},
                    limit=bounded_limit,
                    plan=plan,
                )
            )

        if normalized_scope in {"sessions", "all"}:
            session_results, session_policy = self._search_session_routes(
                plan,
                limit=bounded_limit,
                include_tombstoned=include_tombstoned,
            )
            results.extend(session_results)
            recall_policy["tombstone_filter"] = session_policy
        return results, recall_policy

    def _search_memory_routes(self, plan: MemoryQueryPlan, *, limit: int) -> list[dict[str, Any]]:
        batches: list[tuple[str, str, list[dict[str, Any]]]] = []
        for route in plan.routes():
            query = route["query"]
            pages = [
                _page_result(page)
                for page in self.store.search_memory_pages(query, limit=max(limit, 1))
            ]
            candidates = [
                _candidate_result(candidate)
                for candidate in self.store.search_memory_candidates(query, limit=max(limit, 1))
            ]
            batches.append((route["route"], query, [*pages, *candidates]))
        return fuse_ranked_batches(batches, plan=plan, limit=max(limit * 2, 1))

    def _search_session_routes(
        self,
        plan: MemoryQueryPlan,
        *,
        limit: int,
        include_tombstoned: bool,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        search_session_messages = getattr(self.store, "search_session_messages", None)
        if not search_session_messages:
            return [], _session_tombstone_policy(enabled=not include_tombstoned, tombstones=[], suppressed=[])
        batches: list[tuple[str, str, list[dict[str, Any]]]] = []
        tombstones = [] if include_tombstoned else _session_suppression_tombstones(self.store)
        suppressed: list[dict[str, Any]] = []
        seen_suppressed: set[tuple[str, str]] = set()
        route_limit = min(100, max(limit * 4, limit))
        for route in plan.routes():
            route_items: list[dict[str, Any]] = []
            messages = [
                _session_result(message)
                for message in search_session_messages(route["query"], limit=max(route_limit, 1))
            ]
            for message in messages:
                tombstone = None if include_tombstoned else _matching_session_tombstone(message, tombstones)
                if tombstone:
                    _append_suppressed_session(
                        suppressed,
                        seen_suppressed,
                        message=message,
                        tombstone=tombstone,
                        route=route,
                    )
                    continue
                route_items.append(message)
            batches.append((route["route"], route["query"], route_items))
        return (
            fuse_ranked_batches(batches, plan=plan, limit=max(limit, 1)),
            _session_tombstone_policy(enabled=not include_tombstoned, tombstones=tombstones, suppressed=suppressed),
        )

    def context_cards(
        self,
        query: str,
        limit: int = 5,
        *,
        search_scope: str = "memory",
        include_tombstoned: bool = False,
    ) -> list[dict[str, Any]]:
        return [
            _context_card(item)
            for item in self.search(
                query,
                limit=limit,
                search_scope=search_scope,
                include_tombstoned=include_tombstoned,
            )
            if _is_prompt_context_item(item)
        ]

    def _associated_pages(
        self,
        pages: list[dict[str, Any]],
        *,
        seen_ids: set[str],
        limit: int,
        plan: MemoryQueryPlan,
    ) -> list[dict[str, Any]]:
        associated: list[dict[str, Any]] = []
        max_associations = max(0, int(limit))
        if not pages or max_associations == 0:
            return associated

        for page in pages:
            page_id = page["id"]
            for link, linked_page_id in self._page_association_links(page_id):
                if linked_page_id in seen_ids:
                    continue
                linked_page = self._get_page(linked_page_id)
                if not linked_page or linked_page.get("status") != "active":
                    continue
                associated.append(
                    annotate_memory_match(
                        {
                            "type": "linked_page",
                            "id": linked_page["id"],
                            "title": linked_page["title"],
                            "content": linked_page["content"],
                            "scope": linked_page["scope"],
                            "confidence": linked_page["confidence"],
                            "status": linked_page["status"],
                            "source_candidate_id": linked_page.get("source_candidate_id"),
                            "relation": link["relation"],
                            "linked_from": page_id,
                            "link_id": link["id"],
                            "link_weight": link["weight"],
                            "match_signals": [
                                {"route": "wiki", "query": page.get("title") or page_id, "rank": len(associated) + 1}
                            ],
                        },
                        plan,
                        score=float(link.get("weight", 0.0)),
                    )
                )
                seen_ids.add(linked_page_id)
                if len(associated) >= max_associations:
                    return associated
        return associated

    def _page_association_links(self, page_id: str) -> list[tuple[dict[str, Any], str]]:
        links: list[tuple[dict[str, Any], str]] = []
        list_links = getattr(self.store, "list_memory_links", None)
        if list_links:
            links.extend((link, link["target_id"]) for link in list_links(page_id))

        list_backlinks = getattr(self.store, "list_memory_backlinks", None)
        if list_backlinks:
            links.extend((link, link["source_id"]) for link in list_backlinks(page_id))

        return sorted(
            links,
            key=lambda item: (
                -float(item[0].get("weight", 0.0)),
                -float(item[0].get("created_at", 0.0)),
                item[0].get("id", ""),
            ),
        )


def _session_suppression_tombstones(store: Any, *, limit: int = 100) -> list[dict[str, Any]]:
    list_tombstones = getattr(store, "list_memory_tombstones", None)
    if not list_tombstones:
        return []
    return [
        tombstone
        for tombstone in list_tombstones(limit=limit)
        if _is_private_delete_tombstone(tombstone)
        or _tombstone_signal_terms(tombstone)
        or _tombstone_signal_phrase(tombstone)
    ]

def _matching_session_tombstone(message: dict[str, Any], tombstones: list[dict[str, Any]]) -> dict[str, Any] | None:
    snippet = _normalize_space(str(message.get("snippet") or ""))
    if not snippet:
        return None
    snippet_text = snippet.casefold()
    snippet_terms = set(_keywords(snippet))
    for tombstone in tombstones:
        if _is_private_delete_tombstone(tombstone):
            if _private_delete_tombstone_matches_session(message, tombstone):
                return tombstone
            continue
        phrase = _tombstone_signal_phrase(tombstone)
        if phrase and phrase.casefold() in snippet_text:
            return tombstone
        terms = _tombstone_signal_terms(tombstone)
        if not terms:
            continue
        overlap = terms & snippet_terms
        if len(terms) == 1:
            term = next(iter(terms))
            if len(term) >= 5 and term in overlap:
                return tombstone
            continue
        if len(overlap) >= min(2, len(terms)):
            return tombstone
    return None

def _append_suppressed_session(
    suppressed: list[dict[str, Any]],
    seen: set[tuple[str, str]],
    *,
    message: dict[str, Any],
    tombstone: dict[str, Any],
    route: dict[str, str],
) -> None:
    tombstone_id = str(tombstone.get("id") or "")
    message_id = str(message.get("message_id") or message.get("id") or "")
    key = (message_id, tombstone_id)
    if not key[0] or not key[1] or key in seen:
        return
    seen.add(key)
    suppressed.append(
        {
            "message_id": message_id,
            "conversation_id": message.get("conversation_id"),
            "mission_id": message.get("mission_id"),
            "run_id": message.get("run_id"),
            "tombstone_id": tombstone_id,
            "target_id": tombstone.get("target_id"),
            "target_type": tombstone.get("target_type"),
            "reason": tombstone.get("reason"),
            "route": route.get("route"),
        }
    )

def _session_tombstone_policy(
    *,
    enabled: bool,
    tombstones: list[dict[str, Any]],
    suppressed: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "enabled": enabled,
        "tombstone_count": len(tombstones),
        "suppressed": len(suppressed),
        "suppressed_items": suppressed[:10],
    }

def _tombstone_signal_phrase(tombstone: dict[str, Any]) -> str:
    summary = _normalize_space(str(tombstone.get("summary") or ""))
    return summary if len(summary) >= 8 else ""

def _tombstone_signal_terms(tombstone: dict[str, Any]) -> set[str]:
    metadata = tombstone.get("metadata") if isinstance(tombstone.get("metadata"), dict) else {}
    values = [
        tombstone.get("summary"),
        metadata.get("title"),
        metadata.get("scope"),
    ]
    return set(_keywords(" ".join(str(value or "") for value in values)))

def _is_private_delete_tombstone(tombstone: dict[str, Any]) -> bool:
    metadata = tombstone.get("metadata") if isinstance(tombstone.get("metadata"), dict) else {}
    return (
        tombstone.get("reason") == PRIVATE_DELETE_TOMBSTONE_REASON
        or metadata.get("redaction") == PRIVATE_DELETE_TOMBSTONE_REASON
    )

def _private_delete_tombstone_matches_session(message: dict[str, Any], tombstone: dict[str, Any]) -> bool:
    evidence_run_id = str(tombstone.get("evidence_run_id") or "")
    return bool(evidence_run_id and evidence_run_id == str(message.get("run_id") or ""))
