from __future__ import annotations

import argparse
import json
from typing import Any

from .. import __version__
from ..core.config import ConfigOverrides, DEFAULT_STATE_DIR
from ..core.jsonutil import dumps
from ..mcp import MemoryMcpServer, mcp_server_config
from ..sdk import MemoryClient, memory_api_schema
from .web import MemoryWebConfig, serve_http


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            MemoryClient(state_dir=args.state_dir)._store()
            print(args.state_dir)
            return 0
        if args.command == "schema":
            _print(memory_api_schema(), args.json)
            return 0
        if args.command == "search":
            _print(MemoryClient(state_dir=args.state_dir).search(" ".join(args.query), limit=args.limit), args.json)
            return 0
        if args.command == "update":
            facts = json.loads(args.facts_json) if args.facts_json else args.facts
            _print(MemoryClient(state_dir=args.state_dir).update(facts=facts, source=args.source), args.json)
            return 0
        if args.command == "ingest-event":
            return _cmd_ingest_event(args)
        if args.command == "promote":
            _print(
                MemoryClient(state_dir=args.state_dir).promote_candidate(
                    args.candidate_id,
                    min_confidence=args.min_confidence,
                ),
                args.json,
            )
            return 0
        if args.command == "force-promote":
            _print(MemoryClient(state_dir=args.state_dir).force_promote_candidate(args.candidate_id), args.json)
            return 0
        if args.command == "reject":
            _print(MemoryClient(state_dir=args.state_dir).reject_candidate(args.candidate_id, args.reason), args.json)
            return 0
        if args.command == "health":
            _print(MemoryClient(state_dir=args.state_dir).health(limit=args.limit), args.json)
            return 0
        if args.command == "dream":
            return _cmd_dream(args)
        if args.command == "mcp":
            return _cmd_mcp(args)
        if args.command == "serve":
            serve_http(MemoryWebConfig(state_dir=args.state_dir, host=args.host, port=args.port, auth_token=args.auth_token))
            return 0
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}")
        return 2
    parser.print_help()
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mnemo-memory", description="Memory-only service for agent recall and learning.")
    parser.add_argument("--version", action="version", version=f"mnemo-memory {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    init = subparsers.add_parser("init", help="Initialize a memory state directory")
    _state(init)

    schema = subparsers.add_parser("schema", help="Print the memory API schema")
    schema.add_argument("--json", action="store_true")

    search = subparsers.add_parser("search", help="Search memory")
    _state(search)
    search.add_argument("query", nargs="+")
    search.add_argument("--limit", type=int, default=8)
    search.add_argument("--json", action="store_true")

    update = subparsers.add_parser("update", help="Write memory candidates")
    _state(update)
    update.add_argument("facts", nargs="*", default=[])
    update.add_argument("--facts-json")
    update.add_argument("--source", default="cli")
    update.add_argument("--json", action="store_true")

    ingest_event = subparsers.add_parser("ingest-event", help="Ingest one raw conversation event")
    _state(ingest_event)
    ingest_event.add_argument("text", nargs="+")
    ingest_event.add_argument("--context-json")
    ingest_event.add_argument("--source", default="cli")
    ingest_event.add_argument("--actor")
    ingest_event.add_argument("--event-type", default="message")
    ingest_event.add_argument("--run-id")
    ingest_event.add_argument("--mission-id")
    ingest_event.add_argument("--conversation-id")
    ingest_event.add_argument("--message-id")
    ingest_event.add_argument("--agent-id")
    ingest_event.add_argument("--scope")
    ingest_event.add_argument("--auto-promote", action="store_true")
    ingest_event.add_argument("--min-confidence", type=float, default=0.7)
    ingest_event.add_argument("--use-provider", action="store_true")
    ingest_event.add_argument("--provider")
    ingest_event.add_argument("--base-url")
    ingest_event.add_argument("--model")
    ingest_event.add_argument("--api-key")
    ingest_event.add_argument("--api-key-env")
    ingest_event.add_argument("--timeout-s", type=float)
    ingest_event.add_argument(
        "--thinking",
        dest="thinking_enabled",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Send provider payloads with thinking enabled; use --no-thinking to force it off.",
    )
    ingest_event.add_argument("--json", action="store_true")

    promote = subparsers.add_parser("promote", help="Review and promote a memory candidate")
    _state(promote)
    promote.add_argument("candidate_id")
    promote.add_argument("--min-confidence", type=float, default=0.7)
    promote.add_argument("--json", action="store_true")

    force_promote = subparsers.add_parser("force-promote", help="Force promote a candidate without review guards")
    _state(force_promote)
    force_promote.add_argument("candidate_id")
    force_promote.add_argument("--json", action="store_true")

    reject = subparsers.add_parser("reject", help="Reject a memory candidate")
    _state(reject)
    reject.add_argument("candidate_id")
    reject.add_argument("reason")
    reject.add_argument("--json", action="store_true")

    health = subparsers.add_parser("health", help="Report memory health")
    _state(health)
    health.add_argument("--limit", type=int, default=20)
    health.add_argument("--json", action="store_true")

    dream = subparsers.add_parser("dream", help="Run or inspect memory maintenance")
    _state(dream)
    dream.add_argument("dream_command", choices=["run", "status"], nargs="?", default="status")
    dream.add_argument("--limit", type=int, default=20)
    dream.add_argument("--min-confidence", type=float, default=0.7)
    dream.add_argument("--actions-json")
    dream.add_argument("--use-provider", action="store_true")
    dream.add_argument("--provider")
    dream.add_argument("--base-url")
    dream.add_argument("--model")
    dream.add_argument("--api-key")
    dream.add_argument("--api-key-env")
    dream.add_argument("--timeout-s", type=float)
    dream.add_argument(
        "--thinking",
        dest="thinking_enabled",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Send provider payloads with thinking enabled; use --no-thinking to force it off.",
    )
    dream.add_argument("--json", action="store_true")

    mcp = subparsers.add_parser("mcp", help="Expose MCP tools")
    _state(mcp)
    mcp_sub = mcp.add_subparsers(dest="mcp_command")
    mcp_sub.add_parser("tools")
    cfg = mcp_sub.add_parser("config")
    cfg.add_argument("--client", choices=["generic", "claude"], default="generic")
    cfg.add_argument("--server-command", default="mnemo-memory")
    call = mcp_sub.add_parser("call")
    call.add_argument("tool_name")
    call.add_argument("--arguments-json", default="{}")
    serve = mcp_sub.add_parser("serve")
    serve.add_argument("--transport", choices=["content-length", "jsonl"], default="content-length")
    for sub in [mcp, *mcp_sub.choices.values()]:
        if not any(action.dest == "json" for action in sub._actions):
            sub.add_argument("--json", action="store_true")

    serve_api = subparsers.add_parser("serve", help="Serve the HTTP JSON API and local WebUI")
    _state(serve_api)
    serve_api.add_argument("--host", default="127.0.0.1")
    serve_api.add_argument("--port", type=int, default=8765)
    serve_api.add_argument("--auth-token", help="Deprecated compatibility option; HTTP API access is open.")

    return parser


def _cmd_ingest_event(args: argparse.Namespace) -> int:
    context = json.loads(args.context_json) if args.context_json else []
    if not isinstance(context, list):
        raise ValueError("context-json must be a JSON array")
    config = ConfigOverrides(
        state_dir=args.state_dir,
        provider=args.provider,
        base_url=args.base_url,
        model=args.model,
        api_key=args.api_key,
        api_key_env=args.api_key_env,
        timeout_s=args.timeout_s,
        thinking_enabled=args.thinking_enabled,
    )
    _print(
        MemoryClient(state_dir=args.state_dir).ingest_event(
            text=" ".join(args.text),
            source=args.source,
            actor=args.actor,
            event_type=args.event_type,
            context=context,
            run_id=args.run_id,
            mission_id=args.mission_id,
            conversation_id=args.conversation_id,
            message_id=args.message_id,
            agent_id=args.agent_id,
            scope=args.scope,
            auto_promote=args.auto_promote,
            min_confidence=args.min_confidence,
            use_provider=args.use_provider,
            config=config,
        ),
        args.json,
    )
    return 0


def _cmd_dream(args: argparse.Namespace) -> int:
    client = MemoryClient(state_dir=args.state_dir)
    if args.dream_command == "run":
        actions = json.loads(args.actions_json) if args.actions_json else None
        config = ConfigOverrides(
            state_dir=args.state_dir,
            provider=args.provider,
            base_url=args.base_url,
            model=args.model,
            api_key=args.api_key,
            api_key_env=args.api_key_env,
            timeout_s=args.timeout_s,
            thinking_enabled=args.thinking_enabled,
        )
        _print(
            client.dream_run(
                limit=args.limit,
                min_confidence=args.min_confidence,
                actions=actions,
                use_provider=args.use_provider,
                config=config,
            ),
            args.json,
        )
        return 0
    _print(client.dream_status(limit=args.limit), args.json)
    return 0


def _cmd_mcp(args: argparse.Namespace) -> int:
    server = MemoryMcpServer(state_dir=args.state_dir)
    if args.mcp_command == "tools":
        _print({"tools": server.tools()}, args.json)
        return 0
    if args.mcp_command == "config":
        _print(mcp_server_config(client=args.client, command=args.server_command, state_dir=args.state_dir), args.json)
        return 0
    if args.mcp_command == "call":
        _print(server.call_tool(args.tool_name, json.loads(args.arguments_json)), args.json)
        return 0
    if args.mcp_command == "serve":
        if args.transport == "jsonl":
            server.serve_jsonl()
        else:
            server.serve_content_length()
        return 0
    raise ValueError("mcp command requires a subcommand")


def _state(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--state-dir", default=DEFAULT_STATE_DIR)


def _print(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(dumps(payload))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
