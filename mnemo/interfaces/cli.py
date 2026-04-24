from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Sequence

from .. import __version__
from ..core.config import ConfigOverrides, DEFAULT_PROVIDER, DEFAULT_STATE_DIR, resolve_runtime_config
from ..core.errors import MnemoError
from ..core.events import chat_event_as_dict
from ..core.jsonutil import dumps
from ..core.models import RunRequest
from ..evals import EvalHarness, list_suites, replay_summary
from ..memory import MemoryEngine
from ..providers import AnthropicProviderAdapter, OpenAIProviderAdapter, ProviderAdapter, ProviderConfig
from ..runtime import DaemonRunner, result_as_dict, run_local, run_provider, stream_local
from ..runtime.ledger import RunLedger
from ..runtime.provider import stream_provider
from ..skills import SkillService, default_skill_roots
from ..storage import StateStore
from ..tools import ToolRegistry, tool_specs_as_json_schema
from .web import WebServerConfig, serve_web


_ANTHROPIC_DEFAULT_BASE_URL = "https://api.anthropic.com/v1"


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
        if args.command == "harness":
            return _cmd_harness(args)
        if args.command == "daemon":
            return _cmd_daemon(args)
        if args.command == "backup":
            return _cmd_backup(args)
        if args.command == "config":
            return _cmd_config(args)
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
        choices=["local", "openai-compatible", "anthropic"],
        default=None,
        help="Runtime provider (default: local, or MNEMO_PROVIDER)",
    )
    run_parser.add_argument("--base-url", help="OpenAI-compatible base URL, or MNEMO_BASE_URL")
    run_parser.add_argument("--model", help="Provider model name, or MNEMO_MODEL")
    run_parser.add_argument("--api-key", help="Provider API key. Prefer --api-key-env for shell history safety.")
    run_parser.add_argument("--api-key-env", help="Environment variable containing provider API key.")
    run_parser.add_argument("--timeout-s", type=float, help="Provider request timeout, or MNEMO_TIMEOUT_S")
    run_parser.add_argument("--config", help="Optional JSON config path, or MNEMO_CONFIG")

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

    skills_parser = subparsers.add_parser("skills", help="Scan, list, eval, review, view, and promote skills")
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
    skills_review_parser = skills_subparsers.add_parser("review", help="Review a draft skill candidate")
    _add_state_dir(skills_review_parser)
    skills_review_parser.add_argument("name")
    skills_review_parser.add_argument("--json", action="store_true")
    skills_crystallize_parser = skills_subparsers.add_parser("crystallize", help="Crystallize a run into a draft skill")
    _add_state_dir(skills_crystallize_parser)
    skills_crystallize_parser.add_argument("run_id")
    skills_crystallize_parser.add_argument("name")
    skills_crystallize_parser.add_argument("--description")
    skills_crystallize_parser.add_argument("--notes")
    skills_crystallize_parser.add_argument("--json", action="store_true")
    skills_eval_parser = skills_subparsers.add_parser("eval", help="Run a stored skill eval case")
    _add_state_dir(skills_eval_parser)
    skills_eval_parser.add_argument("case_id")
    skills_eval_parser.add_argument("--json", action="store_true")
    skills_promote_parser = skills_subparsers.add_parser("promote", help="Promote a draft skill to SKILL.md")
    _add_state_dir(skills_promote_parser)
    skills_promote_parser.add_argument("name")
    skills_promote_parser.add_argument("--json", action="store_true")

    tools_parser = subparsers.add_parser("tools", help="Print available tool specs")
    tools_parser.add_argument("--state-dir", help="Optional state directory for installed generated tools")
    tools_parser.add_argument("--json", action="store_true")

    web_parser = subparsers.add_parser("web", help="Run the Mnemo single-chat web UI")
    _add_state_dir(web_parser)
    web_parser.add_argument("--host", default="127.0.0.1")
    web_parser.add_argument("--port", type=int, default=8765)
    web_parser.add_argument(
        "--provider",
        choices=["local", "openai-compatible", "anthropic"],
        default=None,
        help="Runtime provider (default: local, or MNEMO_PROVIDER)",
    )
    web_parser.add_argument("--base-url", help="OpenAI-compatible base URL, or MNEMO_BASE_URL")
    web_parser.add_argument("--model", help="Provider model name, or MNEMO_MODEL")
    web_parser.add_argument("--api-key", help="Provider API key. Prefer --api-key-env for shell history safety.")
    web_parser.add_argument("--api-key-env", help="Environment variable containing provider API key.")
    web_parser.add_argument("--timeout-s", type=float, help="Provider request timeout, or MNEMO_TIMEOUT_S")
    web_parser.add_argument("--config", help="Optional JSON config path, or MNEMO_CONFIG")

    harness_parser = subparsers.add_parser("harness", help="Run lightweight replay and eval harnesses")
    harness_subparsers = harness_parser.add_subparsers(dest="harness_command")
    harness_eval_parser = harness_subparsers.add_parser("eval", help="Run a built-in eval suite")
    harness_eval_parser.add_argument("suite", nargs="?", default="personalization-core")
    harness_eval_parser.add_argument("--state-dir", default=None, help="Optional state root for temporary eval runs")
    harness_eval_parser.add_argument("--json", action="store_true")
    harness_smoke_parser = harness_subparsers.add_parser("smoke", help="Run the smoke eval suite")
    harness_smoke_parser.add_argument("--state-dir", default=None, help="Optional state root for temporary eval runs")
    harness_smoke_parser.add_argument("--json", action="store_true")
    harness_replay_parser = harness_subparsers.add_parser("replay", help="Summarize a run replay trace")
    _add_state_dir(harness_replay_parser)
    harness_replay_parser.add_argument("run_id")
    harness_replay_parser.add_argument("--json", action="store_true")
    harness_list_parser = harness_subparsers.add_parser("list", help="List built-in eval suites")
    harness_list_parser.add_argument("--json", action="store_true")

    daemon_parser = subparsers.add_parser("daemon", help="Manage the lightweight run queue")
    daemon_subparsers = daemon_parser.add_subparsers(dest="daemon_command")
    daemon_enqueue_parser = daemon_subparsers.add_parser("enqueue", help="Queue a run request")
    _add_state_dir(daemon_enqueue_parser)
    daemon_enqueue_parser.add_argument("message", nargs="+")
    daemon_enqueue_parser.add_argument("--conversation-id")
    daemon_enqueue_parser.add_argument("--mission-id")
    daemon_enqueue_parser.add_argument("--json", action="store_true")
    daemon_run_parser = daemon_subparsers.add_parser("run", help="Drain queued run requests")
    _add_state_dir(daemon_run_parser)
    daemon_run_parser.add_argument("--limit", type=int, default=1)
    daemon_run_parser.add_argument("--stale-after-s", type=float, default=900.0)
    daemon_run_parser.add_argument("--worker-id")
    daemon_run_parser.add_argument("--provider", choices=["local", "openai-compatible", "anthropic"], default=None)
    daemon_run_parser.add_argument("--base-url")
    daemon_run_parser.add_argument("--model")
    daemon_run_parser.add_argument("--api-key")
    daemon_run_parser.add_argument("--api-key-env")
    daemon_run_parser.add_argument("--timeout-s", type=float)
    daemon_run_parser.add_argument("--config", help="Optional JSON config path, or MNEMO_CONFIG")
    daemon_run_parser.add_argument("--json", action="store_true")
    daemon_status_parser = daemon_subparsers.add_parser("status", help="Print queue and lock status")
    _add_state_dir(daemon_status_parser)
    daemon_status_parser.add_argument("--json", action="store_true")
    daemon_recover_parser = daemon_subparsers.add_parser("recover", help="Requeue stale running jobs")
    _add_state_dir(daemon_recover_parser)
    daemon_recover_parser.add_argument("--stale-after-s", type=float, default=900.0)
    daemon_recover_parser.add_argument("--json", action="store_true")

    backup_parser = subparsers.add_parser("backup", help="Export or import Mnemo state")
    backup_subparsers = backup_parser.add_subparsers(dest="backup_command")
    backup_export_parser = backup_subparsers.add_parser("export", help="Export state to a zip archive")
    _add_state_dir(backup_export_parser)
    backup_export_parser.add_argument("archive_path")
    backup_export_parser.add_argument("--json", action="store_true")
    backup_import_parser = backup_subparsers.add_parser("import", help="Import state from a zip archive")
    _add_state_dir(backup_import_parser)
    backup_import_parser.add_argument("archive_path")
    backup_import_parser.add_argument("--replace", action="store_true", help="Replace existing managed state")
    backup_import_parser.add_argument("--json", action="store_true")

    config_parser = subparsers.add_parser("config", help="Inspect resolved runtime configuration")
    config_subparsers = config_parser.add_subparsers(dest="config_command")
    config_inspect_parser = config_subparsers.add_parser("inspect", help="Print resolved configuration")
    _add_state_dir(config_inspect_parser)
    config_inspect_parser.add_argument("--provider", choices=["local", "openai-compatible", "anthropic"], default=None)
    config_inspect_parser.add_argument("--base-url")
    config_inspect_parser.add_argument("--model")
    config_inspect_parser.add_argument("--api-key")
    config_inspect_parser.add_argument("--api-key-env")
    config_inspect_parser.add_argument("--timeout-s", type=float)
    config_inspect_parser.add_argument("--config", help="Optional JSON config path, or MNEMO_CONFIG")
    config_inspect_parser.add_argument("--json", action="store_true")
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
    config = _runtime_config_from_args(args)
    request = RunRequest(
        message=message,
        state_dir=config.state_dir,
        conversation_id=args.conversation_id,
        mission_id=args.mission_id,
    )
    if args.stream:
        event_stream = stream_local(request) if config.provider == "local" else stream_provider(request, _provider_adapter(args, stream=True))
        for event in event_stream:
            print(dumps(chat_event_as_dict(event)), flush=True)
        return 0

    result = run_local(request) if config.provider == "local" else run_provider(request, _provider_adapter(args))
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
        f"w0_created={len(result['w0']['created'])} promoted={len(result['promoted'])} "
        f"rejected={len(result['rejected'])} "
        f"skipped={len(result['skipped'])} snapshot_items={result['snapshot']['page_count']}"
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
    elif args.skills_command == "review":
        result = service.review(args.name)
    elif args.skills_command == "crystallize":
        result = service.crystallize_from_run(
            args.run_id,
            args.name,
            description=args.description,
            notes=args.notes,
        )
    elif args.skills_command == "eval":
        result = service.run_eval_case(args.case_id)
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
    if args.state_dir:
        store = StateStore(args.state_dir)
        store.initialize()
        registry = ToolRegistry.from_store(store)
    else:
        registry = ToolRegistry()
    tools = tool_specs_as_json_schema(registry.specs())
    if args.json:
        print(dumps({"tools": tools}))
        return 0
    for tool in tools:
        print(f"{tool['name']} [{tool['risk']}]: {tool['description']}")
    return 0


