from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Sequence

from .. import __version__
from ..core.config import ConfigOverrides, DEFAULT_PROVIDER, DEFAULT_STATE_DIR, resolve_runtime_config
from ..core.errors import MnemoError
from ..core.events import chat_event_as_dict
from ..core.jsonutil import dumps, loads
from ..core.models import PROMPT_MODES, RunRequest
from ..evals import EvalHarness, list_suites, list_variants, replay_summary
from ..memory import MemoryEngine
from ..mcp import MnemoMcpServer
from ..providers import (
    AnthropicProviderAdapter,
    OpenAIProviderAdapter,
    ProviderAdapter,
    ProviderConfig,
    ProviderRunInput,
    provider_capabilities,
)
from ..runtime import DaemonRunner, ScheduleService, result_as_dict, run_local, run_provider, stream_local
from ..runtime.approvals import resolve_inbox_item_with_actions
from ..runtime.ledger import RunLedger
from ..runtime.provider import stream_provider
from ..sdk import mnemo_core_api_schema
from ..skills import SkillService, default_skill_roots
from ..storage import StateStore
from ..tools import ToolEvolutionService, ToolRegistry, tool_specs_as_json_schema
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
        if args.command == "conversations":
            return _cmd_conversations(args)
        if args.command == "missions":
            return _cmd_missions(args)
        if args.command == "runs":
            return _cmd_runs(args)
        if args.command == "events":
            return _cmd_events(args)
        if args.command == "artifacts":
            return _cmd_artifacts(args)
        if args.command == "inbox":
            return _cmd_inbox(args)
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
        if args.command == "evals":
            return _cmd_evals(args)
        if args.command == "daemon":
            return _cmd_daemon(args)
        if args.command == "schedule":
            return _cmd_schedule(args)
        if args.command == "backup":
            return _cmd_backup(args)
        if args.command == "config":
            return _cmd_config(args)
        if args.command == "api":
            return _cmd_api(args)
        if args.command == "mcp":
            return _cmd_mcp(args)
        parser.print_help()
        return 0
    except MnemoError as exc:
        print(f"mnemo: {exc}", file=sys.stderr)
        return 1
    except BrokenPipeError:
        sys.stdout = open(os.devnull, "w")
        return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mnemo", description="Mnemo personal AI runtime")
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
    run_parser.add_argument("--retry-count", type=int, help="Provider non-streaming retry count, or MNEMO_RETRY_COUNT")
    run_parser.add_argument("--retry-backoff-s", type=float, help="Provider retry backoff seconds, or MNEMO_RETRY_BACKOFF_S")
    run_parser.add_argument(
        "--prompt-mode",
        choices=list(PROMPT_MODES),
        default="full",
        help="Prompt disclosure mode for this run",
    )
    run_parser.add_argument("--config", help="Optional JSON config path, or MNEMO_CONFIG")

    conversations_parser = subparsers.add_parser("conversations", help="List and read conversations")
    conversations_subparsers = conversations_parser.add_subparsers(dest="conversations_command")
    conversations_list_parser = conversations_subparsers.add_parser("list", help="List stored conversations")
    _add_state_dir(conversations_list_parser)
    conversations_list_parser.add_argument("--limit", type=int, default=50)
    conversations_list_parser.add_argument("--json", action="store_true")
    conversations_show_parser = conversations_subparsers.add_parser("show", help="Show one conversation")
    _add_state_dir(conversations_show_parser)
    conversations_show_parser.add_argument("conversation_id")
    conversations_show_parser.add_argument("--json", action="store_true")

    missions_parser = subparsers.add_parser("missions", help="List and read missions")
    missions_subparsers = missions_parser.add_subparsers(dest="missions_command")
    missions_list_parser = missions_subparsers.add_parser("list", help="List stored missions")
    _add_state_dir(missions_list_parser)
    missions_list_parser.add_argument("--conversation-id")
    missions_list_parser.add_argument("--status", help="Status filter, or 'all' for no status filter")
    missions_list_parser.add_argument("--limit", type=int, default=50)
    missions_list_parser.add_argument("--json", action="store_true")
    missions_show_parser = missions_subparsers.add_parser("show", help="Show one mission")
    _add_state_dir(missions_show_parser)
    missions_show_parser.add_argument("mission_id")
    missions_show_parser.add_argument("--json", action="store_true")

    runs_parser = subparsers.add_parser("runs", help="Inspect and control runs")
    runs_subparsers = runs_parser.add_subparsers(dest="runs_command")
    runs_list_parser = runs_subparsers.add_parser("list", help="List recent runs")
    _add_state_dir(runs_list_parser)
    runs_list_parser.add_argument("--status", help="Status filter, or 'all' for no status filter")
    runs_list_parser.add_argument("--conversation-id")
    runs_list_parser.add_argument("--mission-id")
    runs_list_parser.add_argument("--limit", type=int, default=50)
    runs_list_parser.add_argument("--json", action="store_true")
    runs_show_parser = runs_subparsers.add_parser("show", help="Show one run record")
    _add_state_dir(runs_show_parser)
    runs_show_parser.add_argument("run_id")
    runs_show_parser.add_argument("--json", action="store_true")
    runs_cancel_parser = runs_subparsers.add_parser("cancel", help="Request cancellation for a running run")
    _add_state_dir(runs_cancel_parser)
    runs_cancel_parser.add_argument("run_id")
    runs_cancel_parser.add_argument("--reason", default="cancelled")
    runs_cancel_parser.add_argument("--json", action="store_true")

    events_parser = subparsers.add_parser("events", help="Print RunLedger events for a run")
    _add_state_dir(events_parser)
    events_parser.add_argument("run_id")
    events_parser.add_argument("--since", type=int, default=0)
    events_parser.add_argument("--chat", action="store_true", help="Print ChatEvent payloads only")
    events_parser.add_argument("--json", action="store_true")

    artifacts_parser = subparsers.add_parser("artifacts", help="List and read stored artifacts")
    artifacts_subparsers = artifacts_parser.add_subparsers(dest="artifacts_command")
    artifacts_list_parser = artifacts_subparsers.add_parser("list", help="List stored artifact metadata")
    _add_state_dir(artifacts_list_parser)
    artifacts_list_parser.add_argument("--mission-id")
    artifacts_list_parser.add_argument("--run-id")
    artifacts_list_parser.add_argument("--limit", type=int, default=50)
    artifacts_list_parser.add_argument("--json", action="store_true")
    artifacts_read_parser = artifacts_subparsers.add_parser("read", help="Read a stored artifact body")
    _add_state_dir(artifacts_read_parser)
    artifacts_read_parser.add_argument("artifact_id")
    artifacts_read_parser.add_argument("--json", action="store_true")

    inbox_parser = subparsers.add_parser("inbox", help="List and resolve Inbox decision items")
    _add_state_dir(inbox_parser)
    inbox_parser.add_argument("--status", choices=["open", "resolved", "all"], default="open")
    inbox_parser.add_argument("--category")
    inbox_parser.add_argument("--priority", choices=["critical", "high", "normal", "low"])
    inbox_parser.add_argument("--limit", type=int, default=50)
    inbox_parser.add_argument("--json", action="store_true")
    inbox_subparsers = inbox_parser.add_subparsers(dest="inbox_command")
    inbox_list_parser = inbox_subparsers.add_parser("list", help="List Inbox items")
    _add_state_dir(inbox_list_parser)
    inbox_list_parser.add_argument("--status", choices=["open", "resolved", "all"], default="open")
    inbox_list_parser.add_argument("--category")
    inbox_list_parser.add_argument("--priority", choices=["critical", "high", "normal", "low"])
    inbox_list_parser.add_argument("--limit", type=int, default=50)
    inbox_list_parser.add_argument("--json", action="store_true")
    inbox_show_parser = inbox_subparsers.add_parser("show", help="Show one Inbox item")
    _add_state_dir(inbox_show_parser)
    inbox_show_parser.add_argument("item_id")
    inbox_show_parser.add_argument("--json", action="store_true")
    inbox_resolve_parser = inbox_subparsers.add_parser("resolve", help="Resolve an Inbox item")
    _add_state_dir(inbox_resolve_parser)
    inbox_resolve_parser.add_argument("item_id")
    inbox_resolution = inbox_resolve_parser.add_mutually_exclusive_group(required=True)
    inbox_resolution.add_argument("--accept", action="store_true")
    inbox_resolution.add_argument("--reject", action="store_true")
    inbox_resolution.add_argument("--ignore", action="store_true")
    inbox_resolve_parser.add_argument("--notes")
    inbox_resolve_parser.add_argument("--json", action="store_true")

    replay_parser = subparsers.add_parser("replay", help="Summarize a run trace")
    _add_state_dir(replay_parser)
    replay_parser.add_argument("run_id")
    replay_parser.add_argument("--json", action="store_true")

    memory_parser = subparsers.add_parser("memory", help="Search and curate memory")
    memory_subparsers = memory_parser.add_subparsers(dest="memory_command")
    memory_notes_parser = memory_subparsers.add_parser("notes", help="List W0 working notes")
    _add_state_dir(memory_notes_parser)
    memory_notes_parser.add_argument("--status", help="Status filter, or 'all' for no status filter")
    memory_notes_parser.add_argument("--limit", type=int, default=50)
    memory_notes_parser.add_argument("--json", action="store_true")
    memory_list_parser = memory_subparsers.add_parser("list", help="List memory candidates or pages")
    _add_state_dir(memory_list_parser)
    memory_list_parser.add_argument("--kind", choices=["candidate", "page", "all"], default="candidate")
    memory_list_parser.add_argument("--status", help="Status filter, or 'all' for no status filter")
    memory_list_parser.add_argument("--limit", type=int, default=50)
    memory_list_parser.add_argument("--json", action="store_true")
    memory_search_parser = memory_subparsers.add_parser("search", help="Search memory pages, candidates, or session snippets")
    _add_state_dir(memory_search_parser)
    memory_search_parser.add_argument("query", nargs="+")
    memory_search_parser.add_argument("--limit", type=int, default=5)
    memory_search_parser.add_argument("--scope", choices=["memory", "stable", "sessions", "all"], default="memory")
    memory_search_parser.add_argument("--debug-query", action="store_true", help="Include compact query plan metadata")
    memory_search_parser.add_argument("--json", action="store_true")
    memory_read_parser = memory_subparsers.add_parser("read", help="Read a memory candidate or page by id")
    _add_state_dir(memory_read_parser)
    memory_read_parser.add_argument("memory_id")
    memory_read_parser.add_argument("--json", action="store_true")
    memory_links_parser = memory_subparsers.add_parser("links", help="List memory graph links for an id")
    _add_state_dir(memory_links_parser)
    memory_links_parser.add_argument("memory_id")
    memory_links_parser.add_argument("--direction", choices=["outgoing", "incoming", "both"], default="both")
    memory_links_parser.add_argument("--json", action="store_true")
    memory_snapshot_parser = memory_subparsers.add_parser("snapshot", help="Inspect the compiled L1 memory snapshot")
    _add_state_dir(memory_snapshot_parser)
    memory_snapshot_parser.add_argument("--json", action="store_true")
    memory_health_parser = memory_subparsers.add_parser("health", help="Inspect compact memory health and review cards")
    _add_state_dir(memory_health_parser)
    memory_health_parser.add_argument("--limit", type=int, default=20)
    memory_health_parser.add_argument("--json", action="store_true")
    memory_tombstones_parser = memory_subparsers.add_parser("tombstones", help="List durable memory tombstones")
    _add_state_dir(memory_tombstones_parser)
    memory_tombstones_parser.add_argument("--target-id")
    memory_tombstones_parser.add_argument("--target-type", choices=["candidate", "page"])
    memory_tombstones_parser.add_argument("--limit", type=int, default=50)
    memory_tombstones_parser.add_argument("--json", action="store_true")
    memory_tombstone_parser = memory_subparsers.add_parser("tombstone", help="Tombstone a memory candidate or page")
    _add_state_dir(memory_tombstone_parser)
    memory_tombstone_parser.add_argument("memory_id")
    memory_tombstone_parser.add_argument("--reason", required=True)
    memory_tombstone_parser.add_argument("--target-type", choices=["auto", "candidate", "page"], default="auto")
    memory_tombstone_parser.add_argument("--json", action="store_true")
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
    _add_state_dir(dream_parser)
    dream_parser.add_argument("--now", action="store_true", help="Run Dream maintenance now")
    dream_parser.add_argument("--limit", type=int, default=20)
    dream_parser.add_argument("--min-confidence", type=float, default=0.7)
    dream_parser.add_argument("--json", action="store_true")
    dream_subparsers = dream_parser.add_subparsers(dest="dream_command")
    dream_run_parser = dream_subparsers.add_parser("run", help="Run Dream maintenance")
    _add_state_dir(dream_run_parser)
    dream_run_parser.add_argument("--limit", type=int, default=20)
    dream_run_parser.add_argument("--min-confidence", type=float, default=0.7)
    dream_run_parser.add_argument("--json", action="store_true")
    dream_status_parser = dream_subparsers.add_parser("status", help="Inspect Dream maintenance backlog")
    _add_state_dir(dream_status_parser)
    dream_status_parser.add_argument("--limit", type=int, default=20)
    dream_status_parser.add_argument("--json", action="store_true")
    dream_report_parser = dream_subparsers.add_parser("report", help="Read a persisted Dream report")
    _add_state_dir(dream_report_parser)
    dream_report_parser.add_argument("report_id", nargs="?")
    dream_report_parser.add_argument("--latest", action="store_true")
    dream_report_parser.add_argument("--json", action="store_true")

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
    skills_usage_parser = skills_subparsers.add_parser("usage", help="Inspect stored skill usage and outcome signals")
    _add_state_dir(skills_usage_parser)
    skills_usage_parser.add_argument("name", nargs="?")
    skills_usage_parser.add_argument("--limit", type=int, default=50)
    skills_usage_parser.add_argument("--json", action="store_true")
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

    tools_parser = subparsers.add_parser("tools", help="List tools and manage generated tool candidates")
    tools_parser.add_argument("--state-dir", help="Optional state directory for installed generated tools")
    tools_parser.add_argument("--json", action="store_true")
    tools_subparsers = tools_parser.add_subparsers(dest="tools_command")
    tools_list_parser = tools_subparsers.add_parser("list", help="Print available tool specs")
    tools_list_parser.add_argument("--state-dir", help="Optional state directory for installed generated tools")
    tools_list_parser.add_argument("--json", action="store_true")
    tools_candidates_parser = tools_subparsers.add_parser("candidates", help="List generated tool candidates")
    _add_state_dir(tools_candidates_parser)
    tools_candidates_parser.add_argument("--status")
    tools_candidates_parser.add_argument("--limit", type=int, default=50)
    tools_candidates_parser.add_argument("--json", action="store_true")
    tools_review_parser = tools_subparsers.add_parser("review", help="Review a generated tool candidate")
    _add_state_dir(tools_review_parser)
    tools_review_parser.add_argument("candidate_id")
    tools_review_parser.add_argument("--json", action="store_true")
    tools_install_parser = tools_subparsers.add_parser("install", help="Install a ready generated tool candidate")
    _add_state_dir(tools_install_parser)
    tools_install_parser.add_argument("candidate_id")
    tools_install_parser.add_argument("--json", action="store_true")
    tools_uninstall_parser = tools_subparsers.add_parser("uninstall", help="Disable an installed generated tool")
    _add_state_dir(tools_uninstall_parser)
    tools_uninstall_parser.add_argument("name")
    tools_uninstall_parser.add_argument("--json", action="store_true")

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
    web_parser.add_argument("--retry-count", type=int, help="Provider non-streaming retry count, or MNEMO_RETRY_COUNT")
    web_parser.add_argument("--retry-backoff-s", type=float, help="Provider retry backoff seconds, or MNEMO_RETRY_BACKOFF_S")
    web_parser.add_argument("--config", help="Optional JSON config path, or MNEMO_CONFIG")

    harness_parser = subparsers.add_parser("harness", help="Run lightweight replay and eval harnesses")
    harness_subparsers = harness_parser.add_subparsers(dest="harness_command")
    harness_eval_parser = harness_subparsers.add_parser("eval", help="Run a built-in eval suite")
    harness_eval_parser.add_argument("suite", nargs="?", default="personalization-core")
    harness_eval_parser.add_argument("--state-dir", default=None, help="Optional state root for temporary eval runs")
    harness_eval_parser.add_argument("--json", action="store_true")
    harness_variants_parser = harness_subparsers.add_parser("variants", help="Compare harness variants for a suite")
    harness_variants_parser.add_argument("suite", nargs="?", default="personalization-core")
    harness_variants_parser.add_argument("--state-dir", default=None, help="Optional state root for temporary eval runs")
    harness_variants_parser.add_argument(
        "--variant",
        action="append",
        default=[],
        help="Variant to include; may be repeated or comma-separated",
    )
    harness_variants_parser.add_argument("--json", action="store_true")
    harness_smoke_parser = harness_subparsers.add_parser("smoke", help="Run the smoke eval suite")
    harness_smoke_parser.add_argument("--state-dir", default=None, help="Optional state root for temporary eval runs")
    harness_smoke_parser.add_argument("--json", action="store_true")
    harness_replay_parser = harness_subparsers.add_parser("replay", help="Summarize a run replay trace")
    _add_state_dir(harness_replay_parser)
    harness_replay_parser.add_argument("run_id")
    harness_replay_parser.add_argument("--json", action="store_true")
    harness_list_parser = harness_subparsers.add_parser("list", help="List built-in eval suites")
    harness_list_parser.add_argument("--json", action="store_true")

    evals_parser = subparsers.add_parser("evals", help="Create, list, and record stored eval cases")
    evals_subparsers = evals_parser.add_subparsers(dest="evals_command")
    evals_create_parser = evals_subparsers.add_parser("create", help="Create a stored eval case")
    _add_state_dir(evals_create_parser)
    evals_create_parser.add_argument("run_id")
    evals_create_parser.add_argument("name")
    evals_create_parser.add_argument("--case-json", required=True, help="JSON object eval case payload")
    evals_create_parser.add_argument("--json", action="store_true")
    evals_list_parser = evals_subparsers.add_parser("list", help="List stored eval cases")
    _add_state_dir(evals_list_parser)
    evals_list_parser.add_argument("--status")
    evals_list_parser.add_argument("--tool-name")
    evals_list_parser.add_argument("--skill-name")
    evals_list_parser.add_argument("--limit", type=int, default=50)
    evals_list_parser.add_argument("--json", action="store_true")
    evals_record_parser = evals_subparsers.add_parser("record", help="Record an eval case result")
    _add_state_dir(evals_record_parser)
    evals_record_parser.add_argument("case_id")
    evals_record_parser.add_argument("status", choices=["passed", "failed"])
    evals_record_parser.add_argument("--result-json", default="{}", help="JSON object result payload")
    evals_record_parser.add_argument("--json", action="store_true")

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
    daemon_run_parser.add_argument("--retry-count", type=int)
    daemon_run_parser.add_argument("--retry-backoff-s", type=float)
    daemon_run_parser.add_argument("--config", help="Optional JSON config path, or MNEMO_CONFIG")
    daemon_run_parser.add_argument("--json", action="store_true")
    daemon_status_parser = daemon_subparsers.add_parser("status", help="Print queue and lock status")
    _add_state_dir(daemon_status_parser)
    daemon_status_parser.add_argument("--json", action="store_true")
    daemon_recover_parser = daemon_subparsers.add_parser("recover", help="Requeue stale running jobs")
    _add_state_dir(daemon_recover_parser)
    daemon_recover_parser.add_argument("--stale-after-s", type=float, default=900.0)
    daemon_recover_parser.add_argument("--json", action="store_true")
    daemon_cancel_parser = daemon_subparsers.add_parser("cancel", help="Cancel a queued run request")
    _add_state_dir(daemon_cancel_parser)
    daemon_cancel_parser.add_argument("queue_id")
    daemon_cancel_parser.add_argument("--reason", default="cancelled")
    daemon_cancel_parser.add_argument("--json", action="store_true")

    schedule_parser = subparsers.add_parser("schedule", help="Manage lightweight watch/cron schedules")
    schedule_subparsers = schedule_parser.add_subparsers(dest="schedule_command")
    schedule_add_parser = schedule_subparsers.add_parser("add", help="Add a watch or cron scheduled item")
    _add_state_dir(schedule_add_parser)
    schedule_add_parser.add_argument("--kind", choices=["watch", "cron"], required=True)
    schedule_add_parser.add_argument("--title")
    schedule_add_parser.add_argument("--instruction", help="Watch instruction or cron message")
    schedule_add_parser.add_argument("--target", help="Watch target title")
    schedule_add_parser.add_argument("--message", help="Cron message")
    schedule_add_parser.add_argument("--schedule", default="once")
    schedule_add_parser.add_argument("--next-run-at", help="Optional due time: now, unix timestamp, or ISO timestamp")
    schedule_add_parser.add_argument("--json", action="store_true")
    schedule_list_parser = schedule_subparsers.add_parser("list", help="List scheduled items")
    _add_state_dir(schedule_list_parser)
    schedule_list_parser.add_argument("--kind", choices=["watch", "cron", "all"], default="all")
    schedule_list_parser.add_argument("--status", choices=["active", "paused", "completed", "disabled", "all"], default="active")
    schedule_list_parser.add_argument("--limit", type=int, default=50)
    schedule_list_parser.add_argument("--json", action="store_true")
    schedule_tick_parser = schedule_subparsers.add_parser("tick", help="Enqueue due scheduled items")
    _add_state_dir(schedule_tick_parser)
    schedule_tick_parser.add_argument("--now", help="Override current time for deterministic checks")
    schedule_tick_parser.add_argument("--limit", type=int, default=50)
    schedule_tick_parser.add_argument("--json", action="store_true")
    for command, help_text in {
        "pause": "Pause a scheduled item",
        "resume": "Resume a scheduled item",
        "disable": "Disable a scheduled item",
    }.items():
        schedule_status_parser = schedule_subparsers.add_parser(command, help=help_text)
        _add_state_dir(schedule_status_parser)
        schedule_status_parser.add_argument("item_id")
        schedule_status_parser.add_argument("--json", action="store_true")

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
    config_inspect_parser.add_argument("--retry-count", type=int)
    config_inspect_parser.add_argument("--retry-backoff-s", type=float)
    config_inspect_parser.add_argument("--config", help="Optional JSON config path, or MNEMO_CONFIG")
    config_inspect_parser.add_argument("--json", action="store_true")
    config_capabilities_parser = config_subparsers.add_parser(
        "capabilities",
        help="Print resolved provider capability metadata",
    )
    _add_state_dir(config_capabilities_parser)
    config_capabilities_parser.add_argument(
        "--provider",
        choices=["local", "openai-compatible", "anthropic"],
        default=None,
    )
    config_capabilities_parser.add_argument("--base-url")
    config_capabilities_parser.add_argument("--model")
    config_capabilities_parser.add_argument("--api-key")
    config_capabilities_parser.add_argument("--api-key-env")
    config_capabilities_parser.add_argument("--timeout-s", type=float)
    config_capabilities_parser.add_argument("--retry-count", type=int)
    config_capabilities_parser.add_argument("--retry-backoff-s", type=float)
    config_capabilities_parser.add_argument("--config", help="Optional JSON config path, or MNEMO_CONFIG")
    config_capabilities_parser.add_argument("--json", action="store_true")
    config_smoke_parser = config_subparsers.add_parser("smoke", help="Smoke test the configured provider endpoint")
    _add_state_dir(config_smoke_parser)
    config_smoke_parser.add_argument("--provider", choices=["openai-compatible", "anthropic"], default=None)
    config_smoke_parser.add_argument("--base-url")
    config_smoke_parser.add_argument("--model")
    config_smoke_parser.add_argument("--api-key")
    config_smoke_parser.add_argument("--api-key-env")
    config_smoke_parser.add_argument("--timeout-s", type=float)
    config_smoke_parser.add_argument("--retry-count", type=int)
    config_smoke_parser.add_argument("--retry-backoff-s", type=float)
    config_smoke_parser.add_argument("--config", help="Optional JSON config path, or MNEMO_CONFIG")
    config_smoke_parser.add_argument("--message", default="Hello, introduce yourself in one sentence.")
    config_smoke_parser.add_argument("--stream", action="store_true", help="Probe chat through provider streaming")
    config_smoke_parser.add_argument("--json", action="store_true")

    api_parser = subparsers.add_parser("api", help="Inspect MnemoCore integration contracts")
    api_subparsers = api_parser.add_subparsers(dest="api_command")
    api_schema_parser = api_subparsers.add_parser("schema", help="Print the MnemoCore API schema")
    api_schema_parser.add_argument("--json", action="store_true")

    mcp_parser = subparsers.add_parser("mcp", help="Expose Mnemo MCP-style tools")
    mcp_subparsers = mcp_parser.add_subparsers(dest="mcp_command")
    mcp_tools_parser = mcp_subparsers.add_parser("tools", help="List MCP-style Mnemo tools")
    _add_state_dir(mcp_tools_parser)
    mcp_tools_parser.add_argument("--json", action="store_true")
    mcp_call_parser = mcp_subparsers.add_parser("call", help="Call one MCP-style Mnemo tool")
    _add_state_dir(mcp_call_parser)
    mcp_call_parser.add_argument("tool_name")
    mcp_call_parser.add_argument("--arguments-json", default="{}", help="Tool arguments as a JSON object")
    mcp_call_parser.add_argument("--json", action="store_true")
    mcp_serve_parser = mcp_subparsers.add_parser("serve", help="Serve MCP-style JSON-RPC over stdio")
    _add_state_dir(mcp_serve_parser)
    mcp_serve_parser.add_argument(
        "--transport",
        choices=["content-length", "jsonl"],
        default="content-length",
        help="stdio transport framing (default: content-length)",
    )
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


