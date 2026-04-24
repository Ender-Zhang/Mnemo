from __future__ import annotations

from dataclasses import asdict
import time
from typing import Any

from .ids import new_id
from .models import ChatEvent, ChatEventType


def new_chat_event(
    event_type: ChatEventType,
    *,
    run_id: str,
    conversation_id: str,
    mission_id: str,
    data: dict[str, Any] | None = None,
) -> ChatEvent:
    return ChatEvent(
        event_id=new_id("evt"),
        type=event_type,
        run_id=run_id,
        conversation_id=conversation_id,
        mission_id=mission_id,
        data=data or {},
        created_at=time.time(),
    )


def chat_event_as_dict(event: ChatEvent) -> dict[str, Any]:
    return asdict(event)