def _cmd_web(args: argparse.Namespace) -> int:
    config = _runtime_config_from_args(args)

    _validate_provider_config(config)

    serve_web(
        WebServerConfig(
            state_dir=config.state_dir,
            host=args.host,
            port=args.port,
            provider=config.provider,
            base_url=config.base_url,
            model=config.model,
            api_key=config.api_key,
            timeout_s=config.timeout_s,
        )
    )
    return 0


def _cmd_harness(args: argparse.Namespace) -> int:
    if args.harness_command == "eval":
        try:
            report = EvalHarness(state_dir=args.state_dir).run_suite(args.suite)
        except ValueError as exc:
            raise MnemoError(str(exc)) from exc
        return _print_harness_report(report.as_dict(), json_output=args.json)
    if args.harness_command == "smoke":
        report = EvalHarness(state_dir=args.state_dir).run_suite("smoke")
        return _print_harness_report(report.as_dict(), json_output=args.json)
    if args.harness_command == "replay":
        result = replay_summary(args.state_dir, args.run_id)
        if args.json:
            print(dumps(result))
            return 0 if result["completed"] else 1
        print(
            f"run={result['run_id']} completed={result['completed']} "
            f"events={result['event_count']} chat_events={result['chat_event_count']}"
        )
        print(result["trace_path"])
        return 0 if result["completed"] else 1
    if args.harness_command == "list":
        suites = list_suites()
        if args.json:
            print(dumps({"suites": suites}))
        else:
            for suite in suites:
                print(suite)
        return 0
    raise MnemoError("harness command requires a subcommand")