def _cmd_api(args: argparse.Namespace) -> int:
    if args.api_command != "schema":
        raise MnemoError("api command requires a subcommand")
    schema = mnemo_core_api_schema()
    if args.json:
        print(dumps({"api_schema": schema}))
        return 0

    print(f"{schema['title']} {schema['schema_version']}")
    print(schema["description"])
    for name, method in schema["methods"].items():
        print(f"- {name}: {method['description']} ({method['side_effects']})")
    return 0


def _cmd_mcp(args: argparse.Namespace) -> int:
    if args.mcp_command not in {"tools", "call", "serve"}:
        raise MnemoError("mcp command requires a subcommand")
    server = MnemoMcpServer(state_dir=args.state_dir, workspace_root=Path.cwd())

    if args.mcp_command == "tools":
        tools = server.tools()
        if args.json:
            print(dumps({"tools": tools}))
            return 0
        for tool in tools:
            risk = tool.get("mnemo", {}).get("risk", "read")
            print(f"{tool['name']} [{risk}]: {tool['description']}")
        return 0

    if args.mcp_command == "call":
        try:
            arguments = loads(args.arguments_json, {})
        except ValueError as exc:
            raise MnemoError(f"invalid --arguments-json: {exc}") from exc
        if not isinstance(arguments, dict):
            raise MnemoError("--arguments-json must decode to an object")
        try:
            result = server.call_tool(args.tool_name, arguments)
        except ValueError as exc:
            raise MnemoError(str(exc)) from exc
        if args.json:
            print(dumps({"tool": args.tool_name, "result": result}))
            return 0
        print(dumps(result))
        return 0

    if args.transport == "jsonl":
        server.serve_jsonl()
        return 0
    server.serve_content_length()
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
        workspace_root=os.getcwd(),
        prompt_mode=args.prompt_mode,
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


