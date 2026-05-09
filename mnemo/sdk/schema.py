from __future__ import annotations

from copy import deepcopy
from typing import Any


_SCHEMA: dict[str, Any] = {
    "schema_version": "mnemo.core_api.v1",
    "title": "MnemoCore",
    "description": "Compact personal AI OS API for SDK, MCP, CLI, and external runtime integrations.",
    "transport": {
        "current": [
            "python:in_process",
            "cli:schema",
            "runtime_adapter:command",
            "http:core_json",
            "mcp:stdio_content_length",
            "mcp:json_rpc_jsonl",
        ],
        "planned": ["http:generated_clients", "runtime_adapter:openclaw", "runtime_adapter:acp"],
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
        "capsule": {
            "description": "Build a minimal-disclosure context capsule for an external runtime handoff.",
            "side_effects": "read_only",
            "input_schema": {
                "type": "object",
                "properties": {
                    "task": {"type": "string"},
                    "runtime": {"type": "string", "default": "external"},
                    "agent_type": {"type": "string", "default": "general"},
                    "requested_pages": {"type": "array", "items": {"type": "string"}},
                    "allowed_pages": {"type": "array", "items": {"type": "string"}},
                    "conversation_id": {"type": ["string", "null"]},
                    "mission_id": {"type": ["string", "null"]},
                    "limit": {"type": "integer", "default": 8, "minimum": 1, "maximum": 50},
                },
                "required": ["task"],
                "additionalProperties": False,
            },
            "output_schema": {
                "type": "object",
                "required": ["kind", "task", "mission_brief", "memory_pointers", "return_contract"],
                "properties": {
                    "kind": {"const": "context_capsule"},
                    "capsule_id": {"type": "string"},
                    "runtime": {"type": "string"},
                    "agent_type": {"type": "string"},
                    "task": {"type": "string"},
                    "mission_brief": {"type": "object"},
                    "persona_min": {"type": "object"},
                    "memory_pointers": {"type": "array"},
                    "allowed_pages": {"type": "array"},
                    "return_contract": {"type": "object"},
                    "text": {"type": "string"},
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
        "external_run": {
            "description": "Execute an explicit command runtime with a minimal-disclosure context capsule and proposal-only return contract.",
            "side_effects": "process_spawn_writes_run_ledger_proposals_only",
            "input_schema": {
                "type": "object",
                "properties": {
                    "task": {"type": "string"},
                    "command": {"type": "array", "items": {"type": "string"}},
                    "runtime": {"type": "string", "default": "external-command"},
                    "agent_type": {"type": "string", "default": "general"},
                    "requested_pages": {"type": "array", "items": {"type": "string"}},
                    "allowed_pages": {"type": "array", "items": {"type": "string"}},
                    "conversation_id": {"type": ["string", "null"]},
                    "mission_id": {"type": ["string", "null"]},
                    "timeout_s": {"type": "number", "default": 30.0, "exclusiveMinimum": 0},
                },
                "required": ["task", "command"],
                "additionalProperties": False,
            },
            "output_schema": {
                "type": "object",
                "required": ["kind", "run_id", "conversation_id", "mission_id", "capsule", "proposal"],
                "properties": {
                    "kind": {"const": "external_runtime_result"},
                    "run_id": {"type": "string"},
                    "conversation_id": {"type": "string"},
                    "mission_id": {"type": "string"},
                    "capsule": {"type": "object"},
                    "proposal": {"type": "object"},
                    "ignored_fields": {"type": "array"},
                    "exit_code": {"type": "integer"},
                },
            },
        },
        "schedule_dream": {
            "description": "Register bounded Dream memory maintenance through the existing scheduler.",
            "side_effects": "writes_scheduled_item",
            "input_schema": {
                "type": "object",
                "properties": {
                    "schedule": {"type": "string", "default": "daily"},
                    "title": {"type": ["string", "null"]},
                    "next_run_at": {"type": ["string", "number", "null"]},
                    "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 200},
                    "min_confidence": {"type": "number", "default": 0.7, "minimum": 0.0, "maximum": 1.0},
                    "source": {"type": "string", "default": "sdk"},
                },
                "additionalProperties": False,
            },
            "output_schema": {
                "type": "object",
                "required": ["kind", "item"],
                "properties": {
                    "kind": {"const": "scheduled_item"},
                    "version": {"type": "string"},
                    "item": {"type": "object"},
                },
            },
        },
        "schedule_watch": {
            "description": "Register a durable Watch check through the existing scheduler.",
            "side_effects": "writes_scheduled_item",
            "input_schema": {
                "type": "object",
                "properties": {
                    "target": {"type": "string"},
                    "instruction": {"type": ["string", "null"]},
                    "schedule": {"type": "string", "default": "daily"},
                    "next_run_at": {"type": ["string", "number", "null"]},
                    "source": {"type": "string", "default": "sdk"},
                },
                "required": ["target"],
                "additionalProperties": False,
            },
            "output_schema": {
                "type": "object",
                "required": ["kind", "item"],
                "properties": {
                    "kind": {"const": "scheduled_item"},
                    "version": {"type": "string"},
                    "item": {"type": "object"},
                },
            },
        },
        "schedule_cron": {
            "description": "Register a durable queued Mnemo task through the existing scheduler.",
            "side_effects": "writes_scheduled_item",
            "input_schema": {
                "type": "object",
                "properties": {
                    "message": {"type": "string"},
                    "schedule": {"type": "string", "default": "once"},
                    "title": {"type": ["string", "null"]},
                    "next_run_at": {"type": ["string", "number", "null"]},
                    "source": {"type": "string", "default": "sdk"},
                },
                "required": ["message"],
                "additionalProperties": False,
            },
            "output_schema": {
                "type": "object",
                "required": ["kind", "item"],
                "properties": {
                    "kind": {"const": "scheduled_item"},
                    "version": {"type": "string"},
                    "item": {"type": "object"},
                },
            },
        },
        "runtime_status": {
            "description": "Return compact queue, run, inbox, generated-tool, scheduled-item, and proactive status.",
            "side_effects": "read_only",
            "input_schema": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
                },
                "additionalProperties": False,
            },
            "output_schema": {
                "type": "object",
                "required": [
                    "kind",
                    "queue",
                    "recent_runs",
                    "open_inbox",
                    "generated_tools",
                    "scheduled",
                    "proactive",
                ],
                "properties": {
                    "kind": {"const": "runtime_status"},
                    "version": {"type": "string"},
                    "queue": {"type": "object"},
                    "recent_runs": {"type": "array"},
                    "open_inbox": {"type": "object"},
                    "generated_tools": {"type": "object"},
                    "scheduled": {"type": "object"},
                    "proactive": {"type": "object"},
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
            "description": "Run a deterministic Mnemo eval suite, variant comparison, or release gate and return a compact report.",
            "side_effects": "eval_state_only",
            "input_schema": {
                "type": "object",
                "properties": {
                    "suite": {"type": "string", "default": "smoke"},
                    "release_gate": {
                        "type": "boolean",
                        "default": False,
                        "description": "Run the fixed core release gate; cannot be combined with variants.",
                    },
                    "variants": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["no_memory", "skills_only", "full_mnemo"]},
                    },
                },
                "additionalProperties": False,
            },
            "output_schema": {"type": "object"},
        },
    },
}


def mnemo_core_api_schema() -> dict[str, Any]:
    return deepcopy(_SCHEMA)
