from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import tempfile
from typing import Any

from ..core.models import RunRequest
from ..runtime import stream_local
from ..runtime.ledger import RunLedger
from ..storage import StateStore


@dataclass(frozen=True)
class EvalStep:
    message: str
    expect_response_contains: tuple[str, ...] = ()
    expect_tool_names: tuple[str, ...] = ()
    expect_event_types: tuple[str, ...] = ()
    expect_memory_match_count: int | None = None
    expect_same_mission_as_previous: bool = False


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    name: str
    steps: tuple[EvalStep, ...]


@dataclass
class AssertionResult:
    name: str
    passed: bool
    detail: str


@dataclass
class StepReport:
    message: str
    run_id: str
    conversation_id: str
    mission_id: str
    response: str
    event_types: list[str]
    tool_names: list[str]
    assertions: list[AssertionResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(assertion.passed for assertion in self.assertions)


@dataclass
class CaseReport:
    case_id: str
    name: str
    passed: bool
    steps: list[StepReport]


@dataclass
class SuiteReport:
    suite: str
    passed: bool
    case_count: int
    passed_count: int
    failed_count: int
    cases: list[CaseReport]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class EvalHarness:
    def __init__(self, *, state_dir: str | Path | None = None):
        self.state_dir = Path(state_dir).expanduser().resolve() if state_dir else None

    def run_suite(self, suite: str) -> SuiteReport:
        cases = _suite_cases(suite)
        case_reports = [self.run_case(case) for case in cases]
        passed_count = sum(1 for report in case_reports if report.passed)
        return SuiteReport(
            suite=suite,
            passed=passed_count == len(case_reports),
            case_count=len(case_reports),
            passed_count=passed_count,
            failed_count=len(case_reports) - passed_count,
            cases=case_reports,
        )

    def run_case(self, case: EvalCase) -> CaseReport:
        with self._case_state_dir(case.case_id) as state_dir:
            step_reports: list[StepReport] = []
            conversation_id: str | None = None
            previous_mission_id: str | None = None

            for step in case.steps:
                events = list(
                    stream_local(
                        RunRequest(
                            message=step.message,
                            state_dir=state_dir,
                            conversation_id=conversation_id,
                        )
                    )
                )
                completed = events[-1]
                result = completed.data["result"]
                conversation_id = result["conversation_id"]
                tool_names = [tool["name"] for tool in result.get("tool_results", [])]
                event_types = [event.type for event in events]
                assertions = _assert_step(
                    step,
                    state_dir=state_dir,
                    run_id=result["run_id"],
                    response=result["response"],
                    event_types=event_types,
                    tool_names=tool_names,
                    tool_results=result.get("tool_results", []),
                    mission_id=result["mission_id"],
                    previous_mission_id=previous_mission_id,
                )
                previous_mission_id = result["mission_id"]
                step_reports.append(
                    StepReport(
                        message=step.message,
                        run_id=result["run_id"],
                        conversation_id=result["conversation_id"],
                        mission_id=result["mission_id"],
                        response=result["response"],
                        event_types=event_types,
                        tool_names=tool_names,
                        assertions=assertions,
                    )
                )

            return CaseReport(
                case_id=case.case_id,
                name=case.name,
                passed=all(step.passed for step in step_reports),
                steps=step_reports,
            )

    def _case_state_dir(self, case_id: str) -> tempfile.TemporaryDirectory[str]:
        if not self.state_dir:
            return tempfile.TemporaryDirectory(prefix=f"mnemo-eval-{case_id}-")
        root = self.state_dir / "evals" / "tmp"
        root.mkdir(parents=True, exist_ok=True)
        return tempfile.TemporaryDirectory(prefix=f"{case_id}-", dir=root)


def list_suites() -> list[str]:
    return sorted(_BUILTIN_SUITES)


def replay_summary(state_dir: str | Path, run_id: str) -> dict[str, Any]:
    store = StateStore(state_dir)
    store.initialize()
    ledger = RunLedger(store)
    trace = ledger.load_trace(run_id)
    event_types = [event.get("event_type") for event in trace]
    chat_events = ledger.chat_events(run_id)
    return {
        "run_id": run_id,
        "event_count": len(trace),
        "chat_event_count": len(chat_events),
        "event_types": event_types,
        "completed": any(
            event.get("event_type") == "run.completed"
            and event.get("payload", {}).get("status") == "completed"
            for event in trace
        ),
        "trace_path": str(ledger.trace_path(run_id)),
    }


def _assert_step(
    step: EvalStep,
    *,
    state_dir: str,
    run_id: str,
    response: str,
    event_types: list[str],
    tool_names: list[str],
    tool_results: list[dict[str, Any]],
    mission_id: str,
    previous_mission_id: str | None,
) -> list[AssertionResult]:
    assertions: list[AssertionResult] = []
    for text in step.expect_response_contains:
        assertions.append(
            AssertionResult(
                name=f"response_contains:{text}",
                passed=text in response,
                detail=response,
            )
        )
    for tool_name in step.expect_tool_names:
        assertions.append(
            AssertionResult(
                name=f"tool_called:{tool_name}",
                passed=tool_name in tool_names,
                detail=", ".join(tool_names),
            )
        )
    for event_type in step.expect_event_types:
        assertions.append(
            AssertionResult(
                name=f"event_emitted:{event_type}",
                passed=event_type in event_types,
                detail=", ".join(event_types),
            )
        )
    if step.expect_memory_match_count is not None:
        match_count = _memory_match_count(tool_results)
        assertions.append(
            AssertionResult(
                name="memory_match_count",
                passed=match_count == step.expect_memory_match_count,
                detail=str(match_count),
            )
        )
    if step.expect_same_mission_as_previous:
        assertions.append(
            AssertionResult(
                name="same_mission_as_previous",
                passed=previous_mission_id is not None and mission_id == previous_mission_id,
                detail=f"previous={previous_mission_id} current={mission_id}",
            )
        )

    replay = replay_summary(state_dir, run_id)
    assertions.append(
        AssertionResult(
            name="trace_completed",
            passed=bool(replay["completed"]) and replay["event_count"] > 0,
            detail=replay["trace_path"],
        )
    )
    return assertions


def _memory_match_count(tool_results: list[dict[str, Any]]) -> int:
    for result in tool_results:
        if result.get("name") == "memory_search":
            matches = result.get("result", {}).get("matches", [])
            if isinstance(matches, list):
                return len(matches)
    return 0


def _suite_cases(suite: str) -> tuple[EvalCase, ...]:
    try:
        return _BUILTIN_SUITES[suite]
    except KeyError as exc:
        known = ", ".join(list_suites())
        raise ValueError(f"unknown eval suite: {suite}. Known suites: {known}") from exc


_PERSONALIZATION_CORE = (
    EvalCase(
        case_id="memory-candidate-capture",
        name="Memory Candidate Capture",
        steps=(
            EvalStep(
                message="remember: User prefers concise engineering updates",
                expect_response_contains=("记忆候选",),
                expect_tool_names=("memory_write_candidate",),
                expect_event_types=("learning.chip", "run.completed"),
            ),
        ),
    ),
    EvalCase(
        case_id="multi-turn-memory-recall",
        name="Multi-Turn Memory Recall",
        steps=(
            EvalStep(
                message="remember: User prefers direct answers",
                expect_tool_names=("memory_write_candidate",),
                expect_event_types=("learning.chip",),
            ),
            EvalStep(
                message="search: direct answers",
                expect_response_contains=("找到 1",),
                expect_tool_names=("memory_search",),
                expect_event_types=("source.attached", "run.completed"),
                expect_memory_match_count=1,
                expect_same_mission_as_previous=True,
            ),
        ),
    ),
    EvalCase(
        case_id="artifact-card-projection",
        name="Artifact Card Projection",
        steps=(
            EvalStep(
                message="artifact: Draft launch notes",
                expect_response_contains=("已更新产物",),
                expect_tool_names=("artifact_update",),
                expect_event_types=("artifact.card", "source.attached", "run.completed"),
            ),
        ),
    ),
)


_BUILTIN_SUITES = {
    "personalization-core": _PERSONALIZATION_CORE,
    "smoke": _PERSONALIZATION_CORE,
}
