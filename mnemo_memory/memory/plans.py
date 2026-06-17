from __future__ import annotations

from typing import Any


ACTIVE_PLAN_STATUSES = {
    "goal": ("active", "paused"),
    "todo": ("open", "doing"),
}


class MemoryPlanMixin:
    def create_plan_item(
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
    ) -> dict[str, Any]:
        item = self.store.add_plan_item(
            kind=kind,
            title=title,
            detail=detail,
            scope=scope,
            parent_id=parent_id,
            status=status,
            priority=priority,
            due_at=due_at,
            source=source,
            source_event_id=source_event_id,
            metadata=metadata,
        )
        return {"kind": "plan_item_create", "version": "mnemo_memory.plan.v1", "item": item}

    def read_plan_item(self, item_id: str) -> dict[str, Any]:
        item = _require_plan_item(self.store, item_id)
        return {"kind": "plan_item_read", "version": "mnemo_memory.plan.v1", "item": item}

    def update_plan_item(self, item_id: str, **fields: Any) -> dict[str, Any]:
        item = self.store.update_plan_item(item_id, **_clean_update_fields(fields))
        return {"kind": "plan_item_update", "version": "mnemo_memory.plan.v1", "item": item}

    def list_plan_items(
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
        clean_query = " ".join(str(query or "").split())
        if clean_query:
            items = self.store.search_plan_items(
                clean_query,
                kind=kind,
                status=status,
                uid=uid,
                limit=limit,
            )
            if scope:
                items = [item for item in items if item.get("scope") == scope]
            if not include_archived:
                items = [item for item in items if item.get("status") != "archived"]
        else:
            items = self.store.list_plan_items(
                kind=kind,
                status=status,
                scope=scope,
                uid=uid,
                limit=limit,
                include_archived=include_archived,
            )
        return {
            "kind": "plan_item_list",
            "version": "mnemo_memory.plan.v1",
            "item_kind": kind,
            "status": status,
            "scope": scope,
            "uid": uid,
            "query": clean_query,
            "count": len(items),
            "items": items,
        }

    def complete_plan_item(self, item_id: str) -> dict[str, Any]:
        item = _require_plan_item(self.store, item_id)
        next_status = "completed" if item.get("kind") == "goal" else "done"
        updated = self.store.update_plan_item(item["id"], status=next_status)
        return {"kind": "plan_item_complete", "version": "mnemo_memory.plan.v1", "item": updated}

    def cancel_plan_item(self, item_id: str, reason: str = "cancelled") -> dict[str, Any]:
        item = _require_plan_item(self.store, item_id)
        metadata = dict(item.get("metadata") if isinstance(item.get("metadata"), dict) else {})
        if reason:
            metadata["cancel_reason"] = " ".join(str(reason).split())
        updated = self.store.update_plan_item(item["id"], status="cancelled", metadata=metadata)
        return {"kind": "plan_item_cancel", "version": "mnemo_memory.plan.v1", "item": updated}

    def archive_plan_item(self, item_id: str) -> dict[str, Any]:
        item = _require_plan_item(self.store, item_id)
        updated = self.store.update_plan_item(item["id"], status="archived")
        return {"kind": "plan_item_archive", "version": "mnemo_memory.plan.v1", "item": updated}

    def create_plan_proposal(
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
    ) -> dict[str, Any]:
        proposal = self.store.add_plan_proposal(
            kind=kind,
            title=title,
            detail=detail,
            scope=scope,
            action=action,
            target_id=target_id,
            parent_id=parent_id,
            status=status,
            priority=priority,
            due_at=due_at,
            confidence=confidence,
            reason=reason,
            source=source,
            source_event_id=source_event_id,
            metadata=metadata,
        )
        return {"kind": "plan_proposal_create", "version": "mnemo_memory.plan.v1", "proposal": proposal}

    def plan_proposals(
        self,
        *,
        status: str | None = "pending",
        scope: str | None = None,
        uid: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        proposals = self.store.list_plan_proposals(status=status, scope=scope, uid=uid, limit=limit)
        return {
            "kind": "plan_proposals",
            "version": "mnemo_memory.plan.v1",
            "status": status,
            "scope": scope,
            "uid": uid,
            "count": len(proposals),
            "proposals": proposals,
        }

    def apply_plan_proposal(self, proposal_id: str) -> dict[str, Any]:
        proposal = _require_pending_plan_proposal(self.store, proposal_id)
        action = str(proposal.get("action") or "create")
        if action == "create":
            item = self.store.add_plan_item(
                kind=str(proposal.get("kind") or "todo"),
                title=str(proposal.get("title") or ""),
                detail=str(proposal.get("detail") or ""),
                scope=str(proposal.get("scope") or "global"),
                parent_id=proposal.get("parent_id"),
                status=proposal.get("status"),
                priority=str(proposal.get("priority") or "normal"),
                due_at=proposal.get("due_at"),
                source=str(proposal.get("source") or "proposal"),
                source_event_id=proposal.get("source_event_id"),
                metadata={
                    **(proposal.get("metadata") if isinstance(proposal.get("metadata"), dict) else {}),
                    "source_plan_proposal_id": proposal["id"],
                },
            )
            result: dict[str, Any] = {"action": "create", "item": item}
        elif action == "update":
            target_id = str(proposal.get("target_id") or "").strip()
            if not target_id:
                raise ValueError("update plan proposal requires target_id")
            item = self.store.update_plan_item(
                target_id,
                kind=proposal.get("kind"),
                parent_id=proposal.get("parent_id"),
                title=proposal.get("title"),
                detail=proposal.get("detail"),
                scope=proposal.get("scope"),
                status=proposal.get("status"),
                priority=proposal.get("priority"),
                due_at=proposal.get("due_at"),
            )
            result = {"action": "update", "item": item}
        else:
            raise ValueError(f"unsupported plan proposal action: {action}")
        updated = self.store.update_plan_proposal_status(proposal["id"], "accepted", reason="operator_accepted")
        return {
            "kind": "plan_proposal_apply",
            "version": "mnemo_memory.plan.v1",
            "proposal_id": updated["id"],
            "result": result,
            "proposal": updated,
        }

    def reject_plan_proposal(self, proposal_id: str, reason: str = "operator_rejected") -> dict[str, Any]:
        proposal = _require_pending_plan_proposal(self.store, proposal_id)
        updated = self.store.update_plan_proposal_status(
            proposal["id"],
            "rejected",
            reason=" ".join(str(reason or "operator_rejected").split()) or "operator_rejected",
        )
        return {
            "kind": "plan_proposal_reject",
            "version": "mnemo_memory.plan.v1",
            "proposal_id": updated["id"],
            "proposal": updated,
        }

    def active_plan_context_items(self, query: str = "", *, uid: str | None = None, limit: int = 4) -> list[dict[str, Any]]:
        statuses = [*ACTIVE_PLAN_STATUSES["goal"], *ACTIVE_PLAN_STATUSES["todo"]]
        clean_query = " ".join(str(query or "").split())
        if clean_query:
            return self.store.search_plan_items(clean_query, status=statuses, uid=uid, limit=limit)
        return self.store.list_plan_items(status=statuses, uid=uid, limit=limit, include_archived=False)


def _require_plan_item(store: Any, item_id: str) -> dict[str, Any]:
    clean_id = str(item_id or "").strip()
    if not clean_id:
        raise ValueError("plan item id is required")
    item = store.get_plan_item(clean_id)
    if not item:
        raise ValueError(f"plan item not found: {clean_id}")
    return item


def _require_pending_plan_proposal(store: Any, proposal_id: str) -> dict[str, Any]:
    clean_id = str(proposal_id or "").strip()
    if not clean_id:
        raise ValueError("plan proposal id is required")
    proposal = store.get_plan_proposal(clean_id)
    if not proposal:
        raise ValueError(f"plan proposal not found: {clean_id}")
    if proposal.get("proposal_status") != "pending":
        raise ValueError(f"plan proposal is not pending: {clean_id}")
    return proposal


def _clean_update_fields(fields: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in fields.items() if value is not None}