def _cmd_conversations(args: argparse.Namespace) -> int:
    if args.conversations_command not in {"list", "show"}:
        raise MnemoError("conversations command requires a subcommand")
    store = StateStore(args.state_dir)
    store.initialize()
    if args.conversations_command == "list":
        result = {"conversations": store.list_conversations(limit=max(0, args.limit))}
    else:
        conversation = store.get_conversation(args.conversation_id)
        if not conversation:
            raise MnemoError(f"conversation not found: {args.conversation_id}")
        result = {"conversation": conversation}

    if args.json:
        print(dumps(result))
        return 0
    _print_conversations_result(result)
    return 0


def _print_conversations_result(result: dict[str, Any]) -> None:
    if "conversations" in result:
        for conversation in result["conversations"]:
            title = conversation.get("title") or "Untitled Conversation"
            print(f"conversation {conversation['id']}: {_short_text(title)}")
        return
    if "conversation" in result:
        conversation = result["conversation"]
        print(f"conversation {conversation['id']}")
        print(f"title={conversation.get('title') or ''}")
        print(f"created_at={conversation['created_at']} updated_at={conversation['updated_at']}")
        return
    print(dumps(result))


def _cmd_missions(args: argparse.Namespace) -> int:
    if args.missions_command not in {"list", "show"}:
        raise MnemoError("missions command requires a subcommand")
    store = StateStore(args.state_dir)
    store.initialize()
    if args.missions_command == "list":
        result = {
            "missions": store.list_missions(
                conversation_id=args.conversation_id,
                status=_status_filter(args.status),
                limit=max(0, args.limit),
            )
        }
    else:
        mission = store.get_mission(args.mission_id)
        if not mission:
            raise MnemoError(f"mission not found: {args.mission_id}")
        result = {"mission": mission}

    if args.json:
        print(dumps(result))
        return 0
    _print_missions_result(result)
    return 0