def _cmd_config(args: argparse.Namespace) -> int:
    if args.config_command != "inspect":
        raise MnemoError("config command requires a subcommand")
    config = _runtime_config_from_args(args)
    payload = config.redacted()
    if args.json:
        print(dumps(payload))
    else:
        for key in ("state_dir", "provider", "base_url", "model", "api_key_env", "api_key", "timeout_s", "config_path"):
            print(f"{key}={payload.get(key)}")
    return 0


def _cmd_daemon(args: argparse.Namespace) -> int:
    if args.daemon_command == "enqueue":
        runner = DaemonRunner(args.state_dir)
        try:
            queue_id = runner.enqueue(
                " ".join(args.message),
                conversation_id=args.conversation_id,
                mission_id=args.mission_id,
                metadata={"source": "cli"},
            )
        except ValueError as exc:
            raise MnemoError(str(exc)) from exc
        result = {"queue_id": queue_id, "status": "pending"}
    elif args.daemon_command == "run":
        config = _runtime_config_from_args(args)
        runner = DaemonRunner(config.state_dir)
        result = runner.drain(
            _queued_executor(args),
            limit=args.limit,
            stale_after_s=args.stale_after_s,
            worker_id=args.worker_id,
        )
    elif args.daemon_command == "status":
        result = DaemonRunner(args.state_dir).status()
    elif args.daemon_command == "recover":
        result = DaemonRunner(args.state_dir).recover(stale_after_s=args.stale_after_s)
    else:
        raise MnemoError("daemon command requires a subcommand")

    if args.json:
        print(dumps(result))
        return 0
    _print_daemon_result(args.daemon_command, result)
    return 0


