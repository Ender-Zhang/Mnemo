from __future__ import annotations

from typing import Any


class MemoryStoreAccessMixin:
    def _get_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        get_candidate = getattr(self.store, "get_memory_candidate", None)
        if get_candidate:
            return get_candidate(candidate_id)

        candidates = self.store.list_memory_candidates(status=None, limit=1000)
        return next((candidate for candidate in candidates if candidate["id"] == candidate_id), None)

    def _get_page(self, page_id: str) -> dict[str, Any] | None:
        get_page = getattr(self.store, "get_memory_page", None)
        if get_page:
            return get_page(page_id)
        return None

    def _promoted_page_ids(self, candidate_id: str) -> list[str]:
        page_ids: list[str] = []
        list_links = getattr(self.store, "list_memory_links", None)
        if list_links:
            for link in list_links(candidate_id):
                if link.get("relation") != "promoted_to":
                    continue
                page_id = str(link.get("target_id") or "")
                if page_id and page_id not in page_ids:
                    page_ids.append(page_id)

        list_pages = getattr(self.store, "list_memory_pages", None)
        if list_pages:
            for page in list_pages(status=None, limit=1000):
                page_id = str(page.get("id") or "")
                if page.get("source_candidate_id") == candidate_id and page_id and page_id not in page_ids:
                    page_ids.append(page_id)
        return page_ids