def _print_missions_result(result: dict[str, Any]) -> None:
    if "missions" in result:
        for mission in result["missions"]:
            print(
                f"mission {mission['id']} [{mission['status']}] "
                f"conversation={mission['conversation_id']}: {_short_text(mission.get('brief', ''))}"
            )
        return
    if "mission" in result:
        mission = result["mission"]
        print(f"mission {mission['id']} [{mission['status']}]")
        print(f"conversation={mission['conversation_id']}")
        print(f"created_at={mission['created_at']} updated_at={mission['updated_at']}")
        print()
        print(mission.get("brief", ""))
        checkpoint = mission.get("checkpoint") or {}
        if checkpoint:
            print()
            print(dumps({"checkpoint": checkpoint}))
        return
    print(dumps(result))


def _cmd_runs(args: argparse.Namespace) -> int:
    if args.runs_command not in {"list", "show", "cancel"}:
        raise MnemoError("runs command requires a subcommand")
    store = StateStore(args.state_dir)
    store.initialize()
    if args.runs_command == "list":
        result = {
            "runs": store.list_runs(
                status=_status_filter(args.status),
                conversation_id=args.conversation_id,
                mission_id=args.mission_id,
                limit=max(0, args.limit),
            )
        }
        if args.json:
            print(dumps(result))
        else:
            _print_runs_result(result)
        return 0
    if args.runs_command == "show":
        run = _require_run(store, args.run_id)
        result = {"run": run}
        if args.json:
            print(dumps(result))
        else:
            _print_runs_result(result)
        return 0
    try:
        result = store.cancel_run(args.run_id, reason=args.reason)
    except ValueError as exc:
        raise MnemoError(str(exc)) from exc
    store.append_event(
        args.run_id,
        "run.cancel.requested",
        {"reason": args.reason, "changed": result["changed"], "status": result["status"]},
    )
    payload = {"run_id": args.run_id, "status": result["status"], "changed": result["changed"]}
    if args.json:
        print(dumps(payload))
    else:
        changed = "cancelled" if result["changed"] else "unchanged"
        print(f"Run {args.run_id} {changed} status={result['status']}")
    return 0


def _status_filter(status: str | None) -> str | None:
    if status == "all":
        return None
    return status


def _require_run(store: StateStore, run_id: str) -> dict[str, Any]:
    run = store.get_run(run_id)
    if not run:
        raise MnemoError(f"run not found: {run_id}")
    return run


