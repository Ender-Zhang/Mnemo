from __future__ import annotations

from ..core.errors import MnemoError, NotFoundError
from ..core.models import RunRequest
from ..storage import StateStore


def resolve_conversation(store: StateStore, request: RunRequest, title: str | None = None) -> str:
    if not request.conversation_id:
        return store.create_conversation(title=title)
    if not store.get_conversation(request.conversation_id):
        raise NotFoundError(f"conversation not found: {request.conversation_id}")
    return request.conversation_id


def resolve_mission(store: StateStore, conversation_id: str, request: RunRequest, brief: str) -> str:
    if request.mission_id:
        mission = store.get_mission(request.mission_id)
        if not mission:
            raise NotFoundError(f"mission not found: {request.mission_id}")
        if mission["conversation_id"] != conversation_id:
            raise MnemoError("mission does not belong to the selected conversation")
        return request.mission_id

    latest = store.latest_active_mission(conversation_id)
    if latest:
        return str(latest["id"])
    return store.create_mission(conversation_id, brief=brief)