def _queued_executor(args: argparse.Namespace):
    config = _runtime_config_from_args(args)
    if config.provider == "local":
        return run_local
    adapter = _provider_adapter(args)

    def execute(request: RunRequest):
        return run_provider(request, adapter)

    return execute


def _print_daemon_result(command: str, result: dict[str, Any]) -> None:
    if command == "enqueue":
        print(f"Queued run {result['queue_id']}")
        return
    if command == "run":
        print(
            f"Daemon processed={len(result['processed'])} recovered={len(result['recovered'])} "
            f"pending={result['stats']['counts']['pending']}"
        )
        return
    if command == "status":
        counts = result["queue"]["counts"]
        lock = "locked" if result["lock"].get("locked") else "unlocked"
        print(
            f"Queue pending={counts['pending']} running={counts['running']} "
            f"completed={counts['completed']} failed={counts['failed']} lock={lock}"
        )
        return
    if command == "recover":
        print(f"Recovered {len(result['recovered'])} queued run(s)")
        return
    print(dumps(result))


def _cmd_backup(args: argparse.Namespace) -> int:
    store = StateStore(args.state_dir)
    try:
        if args.backup_command == "export":
            result = store.export_state(args.archive_path)
            action = "exported"
        elif args.backup_command == "import":
            result = store.import_state(args.archive_path, replace=args.replace)
            action = "imported"
        else:
            raise MnemoError("backup command requires a subcommand")
    except ValueError as exc:
        raise MnemoError(str(exc)) from exc

    if args.json:
        print(dumps(result))
        return 0
    print(
        f"State {action}: {result['archive_path']} "
        f"(schema_version={result['schema_version']} files={result['file_count']})"
    )
    return 0


def _print_harness_report(report: dict, *, json_output: bool) -> int:
    if json_output:
        print(dumps(report))
    else:
        status = "passed" if report["passed"] else "failed"
        print(
            f"{report['suite']}: {status} "
            f"({report['passed_count']}/{report['case_count']} cases)"
        )
        for case in report["cases"]:
            marker = "ok" if case["passed"] else "fail"
            print(f"- {marker} {case['case_id']}: {case['name']}")
    return 0 if report["passed"] else 1


def _provider_name(args: argparse.Namespace) -> str:
    return _runtime_config_from_args(args).provider


def _provider_adapter(args: argparse.Namespace, *, stream: bool = False) -> ProviderAdapter:
    config = _runtime_config_from_args(args)
    _validate_provider_config(config)
    if config.provider == "anthropic":
        return AnthropicProviderAdapter(
            ProviderConfig(
                base_url=config.base_url or _ANTHROPIC_DEFAULT_BASE_URL,
                model=config.model or "",
                api_key=config.api_key,
                timeout_s=config.timeout_s,
                stream=stream,
            )
        )
    return _openai_compatible_adapter(args, stream=stream)


def _openai_compatible_adapter(args: argparse.Namespace, *, stream: bool = False) -> OpenAIProviderAdapter:
    config = _runtime_config_from_args(args)
    if not config.base_url:
        raise MnemoError("openai-compatible provider requires --base-url or MNEMO_BASE_URL")
    if not config.model:
        raise MnemoError("openai-compatible provider requires --model or MNEMO_MODEL")

    return OpenAIProviderAdapter(
        ProviderConfig(
            base_url=config.base_url,
            model=config.model,
            api_key=config.api_key,
            timeout_s=config.timeout_s,
            stream=stream,
        )
    )


def _validate_provider_config(config) -> None:
    if config.provider == "local":
        return
    if config.provider == "openai-compatible":
        if not config.base_url:
            raise MnemoError("openai-compatible provider requires --base-url or MNEMO_BASE_URL")
        if not config.model:
            raise MnemoError("openai-compatible provider requires --model or MNEMO_MODEL")
        return
    if config.provider == "anthropic":
        if not config.model:
            raise MnemoError("anthropic provider requires --model or MNEMO_MODEL")
        return
    raise MnemoError(f"unsupported provider: {config.provider}")


def _runtime_config_from_args(args: argparse.Namespace):
    state_dir = getattr(args, "state_dir", None)
    if state_dir == DEFAULT_STATE_DIR:
        state_dir = None
    return resolve_runtime_config(
        ConfigOverrides(
            state_dir=state_dir,
            provider=getattr(args, "provider", None),
            base_url=getattr(args, "base_url", None),
            model=getattr(args, "model", None),
            api_key=getattr(args, "api_key", None),
            api_key_env=getattr(args, "api_key_env", None),
            timeout_s=getattr(args, "timeout_s", None),
            config_path=getattr(args, "config", None),
        )
    )