def _print_runs_result(result: dict[str, Any]) -> None:
    if "runs" in result:
        for run in result["runs"]:
            print(
                f"run {run['id']} [{run['status']}] "
                f"conversation={run['conversation_id']} mission={run['mission_id']}: "
                f"{_short_text(run.get('input_preview', ''))}"
            )
        return
    if "run" in result:
        run = result["run"]
        print(f"run {run['id']} [{run['status']}]")
        print(f"conversation={run['conversation_id']}")
        print(f"mission={run['mission_id']}")
        print(f"created_at={run['created_at']} completed_at={run.get('completed_at')}")
        print()
        print(run.get("input_text", ""))
        output = run.get("output_text")
        if output:
            print()
            print(output)
        return
    print(dumps(result))


def _cmd_events(args: argparse.Namespace) -> int:
    store = StateStore(args.state_dir)
    store.initialize()
    _require_run(store, args.run_id)
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


def _cmd_artifacts(args: argparse.Namespace) -> int:
    if args.artifacts_command not in {"list", "read"}:
        raise MnemoError("artifacts command requires a subcommand")
    store = StateStore(args.state_dir)
    store.initialize()
    if args.artifacts_command == "list":
        result = {
            "artifacts": store.list_artifacts(
                mission_id=args.mission_id,
                run_id=args.run_id,
                limit=max(0, args.limit),
            )
        }
    elif args.artifacts_command == "read":
        artifact = store.get_artifact(args.artifact_id)
        if not artifact:
            raise MnemoError(f"artifact not found: {args.artifact_id}")
        result = {"artifact": artifact}

    if args.json:
        print(dumps(result))
        return 0
    _print_artifacts_result(result)
    return 0


def _print_artifacts_result(result: dict[str, Any]) -> None:
    if "artifacts" in result:
        for artifact in result["artifacts"]:
            print(
                f"artifact {artifact['id']} [{artifact['kind']}] "
                f"mission={artifact['mission_id']} run={artifact['run_id']}: "
                f"{_short_text(artifact.get('title', ''))}"
            )
        return
    if "artifact" in result:
        artifact = result["artifact"]
        print(f"# {artifact['title']}")
        print(
            f"id={artifact['id']} kind={artifact['kind']} "
            f"mission={artifact['mission_id']} run={artifact['run_id']}"
        )
        print()
        print(artifact.get("body", ""))
        return
    print(dumps(result))


def _cmd_inbox(args: argparse.Namespace) -> int:
    command = args.inbox_command or "list"
    store = StateStore(args.state_dir)
    store.initialize()

    try:
        if command == "list":
            result = {
                "items": store.list_inbox_items(
                    status=_inbox_status_filter(args.status),
                    category=args.category,
                    priority_lte=_priority_lte(args.priority),
                    limit=max(0, args.limit),
                )
            }
        elif command == "show":
            item = store.get_inbox_item(args.item_id)
            if not item:
                raise MnemoError(f"inbox item not found: {args.item_id}")
            result = {"item": item}
        elif command == "resolve":
            result = resolve_inbox_item_with_actions(
                store,
                args.item_id,
                _inbox_resolution_from_args(args),
                notes=args.notes,
                source="cli",
            )
        else:
            raise MnemoError("inbox command requires list, show, or resolve")
    except ValueError as exc:
        raise MnemoError(str(exc)) from exc

    if args.json:
        print(dumps(result))
        return 0
    _print_inbox_result(result)
    return 0


def _print_inbox_result(result: dict[str, Any]) -> None:
    if "items" in result:
        for item in result["items"]:
            print(_format_inbox_item(item))
        return
    if "item" in result:
        item = result["item"]
        print(_format_inbox_item(item))
        if item.get("body"):
            print(item["body"])
        if item.get("action_data"):
            print(f"action_data={dumps(item['action_data'])}")
        if result.get("tool_result"):
            tool = result["tool_result"]
            print(f"tool_result {tool.get('tool') or tool.get('name')} ok={tool.get('ok')}: {tool.get('summary')}")
        return
    print(dumps(result))


def _format_inbox_item(item: dict[str, Any]) -> str:
    changed = item.get("changed")
    changed_suffix = f" changed={changed}" if changed is not None else ""
    resolution = f" resolution={item['resolution']}" if item.get("resolution") else ""
    return (
        f"inbox {item['id']} [{item['status']}] priority={_priority_name(int(item['priority']))} "
        f"category={item['category']} action={item['action_type']}{resolution}{changed_suffix}: "
        f"{_short_text(item.get('title', ''))}"
    )


def _inbox_status_filter(status: str | None) -> str | None:
    return None if status == "all" else status


def _priority_lte(priority: str | None) -> int | None:
    if priority is None:
        return None
    return {
        "critical": 0,
        "high": 1,
        "normal": 2,
        "low": 3,
    }[priority]


def _priority_name(priority: int) -> str:
    return {
        0: "critical",
        1: "high",
        2: "normal",
        3: "low",
    }.get(priority, str(priority))


def _inbox_resolution_from_args(args: argparse.Namespace) -> str:
    if args.accept:
        return "accepted"
    if args.reject:
        return "rejected"
    if args.ignore:
        return "ignored"
    raise MnemoError("inbox resolve requires --accept, --reject, or --ignore")


def _cmd_replay(args: argparse.Namespace) -> int:
    store = StateStore(args.state_dir)
    store.initialize()
    _require_run(store, args.run_id)
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

    try:
        if args.memory_command == "notes":
            result = _working_notes(store, args.status, args.limit)
        elif args.memory_command == "list":
            result = _list_memory_items(store, args.kind, args.status, args.limit)
        elif args.memory_command == "search":
            search = engine.search_with_plan(" ".join(args.query), limit=args.limit, search_scope=args.scope)
            result = search if args.debug_query else {"matches": search["matches"]}
        elif args.memory_command == "read":
            result = {"memory": _read_memory_item(store, args.memory_id)}
        elif args.memory_command == "links":
            result = _memory_links(store, args.memory_id, args.direction)
        elif args.memory_command == "snapshot":
            snapshot = engine.load_l1_snapshot()
            result = {"exists": snapshot is not None, "snapshot": snapshot}
        elif args.memory_command == "health":
            result = engine.health_report(limit=args.limit)
        elif args.memory_command == "tombstones":
            result = {
                "limit": max(0, int(args.limit)),
                "target_id": args.target_id,
                "target_type": args.target_type,
                "tombstones": store.list_memory_tombstones(
                    target_id=args.target_id,
                    target_type=args.target_type,
                    limit=args.limit,
                ),
            }
        elif args.memory_command == "tombstone":
            result = engine.tombstone_memory(args.memory_id, args.reason, target_type=args.target_type)
        elif args.memory_command == "promote":
            result = engine.promote_candidate(args.candidate_id)
        elif args.memory_command == "reject":
            result = engine.reject_candidate(args.candidate_id, args.reason)
        else:
            raise MnemoError("memory command requires a subcommand")
    except ValueError as exc:
        raise MnemoError(str(exc)) from exc

    if args.json:
        print(dumps(result))
        return 0
    _print_memory_result(result)
    return 0


def _cmd_dream(args: argparse.Namespace) -> int:
    store = StateStore(args.state_dir)
    store.initialize()
    engine = MemoryEngine(store)
    if args.now or args.dream_command == "run":
        result = engine.dream_maintenance(limit=args.limit, min_confidence=args.min_confidence)
    elif args.dream_command == "status":
        result = engine.dream_status(limit=args.limit)
    elif args.dream_command == "report":
        latest = bool(args.latest or not args.report_id)
        result = engine.load_dream_report(args.report_id, latest=latest)
        if not result:
            raise MnemoError("dream report not found")
    else:
        raise MnemoError("dream command requires a subcommand or --now")

    if args.json:
        print(dumps(result))
        return 0
    _print_dream_result(result)
    return 0


