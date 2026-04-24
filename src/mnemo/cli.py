from __future__ import annotations

import argparse
import sys
from typing import Sequence

from . import __version__
from .errors import MnemoError
from .jsonutil import dumps
from .ledger import RunLedger
from .models import RunRequest
from .runtime import result_as_dict, run_local
from .storage import StateStore
from .tools import ToolRegistry, tool_specs_as_json_schema


DEFAULT_STATE_DIR = "~/.mnemo"


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
    message = " ".join(args.message)
    result = run_local(
        RunRequest(
            message=message,
            state_dir=args.state_dir,
            conversation_id=args.conversation_id,
            mission_id=args.mission_id,
        )
    )
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
