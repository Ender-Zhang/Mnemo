from __future__ import annotations

import argparse
import os
import sys
from typing import Sequence

from .. import __version__
from ..core.errors import MnemoError
from ..core.events import chat_event_as_dict
from ..core.jsonutil import dumps
from ..core.models import RunRequest
from ..memory import MemoryEngine
from ..providers import OpenAIProviderAdapter, ProviderConfig
from ..runtime import result_as_dict, run_local, stream_local
from ..runtime.ledger import RunLedger
from ..runtime.provider import run_provider, stream_provider
from ..skills import SkillService, default_skill_roots
from ..storage import StateStore
from ..tools import ToolRegistry, tool_specs_as_json_schema
from .web import WebServerConfig, serve_web


DEFAULT_STATE_DIR = "~/.mnemo"
DEFAULT_PROVIDER = "local"


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "init":
            return _cmd_init(args)
        if args.command == "run":
            return _cmd_run(args)
        if args.command == "events":
            return _cmd_events(args)
        if args.command == "memory":
            return _cmd_memory(args)
        if args.command == "dream":
            return _cmd_dream(args)
        if args.command == "prompt":
            return _cmd_prompt(args)
        if args.command == "replay":
            return _cmd_replay(args)
        if args.command == "skills":
            return _cmd_skills(args)
        if args.command == "tools":
            return _cmd_tools(args)
        if args.command == "web":
            return _cmd_web(args)
        parser.print_help()
        return 0
    except MnemoError as exc:
        print(f"mnemo: {exc}", file=sys.stderr)
        return 1
    except BrokenPipeError:
        sys.stdout = open(os.devnull, "w")
        return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mnemo", description="Mnemo personal AI runtime foundation")
    parser.add_argument("--version", action="version", version=f"mnemo {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    init_parser = subparsers.add_parser("init", help="Initialize a Mnemo state directory")
    _add_state_dir(init_parser)

    run_parser = subparsers.add_parser("run", help="Run one local agent turn")
    _add_state_dir(run_parser)
    run_parser.add_argument("message", nargs="+", help="User message")
    run_parser.add_argument("--conversation-id")
    run_parser.add_argument("--mission-id")
    run_parser.add_argument("--json", action="store_true", help="Print structured run result")
    run_parser.add_argument("--stream", action="store_true", help="Print newline-delimited ChatEvent JSON")
    run_parser.add_argument(
        "--provider",
        choices=["local", "openai-compatible"],
        default=None,
        help="Runtime provider (default: local, or MNEMO_PROVIDER)",
    )
    run_parser.add_argument("--base-url", help="OpenAI-compatible base URL, or MNEMO_BASE_URL")
    run_parser.add_argument("--model", help="Provider model name, or MNEMO_MODEL")
    run_parser.add_argument("--api-key", help="Provider API key. Prefer --api-key-env for shell history safety.")
    run_parser.add_argument("--api-key-env", help="Environment variable containing provider API key.")
    run_parser.add_argument("--timeout-s", type=float, help="Provider request timeout, or MNEMO_TIMEOUT_S")

    events_parser = subparsers.add_parser("events", help="Print RunLedger events for a run")
    _add_state_dir(events_parser)
    events_parser.add_argument("run_id")
    events_parser.add_argument("--since", type=int, default=0)
    events_parser.add_argument("--chat", action="store_true", help="Print ChatEvent payloads only")
    events_parser.add_argument("--json", action="store_true")

    replay_parser = subparsers.add_parser("replay", help="Summarize a run trace")
    _add_state_dir(replay_parser)
    replay_parser.add_argument("run_id")
    replay_parser.add_argument("--json", action="store_true")

    memory_parser = subparsers.add_parser("memory", help="Search and curate memory")
    memory_subparsers = memory_parser.add_subparsers(dest="memory_command")
    memory_search_parser = memory_subparsers.add_parser("search", help="Search memory pages and candidates")
    _add_state_dir(memory_search_parser)
    memory_search_parser.add_argument("query", nargs="+")
    memory_search_parser.add_argument("--limit", type=int, default=5)
    memory_search_parser.add_argument("--json", action="store_true")
    memory_promote_parser = memory_subparsers.add_parser("promote", help="Promote a memory candidate")
    _add_state_dir(memory_promote_parser)
    memory_promote_parser.add_argument("candidate_id")
    memory_promote_parser.add_argument("--json", action="store_true")
    memory_reject_parser = memory_subparsers.add_parser("reject", help="Reject a memory candidate")
    _add_state_dir(memory_reject_parser)
    memory_reject_parser.add_argument("candidate_id")
    memory_reject_parser.add_argument("--reason", default="not durable")
    memory_reject_parser.add_argument("--json", action="store_true")

    dream_parser = subparsers.add_parser("dream", help="Run idle consolidation cycles")
    dream_subparsers = dream_parser.add_subparsers(dest="dream_command")
    dream_run_parser = dream_subparsers.add_parser("run", help="Run deterministic memory consolidation")
    _add_state_dir(dream_run_parser)
    dream_run_parser.add_argument("--limit", type=int, default=20)
    dream_run_parser.add_argument("--min-confidence", type=float, default=0.7)
    dream_run_parser.add_argument("--json", action="store_true")

    prompt_parser = subparsers.add_parser("prompt", help="Inspect prompt assembly metadata")
    prompt_subparsers = prompt_parser.add_subparsers(dest="prompt_command")
    prompt_inspect_parser = prompt_subparsers.add_parser("inspect", help="Inspect a run's prompt assembly")
    _add_state_dir(prompt_inspect_parser)
    prompt_inspect_parser.add_argument("run_id")
    prompt_inspect_parser.add_argument("--json", action="store_true")

    skills_parser = subparsers.add_parser("skills", help="Scan, list, view, and promote skills")
    skills_subparsers = skills_parser.add_subparsers(dest="skills_command")
    skills_scan_parser = skills_subparsers.add_parser("scan", help="Scan Agent Skills roots")
    _add_state_dir(skills_scan_parser)
    skills_scan_parser.add_argument("--root", action="append", default=[], help="Additional skill root")
    skills_scan_parser.add_argument("--json", action="store_true")
    skills_list_parser = skills_subparsers.add_parser("list", help="List known skills")
    _add_state_dir(skills_list_parser)
    skills_list_parser.add_argument("--json", action="store_true")
    skills_view_parser = skills_subparsers.add_parser("view", help="View a skill")
    _add_state_dir(skills_view_parser)
    skills_view_parser.add_argument("name")
    skills_view_parser.add_argument("--json", action="store_true")
    skills_promote_parser = skills_subparsers.add_parser("promote", help="Promote a draft skill to SKILL.md")
    _add_state_dir(skills_promote_parser)
    skills_promote_parser.add_argument("name")
    skills_promote_parser.add_argument("--json", action="store_true")

    tools_parser = subparsers.add_parser("tools", help="Print available tool specs")
    tools_parser.add_argument("--json", action="store_true")

    web_parser = subparsers.add_parser("web", help="Run the Mnemo single-chat web UI")
    _add_state_dir(web_parser)
    web_parser.add_argument("--host", default="127.0.0.1")
    web_parser.add_argument("--port", type=int, default=8765)
    web_parser.add_argument(
        "--provider",
        choices=["local", "openai-compatible"],
        default=None,
        help="Runtime provider (default: local, or MNEMO_PROVIDER)",
    )
    web_parser.add_argument("--base-url", help="OpenAI-compatible base URL, or MNEMO_BASE_URL")
    web_parser.add_argument("--model", help="Provider model name, or MNEMO_MODEL")
    web_parser.add_argument("--api-key", help="Provider API key. Prefer --api-key-env for shell history safety.")
    web_parser.add_argument("--api-key-env", help="Environment variable containing provider API key.")
    web_parser.add_argument("--timeout-s", type=float, help="Provider request timeout, or MNEMO_TIMEOUT_S")
    return parser


def _add_state_dir(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--state-dir",
        default=DEFAULT_STATE_DIR,
        help=f"State directory (default: {DEFAULT_STATE_DIR})",
    )


def _cmd_init(args: argparse.Namespace) -> int:
    store = StateStore(args.state_dir)
    store.initialize()
    print(f"Initialized Mnemo state at {store.state_dir}")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    if args.json and args.stream:
        raise MnemoError("--json and --stream cannot be used together")

    message = " ".join(args.message)
    request = RunRequest(
        message=message,
        state_dir=args.state_dir,
        conversation_id=args.conversation_id,
        mission_id=args.mission_id,
    )
    provider_name = _provider_name(args)
    if args.stream:
        event_stream = (
            stream_local(request)
            if provider_name == "local"
            else stream_provider(request, _openai_compatible_adapter(args, stream=True))
        )
        for event in event_stream:
            print(dumps(chat_event_as_dict(event)), flush=True)
        return 0

    result = run_local(request) if provider_name == "local" else run_provider(request, _openai_compatible_adapter(args))
    if args.json:
        print(dumps(result_as_dict(result)))
        return 0

    print(result.response)
    print(f"conversation_id={result.conversation_id}")
    print(f"mission_id={result.mission_id}")
    print(f"run_id={result.run_id}")
    return 0


def _cmd_events(args: argparse.Namespace) -> int:
    store = StateStore(args.state_dir)
    store.initialize()
    ledger = RunLedger(store)
    events = ledger.chat_events(args.run_id, since=args.since) if args.chat else ledger.events_since(args.run_id, args.since)
    if args.json:
        print(dumps({"events": events}))
        return 0

    for event in events:
        if args.chat:
            print(dumps(event))
        else:
            print(f"{event['seq']:03d} {event['event_type']} {dumps(event['payload'])}")
    return 0


def _cmd_replay(args: argparse.Namespace) -> int:
    store = StateStore(args.state_dir)
    store.initialize()
    ledger = RunLedger(store)
    trace = ledger.load_trace(args.run_id)
    summary = {
        "run_id": args.run_id,
        "event_count": len(trace),
        "chat_event_count": sum(1 for event in trace if event.get("event_type") == "chat.event"),
        "tool_call_count": sum(1 for event in trace if event.get("event_type") == "tool.called"),
        "completed": any(
            event.get("event_type") == "run.completed"
            and event.get("payload", {}).get("status") == "completed"
            for event in trace
        ),
        "trace_path": str(ledger.trace_path(args.run_id)),
    }
    if args.json:
        print(dumps(summary))
    else:
        print(
            f"run={summary['run_id']} events={summary['event_count']} "
            f"chat_events={summary['chat_event_count']} tool_calls={summary['tool_call_count']} "
            f"completed={summary['completed']}"
        )
        print(summary["trace_path"])
    return 0


def _cmd_memory(args: argparse.Namespace) -> int:
    store = StateStore(args.state_dir)
    store.initialize()
    engine = MemoryEngine(store)

    if args.memory_command == "search":
        result = {"matches": engine.search(" ".join(args.query), limit=args.limit)}
    elif args.memory_command == "promote":
        result = engine.promote_candidate(args.candidate_id)
    elif args.memory_command == "reject":
        result = engine.reject_candidate(args.candidate_id, args.reason)
    else:
        raise MnemoError("memory command requires a subcommand")

    if args.json:
        print(dumps(result))
        return 0
    _print_memory_result(result)
    return 0


def _cmd_dream(args: argparse.Namespace) -> int:
    if args.dream_command != "run":
        raise MnemoError("dream command requires a subcommand")
    store = StateStore(args.state_dir)
    store.initialize()
    result = MemoryEngine(store).dream_consolidate(limit=args.limit, min_confidence=args.min_confidence)
    if args.json:
        print(dumps(result))
        return 0
    print(
        "DreamCycle completed: "
        f"promoted={len(result['promoted'])} rejected={len(result['rejected'])} skipped={len(result['skipped'])}"
    )
    return 0


def _print_memory_result(result: dict) -> None:
    if "matches" in result:
        for item in result["matches"]:
            if item["type"] == "page":
                print(f"page {item['id']}: {item['title']} ({item['confidence']:.2f})")
            else:
                print(f"candidate {item['id']}: {item['claim']} [{item['status']}]")
        return
    print(dumps(result))


def _cmd_prompt(args: argparse.Namespace) -> int:
    if args.prompt_command == "inspect":
        return _cmd_prompt_inspect(args)
    raise MnemoError("prompt command requires a subcommand")


def _cmd_prompt_inspect(args: argparse.Namespace) -> int:
    store = StateStore(args.state_dir)
    store.initialize()
    ledger = RunLedger(store)
    event = ledger.latest(args.run_id, "prompt.assembled")
    if not event:
        raise MnemoError(f"prompt assembly not found for run: {args.run_id}")
    payload = event["payload"]
    if args.json:
        print(dumps({"run_id": args.run_id, "prompt": payload}))
        return 0

    print(f"Prompt for run {args.run_id}")
    print(f"mode={payload.get('mode', 'unknown')} total_tokens={payload.get('total_token_estimate', 0)}")
    for block in payload.get("blocks", []):
        print(
            f"- {block['id']} role={block['role']} cache={block['cache_policy']} "
            f"tokens={block['token_estimate']}"
        )
    return 0


def _cmd_skills(args: argparse.Namespace) -> int:
    store = StateStore(args.state_dir)
    store.initialize()
    roots = [*default_skill_roots(args.state_dir), *args.root] if hasattr(args, "root") else default_skill_roots(args.state_dir)
    service = SkillService(store, roots=roots)

    if args.skills_command == "scan":
        result = {"skills": service.scan()}
    elif args.skills_command == "list":
        result = {"skills": service.list()}
    elif args.skills_command == "view":
        skill = service.view(args.name)
        if not skill:
            raise MnemoError(f"skill not found: {args.name}")
        result = {"skill": skill}
    elif args.skills_command == "promote":
        result = service.promote(args.name)
    else:
        raise MnemoError("skills command requires a subcommand")

    if args.json:
        print(dumps(result))
        return 0
    _print_skills_result(result)
    return 0


def _print_skills_result(result: dict) -> None:
    if "skills" in result:
        for skill in result["skills"]:
            print(f"{skill['name']} [{skill.get('status', 'scanned')}]: {skill.get('description', '')}")
        return
    if "skill" in result:
        skill = result["skill"]
        print(f"# {skill['name']}")
        print(skill.get("description", ""))
        print()
        print(skill.get("body", ""))
        return
    print(dumps(result))


def _cmd_tools(args: argparse.Namespace) -> int:
    tools = tool_specs_as_json_schema(ToolRegistry().specs())
    if args.json:
        print(dumps({"tools": tools}))
        return 0
    for tool in tools:
        print(f"{tool['name']} [{tool['risk']}]: {tool['description']}")
    return 0


def _cmd_web(args: argparse.Namespace) -> int:
    provider_name = _provider_name(args)
    base_url = args.base_url or os.environ.get("MNEMO_BASE_URL")
    model = args.model or os.environ.get("MNEMO_MODEL")
    api_key_env = args.api_key_env or os.environ.get("MNEMO_API_KEY_ENV")
    api_key = args.api_key or (os.environ.get(api_key_env) if api_key_env else os.environ.get("MNEMO_API_KEY"))
    timeout_s = args.timeout_s or _env_float("MNEMO_TIMEOUT_S") or 30.0

    if provider_name == "openai-compatible" and not base_url:
        raise MnemoError("openai-compatible provider requires --base-url or MNEMO_BASE_URL")
    if provider_name == "openai-compatible" and not model:
        raise MnemoError("openai-compatible provider requires --model or MNEMO_MODEL")

    serve_web(
        WebServerConfig(
            state_dir=args.state_dir,
            host=args.host,
            port=args.port,
            provider=provider_name,
            base_url=base_url,
            model=model,
            api_key=api_key,
            timeout_s=timeout_s,
        )
    )
    return 0


def _provider_name(args: argparse.Namespace) -> str:
    return args.provider or os.environ.get("MNEMO_PROVIDER") or DEFAULT_PROVIDER


def _openai_compatible_adapter(args: argparse.Namespace, *, stream: bool = False) -> OpenAIProviderAdapter:
    base_url = args.base_url or os.environ.get("MNEMO_BASE_URL")
    model = args.model or os.environ.get("MNEMO_MODEL")
    api_key_env = args.api_key_env or os.environ.get("MNEMO_API_KEY_ENV")
    api_key = args.api_key or (os.environ.get(api_key_env) if api_key_env else os.environ.get("MNEMO_API_KEY"))
    timeout_s = args.timeout_s or _env_float("MNEMO_TIMEOUT_S") or 30.0

    if not base_url:
        raise MnemoError("openai-compatible provider requires --base-url or MNEMO_BASE_URL")
    if not model:
        raise MnemoError("openai-compatible provider requires --model or MNEMO_MODEL")

    return OpenAIProviderAdapter(
        ProviderConfig(
            base_url=base_url,
            model=model,
            api_key=api_key,
            timeout_s=timeout_s,
            stream=stream,
        )
    )


def _env_float(name: str) -> float | None:
    value = os.environ.get(name)
    if not value:
        return None
    try:
        return float(value)
    except ValueError as exc:
        raise MnemoError(f"{name} must be a number") from exc