def _print_dream_result(result: dict[str, Any]) -> None:
    if result.get("kind") == "dream_status":
        latest = result.get("latest") or {}
        backlog = result.get("backlog") or {}
        latest_id = latest.get("id") or "-"
        print(
            "Dream status: "
            f"latest={latest_id} "
            f"w0_pending={backlog.get('w0_pending', 0)} "
            f"draft_candidates={backlog.get('draft_candidates', 0)} "
            f"review_cards={backlog.get('review_cards', 0)}"
        )
        return

    if result.get("kind") == "dream_report":
        execution = result.get("execution") if isinstance(result.get("execution"), dict) else {}
        execution_result = execution.get("result") if isinstance(execution.get("result"), dict) else {}
        w0 = execution_result.get("w0") if isinstance(execution_result.get("w0"), dict) else {}
        snapshot = execution_result.get("snapshot") if isinstance(execution_result.get("snapshot"), dict) else {}
        print(
            "Dream report: "
            f"id={result.get('id')} "
            f"mode={execution.get('mode')} "
            f"w0_created={len(w0.get('created', []))} "
            f"promoted={len(execution_result.get('promoted', []))} "
            f"rejected={len(execution_result.get('rejected', []))} "
            f"skipped={len(execution_result.get('skipped', []))} "
            f"conflicts={len(execution_result.get('conflicts', []))} "
            f"snapshot_items={snapshot.get('page_count', 0)}"
        )
        return

    print(dumps(result))


def _print_memory_result(result: dict) -> None:
    if "query_plan" in result:
        plan = result["query_plan"]
        print(
            "query_plan "
            f"routes={len(plan.get('routes', []))} "
            f"dimensions={','.join(plan.get('dimensions', [])) or '-'} "
            f"temporal={plan.get('temporal') or '-'}"
        )
    if "notes" in result:
        for note in result["notes"]:
            metadata = note.get("metadata") or {}
            retention = metadata.get("retention") or "ephemeral"
            print(
                f"note {note['id']} [{note['status']}] retention={retention} "
                f"mission={note['mission_id']} run={note['run_id']}: "
                f"{_short_text(note.get('content', ''))}"
            )
        return
    if "snapshot" in result and "exists" in result:
        snapshot = result.get("snapshot")
        if not snapshot:
            print("L1 memory snapshot missing")
            return
        print(
            f"L1 memory snapshot page_count={snapshot.get('page_count', 0)} "
            f"generated_at={snapshot.get('generated_at')}"
        )
        for item in snapshot.get("items", []):
            confidence = float(item.get("confidence", 0.0))
            print(
                f"- {item.get('id')} confidence={confidence:.2f} "
                f"scope={item.get('scope', '')}: {_short_text(item.get('title', ''))} :: "
                f"{_short_text(item.get('summary', ''))}"
            )
        return
    if result.get("kind") == "memory_health_report":
        counts = result.get("counts", {})
        score = result.get("score", {})
        pages = counts.get("pages", {})
        candidates = counts.get("candidates", {})
        print(
            "Memory health "
            f"overall={float(score.get('overall', 0.0)):.3f} "
            f"active_pages={pages.get('active', 0)} stale={pages.get('stale', 0)} "
            f"tombstones={counts.get('tombstones', 0)} draft_candidates={candidates.get('draft', 0)}"
        )
        for card in result.get("review_cards", []):
            print(
                f"- {card.get('kind')} {card.get('target_type')}:{card.get('target_id')} "
                f"[{card.get('status') or card.get('reason') or '-'}] {_short_text(card.get('summary', ''))}"
            )
        return
    if "tombstones" in result and "matches" not in result:
        for tombstone in result.get("tombstones", []):
            print(_format_memory_tombstone(tombstone))
        return
    if "tombstone_id" in result and "memory_id" in result:
        print(
            f"tombstoned {result['target_type']} {result['memory_id']} "
            f"-> {result['tombstone_id']} reason={result.get('reason', '')}"
        )
        return
    if "memory_id" in result and ("outgoing" in result or "incoming" in result):
        for link in result.get("outgoing", []):
            print(_format_memory_link("outgoing", link))
        for link in result.get("incoming", []):
            print(_format_memory_link("incoming", link))
        return
    if "candidates" in result or "pages" in result:
        for candidate in result.get("candidates", []):
            confidence = float(candidate.get("confidence", 0.0))
            print(
                f"candidate {candidate['id']} [{candidate['status']}] "
                f"confidence={confidence:.2f} scope={candidate.get('scope', '')}: "
                f"{_short_text(candidate.get('claim', ''))}"
            )
        for page in result.get("pages", []):
            confidence = float(page.get("confidence", 0.0))
            print(
                f"page {page['id']} [{page['status']}] "
                f"confidence={confidence:.2f} scope={page.get('scope', '')}: "
                f"{_short_text(page.get('title', ''))}"
            )
        return
    if "matches" in result:
        for item in result["matches"]:
            if item["type"] == "page":
                print(f"page {item['id']}: {item['title']} ({item['confidence']:.2f})")
            elif item["type"] == "linked_page":
                print(f"linked_page {item['id']}: {item['title']} relation={item.get('relation', '')}")
            elif item["type"] == "session_message":
                print(
                    f"session_message {item['id']} role={item.get('role', '')} "
                    f"conversation={item.get('conversation_id', '')} mission={item.get('mission_id', '')} "
                    f"run={item.get('run_id', '')}: {_short_text(item.get('snippet', ''))}"
                )
            else:
                print(f"candidate {item['id']}: {item['claim']} [{item['status']}]")
        return
    if "memory" in result:
        item = result["memory"]
        confidence = float(item.get("confidence", 0.0))
        print(f"{item['type']} {item['id']} [{item.get('status', 'unknown')}] confidence={confidence:.2f} scope={item.get('scope', '')}")
        if item["type"] == "page":
            print(item.get("title", ""))
            print(item.get("content", ""))
        else:
            print(item.get("claim", ""))
        return
    print(dumps(result))


def _list_memory_items(store: StateStore, kind: str, status: str | None, limit: int) -> dict[str, Any]:
    limit_value = max(0, int(limit))
    include_candidates = kind in {"candidate", "all"}
    include_pages = kind in {"page", "all"}
    candidates = (
        store.list_memory_candidates(status=_memory_status_filter(status, default="draft"), limit=limit_value)
        if include_candidates
        else []
    )
    pages = (
        store.list_memory_pages(status=_memory_status_filter(status, default="active"), limit=limit_value)
        if include_pages
        else []
    )
    return {
        "kind": kind,
        "status": status or "default",
        "limit": limit_value,
        "candidates": candidates,
        "pages": pages,
    }


def _working_notes(store: StateStore, status: str | None, limit: int) -> dict[str, Any]:
    limit_value = max(0, int(limit))
    return {
        "status": status or "open",
        "limit": limit_value,
        "notes": store.list_working_notes(status=_note_status_filter(status), limit=limit_value),
    }


def _note_status_filter(status: str | None) -> str | None:
    if status == "all":
        return None
    return status or "open"


def _memory_links(store: StateStore, memory_id: str, direction: str) -> dict[str, Any]:
    outgoing = store.list_memory_links(memory_id) if direction in {"outgoing", "both"} else []
    incoming = store.list_memory_backlinks(memory_id) if direction in {"incoming", "both"} else []
    return {
        "memory_id": memory_id,
        "direction": direction,
        "outgoing": outgoing,
        "incoming": incoming,
    }


def _format_memory_link(direction: str, link: dict[str, Any]) -> str:
    weight = float(link.get("weight", 0.0))
    return (
        f"{direction} {link['id']} {link['source_id']} -> {link['target_id']} "
        f"{link['relation']} weight={weight:.2f}"
    )


def _format_memory_tombstone(tombstone: dict[str, Any]) -> str:
    return (
        f"tombstone {tombstone['id']} {tombstone['target_type']}:{tombstone['target_id']} "
        f"reason={tombstone['reason']}: {_short_text(tombstone.get('summary', ''))}"
    )


def _memory_status_filter(status: str | None, *, default: str) -> str | None:
    if status is None:
        return default
    if status == "all":
        return None
    return status


