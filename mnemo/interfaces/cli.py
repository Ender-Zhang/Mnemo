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
from ..providers import OpenAIProviderAdapter, ProviderConfig
from ..runtime import result_as_dict, run_local, stream_local
from ..runtime.provider import run_provider, stream_provider
from ..runtime.ledger import RunLedger
from ..storage import StateStore
from ..tools import ToolRegistry, tool_specs_as_json_schema


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
        if args.command == "tools":
            return _cmd_tools(args)
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
    events_parser.add_argument("--json", action="store_true")

    tools_parser = subparsers.add_parser("tools", help="Print available tool specs")
    tools_parser.add_argument("--json", action="store_true")
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
            else stream_provider(request, _openai_compatible_adapter(args))
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
    events = ledger.events(args.run_id)
    if args.json:
        print(dumps({"events": events}))
        return 0

    for event in events:
        print(f"{event['seq']:03d} {event['event_type']} {dumps(event['payload'])}")
    return 0


def _cmd_tools(args: argparse.Namespace) -> int:
    tools = tool_specs_as_json_schema(ToolRegistry().specs())
    if args.json:
        print(dumps({"tools": tools}))
        return 0
    for tool in tools:
        print(f"{tool['name']} [{tool['risk']}]: {tool['description']}")
    return 0


def _provider_name(args: argparse.Namespace) -> str:
    return args.provider or os.environ.get("MNEMO_PROVIDER") or DEFAULT_PROVIDER


def _openai_compatible_adapter(args: argparse.Namespace) -> OpenAIProviderAdapter:
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
