from __future__ import annotations

from copy import deepcopy
from typing import Any


_SCHEMA: dict[str, Any] = {
    "schema_version": "mnemo.core_api.v1",
    "title": "MnemoCore",
    "description": "Compact personal AI OS API for SDK, MCP, CLI, and external runtime integrations.",
    "transport": {
        "current": ["python:in_process", "cli:schema"],
        "planned": ["mcp", "http", "runtime_adapter"],
    },
    "methods": {
        "context": {
            "description": "Return prompt-ready compact personal context for an external agent turn.",
            "side_effects": "read_only",
            "input_schema": {
                "type": "object",
                "properties": {
                    "intent": {"type": "string", "default": ""},
                    "agent_role": {"type": "string", "default": "general"},
                    "budget_tokens": {"type": "integer", "default": 4000, "minimum": 512},
                    "include_associations": {"type": "boolean", "default": True},
                    "prompt_mode": {"type": "string", "enum": ["full", "minimal", "capsule"], "default": "full"},
                },
                "additionalProperties": False,
            },
            "output_schema": {
                "type": "object",
                "required": ["kind", "messages", "metadata", "tool_bundle"],
                "properties": {
                    "kind": {"const": "context_block"},
                    "messages": {"type": "array"},
                    "metadata": {"type": "object"},
                    "tool_bundle": {"type": "object"},
                    "cards": {"type": "object"},
                    "text": {"type": "string"},
                },
            },
        },
        "recall": {
            "description": "Return compact associative recall cards from memory and prior session snippets.",
            "side_effects": "read_only",
            "input_schema": {
                "type": "object",
                "properties": {
                    "seed": {"type": "string"},
                    "depth": {"type": "integer", "default": 2, "minimum": 1, "maximum": 4},
                    "context": {"type": "string", "default": ""},
                    "limit": {"type": "integer", "default": 8, "minimum": 1, "maximum": 20},
                },
                "required": ["seed"],
                "additionalProperties": False,
            },
            "output_schema": {
                "type": "object",
                "required": ["kind", "seed", "items"],
                "properties": {
                    "kind": {"const": "associative_cluster"},
                    "seed": {"type": "string"},
                    "query_plan": {"type": "object"},
                    "items": {"type": "array"},
                },
            },
        },
        "run": {
            "description": "Execute one native Mnemo turn through the existing runtime harness.",
            "side_effects": "writes_run_ledger_and_runtime_state",
            "input_schema": {
                "type": "object",
                "properties": {
                    "message": {"type": "string"},
                    "conversation_id": {"type": ["string", "null"]},
                    "mission_id": {"type": ["string", "null"]},
                    "prompt_mode": {"type": "string", "enum": ["full", "minimal", "capsule"], "default": "full"},
                },
                "required": ["message"],
                "additionalProperties": False,
            },
            "output_schema": {
                "type": "object",
                "required": ["run_id", "conversation_id", "mission_id", "response", "tool_summary"],
                "properties": {
                    "run_id": {"type": "string"},
                    "conversation_id": {"type": "string"},
                    "mission_id": {"type": "string"},
                    "response": {"type": "string"},
                    "tool_summary": {"type": "array"},
                    "event_summary": {"type": "object"},
                },
            },
        },
        "replay": {
            "description": "Summarize a persisted run trace for debugging and harness replay.",
            "side_effects": "read_only",
            "input_schema": {
                "type": "object",
                "properties": {"run_id": {"type": "string"}},
                "required": ["run_id"],
                "additionalProperties": False,
            },
            "output_schema": {"type": "object"},
        },
        "evaluate": {
            "description": "Run a deterministic Mnemo eval suite and return a compact report.",
            "side_effects": "eval_state_only",
            "input_schema": {
                "type": "object",
                "properties": {"suite": {"type": "string", "default": "smoke"}},
                "additionalProperties": False,
            },
            "output_schema": {"type": "object"},
        },
    },
}


def mnemo_core_api_schema() -> dict[str, Any]:
    return deepcopy(_SCHEMA)