def _read_memory_item(store: StateStore, memory_id: str) -> dict[str, Any]:
    candidate = store.get_memory_candidate(memory_id)
    if candidate:
        return {
            "type": "candidate",
            **candidate,
            "tombstones": store.list_memory_tombstones(target_id=memory_id, limit=10),
        }
    page = store.get_memory_page(memory_id)
    if page:
        return {
            "type": "page",
            **page,
            "tombstones": store.list_memory_tombstones(target_id=memory_id, limit=10),
        }
    raise MnemoError(f"memory not found: {memory_id}")


def _short_text(value: str, limit: int = 120) -> str:
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 1)]}..."


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

    try:
        if args.skills_command == "scan":
            result = {"skills": service.scan()}
        elif args.skills_command == "list":
            result = {"skills": service.list()}
        elif args.skills_command == "usage":
            stats = store.skill_usage_stats()
            result = {
                "usage": store.list_skill_usage(args.name, limit=max(0, args.limit)),
                "stats": {args.name: stats.get(args.name, _empty_skill_usage_stats())} if args.name else stats,
            }
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
    except ValueError as exc:
        raise MnemoError(str(exc)) from exc

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
    if "usage" in result:
        for event in result["usage"]:
            outcome = f" outcome={event['outcome']}" if event.get("outcome") else ""
            score = f" score={event['score']}" if event.get("score") is not None else ""
            print(f"{event['id']} {event['skill_name']} {event['event_type']}{outcome}{score}")
        return
    print(dumps(result))


def _empty_skill_usage_stats() -> dict[str, Any]:
    return {
        "uses": 0,
        "views": 0,
        "outcomes": 0,
        "successes": 0,
        "failures": 0,
        "neutral": 0,
        "last_used_at": None,
        "avg_score": 0.0,
    }


def _cmd_tools(args: argparse.Namespace) -> int:
    if args.tools_command in (None, "list"):
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

    store = StateStore(args.state_dir)
    store.initialize()
    service = ToolEvolutionService(store)

    if args.tools_command == "candidates":
        result = {"candidates": store.list_tool_candidates(status=args.status, limit=args.limit)}
    elif args.tools_command == "review":
        result = service.review_candidate(args.candidate_id)
    elif args.tools_command == "install":
        registry = ToolRegistry.from_store(store)
        result = service.install_candidate(
            args.candidate_id,
            available_tools={spec.name: spec for spec in registry.specs()},
        )
    elif args.tools_command == "uninstall":
        result = service.uninstall_generated_tool(args.name)
    else:
        raise MnemoError("tools command requires a valid subcommand")

    if args.json:
        print(dumps(result))
        return 0
    _print_tools_result(args.tools_command, result)
    return 0


def _print_tools_result(command: str, result: dict[str, Any]) -> None:
    if command == "candidates":
        for candidate in result["candidates"]:
            print(f"{candidate['id']} {candidate['name']} [{candidate['status']}]")
        return
    if command == "review":
        print(f"Tool candidate {result['candidate_id']} {result['status']}")
        for error in result.get("errors", []):
            print(f"- {error}")
        return
    if command == "install":
        if result.get("installed"):
            print(f"Installed generated tool {result['name']} -> {result['target_tool']}")
        else:
            print(f"Tool candidate {result['candidate_id']} {result['status']}")
            for error in result.get("errors", []):
                print(f"- {error}")
        return
    if command == "uninstall":
        print(f"Disabled generated tool {result['name']}")
        return
    print(dumps(result))


def _cmd_web(args: argparse.Namespace) -> int:
    config = _runtime_config_from_args(args)

    _validate_provider_config(config)

    serve_web(
        WebServerConfig(
            state_dir=config.state_dir,
            host=args.host,
            port=args.port,
            workspace_root=os.getcwd(),
            provider=config.provider,
            base_url=config.base_url,
            model=config.model,
            api_key=config.api_key,
            timeout_s=config.timeout_s,
            retry_count=config.retry_count,
            retry_backoff_s=config.retry_backoff_s,
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
    if args.harness_command == "variants":
        try:
            report = EvalHarness(state_dir=args.state_dir).run_variant_report(
                args.suite,
                variants=args.variant or None,
            )
        except ValueError as exc:
            raise MnemoError(str(exc)) from exc
        return _print_harness_report(report.as_dict(), json_output=args.json)
    if args.harness_command == "smoke":
        report = EvalHarness(state_dir=args.state_dir).run_suite("smoke")
        return _print_harness_report(report.as_dict(), json_output=args.json)
    if args.harness_command == "replay":
        store = StateStore(args.state_dir)
        store.initialize()
        _require_run(store, args.run_id)
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
            print(dumps({"suites": suites, "variants": list_variants()}))
        else:
            for suite in suites:
                print(suite)
            print("variants: " + ", ".join(list_variants()))
        return 0
    raise MnemoError("harness command requires a subcommand")


def _cmd_evals(args: argparse.Namespace) -> int:
    store = StateStore(args.state_dir)
    store.initialize()

    if args.evals_command == "create":
        _require_run(store, args.run_id)
        case_id = store.add_eval_case(
            args.run_id,
            args.name,
            _parse_json_object_arg(args.case_json, "--case-json"),
        )
        result = {"eval_case": store.get_eval_case(case_id)}
    elif args.evals_command == "list":
        result = {
            "eval_cases": store.list_eval_cases(
                status=args.status,
                tool_name=args.tool_name,
                skill_name=args.skill_name,
                limit=max(0, args.limit),
            )
        }
    elif args.evals_command == "record":
        if not store.get_eval_case(args.case_id):
            raise MnemoError(f"eval case not found: {args.case_id}")
        store.update_eval_case_status(
            args.case_id,
            args.status,
            result=_parse_json_object_arg(args.result_json, "--result-json"),
        )
        result = {"eval_case": store.get_eval_case(args.case_id)}
    else:
        raise MnemoError("evals command requires a subcommand")

    if args.json:
        print(dumps(result))
        return 0
    _print_evals_result(args.evals_command, result)
    return 0


def _print_evals_result(command: str, result: dict[str, Any]) -> None:
    if command == "create":
        case = result["eval_case"]
        print(f"Eval case {case['id']} created [{case['status']}]")
        return
    if command == "list":
        for case in result["eval_cases"]:
            print(f"{case['id']} {case['name']} [{case['status']}]")
        return
    if command == "record":
        case = result["eval_case"]
        print(f"Eval case {case['id']} {case['status']}")
        return
    print(dumps(result))


def _parse_json_object_arg(value: str, flag: str) -> dict[str, Any]:
    try:
        parsed = loads(value, default={})
    except ValueError as exc:
        raise MnemoError(f"{flag} must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise MnemoError(f"{flag} must be a JSON object")
    return parsed


def _cmd_config(args: argparse.Namespace) -> int:
    if args.config_command == "smoke":
        return _cmd_config_smoke(args)
    if args.config_command == "capabilities":
        return _cmd_config_capabilities(args)
    if args.config_command != "inspect":
        raise MnemoError("config command requires a subcommand")
    config = _runtime_config_from_args(args)
    payload = config.redacted()
    if args.json:
        print(dumps(payload))
    else:
        for key in (
            "state_dir",
            "provider",
            "base_url",
            "model",
            "api_key_env",
            "api_key",
            "timeout_s",
            "retry_count",
            "retry_backoff_s",
            "config_path",
        ):
            print(f"{key}={payload.get(key)}")
    return 0


def _cmd_config_capabilities(args: argparse.Namespace) -> int:
    config = _runtime_config_from_args(args)
    capabilities = provider_capabilities(config.provider, model=config.model)
    payload = {
        "provider": config.provider,
        "model": config.model,
        "capabilities": capabilities.metadata(),
        "cache_plan": capabilities.cache_plan(),
        "config": config.redacted(),
    }
    if args.json:
        print(dumps(payload))
        return 0
    print(f"provider={payload['provider']} model={payload['model']}")
    print(f"adapter_version={payload['capabilities']['adapter_version']}")
    print(f"prompt_cache_strategy={payload['capabilities']['prompt_cache_strategy']}")
    print(f"tool_schema_cache_strategy={payload['capabilities']['tool_schema_cache_strategy']}")
    print(f"context_window_tokens={payload['capabilities']['context_window_tokens']}")
    return 0


def _cmd_config_smoke(args: argparse.Namespace) -> int:
    config = _runtime_config_from_args(args)
    _validate_provider_config(config)
    if config.provider == "local":
        raise MnemoError("config smoke requires --provider openai-compatible or anthropic")

    if config.provider == "openai-compatible":
        adapter = _openai_adapter_from_config(config, stream=args.stream)
        models = _openai_models_smoke(adapter)
    else:
        adapter = _anthropic_adapter_from_config(config, stream=args.stream)
        models = {"ok": True, "skipped": True, "reason": "Anthropic-compatible model listing is not probed"}

    chat = _provider_chat_smoke(adapter, args.message)
    capabilities = provider_capabilities(config.provider, model=config.model)
    result = {
        "ok": bool(models.get("ok")) and bool(chat.get("ok")),
        "provider": config.provider,
        "model": config.model,
        "base_url": config.base_url,
        "capabilities": capabilities.metadata(),
        "cache_plan": capabilities.cache_plan(),
        "models": models,
        "chat": chat,
        "stream": args.stream,
        "config": config.redacted(),
    }
    if args.json:
        print(dumps(result))
        return 0 if result["ok"] else 1
    print(f"provider={result['provider']} model={result['model']} ok={result['ok']}")
    print(f"models={models.get('status', 'skipped')} count={models.get('count', 0)}")
    print(f"chat={chat.get('status')} preview={chat.get('response_preview', '')}")
    return 0 if result["ok"] else 1


def _cmd_daemon(args: argparse.Namespace) -> int:
    if args.daemon_command == "enqueue":
        runner = DaemonRunner(args.state_dir)
        try:
            queue_id = runner.enqueue(
                " ".join(args.message),
                conversation_id=args.conversation_id,
                mission_id=args.mission_id,
                metadata={"source": "cli", "workspace_root": os.getcwd()},
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
    elif args.daemon_command == "cancel":
        try:
            result = DaemonRunner(args.state_dir).cancel(args.queue_id, reason=args.reason)
        except ValueError as exc:
            raise MnemoError(str(exc)) from exc
    else:
        raise MnemoError("daemon command requires a subcommand")

    if args.json:
        print(dumps(result))
        return 0
    _print_daemon_result(args.daemon_command, result)
    return 0


def _cmd_schedule(args: argparse.Namespace) -> int:
    service = ScheduleService(args.state_dir)
    try:
        if args.schedule_command == "add":
            if args.kind == "watch":
                target = args.target or args.title
                instruction = args.instruction or args.message or target
                result = {
                    "item": service.add_watch(
                        target=target,
                        instruction=instruction,
                        schedule=args.schedule,
                        next_run_at=args.next_run_at,
                        metadata={"source": "cli", "workspace_root": os.getcwd()},
                    )
                }
            else:
                message = args.message or args.instruction
                result = {
                    "item": service.add_cron(
                        title=args.title,
                        message=message,
                        schedule=args.schedule,
                        next_run_at=args.next_run_at,
                        metadata={"source": "cli", "workspace_root": os.getcwd()},
                    )
                }
        elif args.schedule_command == "list":
            kind = None if args.kind == "all" else args.kind
            status = None if args.status == "all" else args.status
            result = {"items": service.list_items(kind=kind, status=status, limit=args.limit)}
        elif args.schedule_command == "tick":
            result = service.tick(now=args.now, limit=args.limit)
        elif args.schedule_command in {"pause", "resume", "disable"}:
            status = "active" if args.schedule_command == "resume" else args.schedule_command + "d"
            if args.schedule_command == "pause":
                status = "paused"
            result = {"item": service.update_status(args.item_id, status)}
        else:
            raise MnemoError("schedule command requires a subcommand")
    except ValueError as exc:
        raise MnemoError(str(exc)) from exc

    if args.json:
        print(dumps(result))
        return 0
    _print_schedule_result(args.schedule_command, result)
    return 0


def _queued_executor(args: argparse.Namespace):
    config = _runtime_config_from_args(args)
    if config.provider == "local":
        return run_local
    adapter = _provider_adapter(args)

    def execute(request: RunRequest):
        return run_provider(request, adapter)

    return execute


def _print_schedule_result(command: str, result: dict[str, Any]) -> None:
    if command == "add":
        item = result["item"]
        print(f"Scheduled {item['kind']} {item['id']} next_run_at={item['next_run_at']}")
        return
    if command == "list":
        for item in result["items"]:
            print(
                f"{item['id']} [{item['kind']}:{item['status']}] "
                f"{item['title']} schedule={item['schedule']} next={item['next_run_at']}"
            )
        return
    if command == "tick":
        print(
            f"Scheduled processed={len(result['processed'])} "
            f"pending={result['queue']['counts']['pending']} due={result['scheduled']['due']}"
        )
        return
    if command in {"pause", "resume", "disable"}:
        item = result["item"]
        changed = "changed" if item.get("changed") else "unchanged"
        print(f"Scheduled item {item['id']} {changed} status={item['status']}")
        return
    print(dumps(result))


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
            f"completed={counts['completed']} failed={counts['failed']} "
            f"scheduled_due={result.get('scheduled', {}).get('due', 0)} lock={lock}"
        )
        return
    if command == "recover":
        print(f"Recovered {len(result['recovered'])} queued run(s)")
        return
    if command == "cancel":
        changed = "cancelled" if result.get("changed") else "unchanged"
        print(f"Queue item {result['queue_id']} {changed} status={result['status']}")
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
        if report.get("kind") == "harness_variant_report":
            print(
                f"{report['suite']} variants: {status} "
                f"(target={report['target_variant']} baseline={report['baseline_variant']})"
            )
            for variant_report in report["reports"]:
                metrics = variant_report["metrics"]
                print(
                    f"- {variant_report['variant']}: "
                    f"task_success={metrics['task_success']} "
                    f"preference={metrics['preference_adherence']} "
                    f"wrong_memory={metrics['wrong_memory_rate']}"
                )
        else:
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
        return _anthropic_adapter_from_config(config, stream=stream)
    return _openai_compatible_adapter(args, stream=stream)


def _openai_compatible_adapter(args: argparse.Namespace, *, stream: bool = False) -> OpenAIProviderAdapter:
    config = _runtime_config_from_args(args)
    return _openai_adapter_from_config(config, stream=stream)


def _openai_adapter_from_config(config, *, stream: bool = False) -> OpenAIProviderAdapter:
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
            retry_count=config.retry_count,
            retry_backoff_s=config.retry_backoff_s,
            stream=stream,
        )
    )


def _anthropic_adapter_from_config(config, *, stream: bool = False) -> AnthropicProviderAdapter:
    return AnthropicProviderAdapter(
        ProviderConfig(
            base_url=config.base_url or _ANTHROPIC_DEFAULT_BASE_URL,
            model=config.model or "",
            api_key=config.api_key,
            timeout_s=config.timeout_s,
            retry_count=config.retry_count,
            retry_backoff_s=config.retry_backoff_s,
            stream=stream,
        )
    )


def _openai_models_smoke(adapter: OpenAIProviderAdapter) -> dict[str, Any]:
    payload = adapter.list_models()
    data = payload.get("data") or []
    model_ids: list[str] = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                model_ids.append(item["id"])
    return {
        "ok": True,
        "status": "passed",
        "count": len(model_ids),
        "ids": model_ids[:20],
    }


def _provider_chat_smoke(adapter: ProviderAdapter, message: str) -> dict[str, Any]:
    response_parts: list[str] = []
    metadata: dict[str, Any] = {}
    for event in adapter.stream(
        ProviderRunInput(
            messages=[{"role": "user", "content": message}],
            tools=[],
            metadata={"source": "config_smoke"},
        )
    ):
        if event.type == "text_delta" and event.text:
            response_parts.append(event.text)
        elif event.type == "completed":
            metadata = event.metadata
    response = "".join(response_parts).strip()
    return {
        "ok": True,
        "status": "passed",
        "response_preview": response[:240],
        "metadata": metadata,
    }


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
            retry_count=getattr(args, "retry_count", None),
            retry_backoff_s=getattr(args, "retry_backoff_s", None),
            config_path=getattr(args, "config", None),
        )
    )
