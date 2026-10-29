"""Answer-quality A/B: fallback vs ddg_first through the real chat service.

This runs the same calls ``POST /chat`` makes - ``ChatService.start_turn`` then
``ChatService.generate`` on the production service graph - for the frozen
Search-2 question set. It is a measurement harness, not a new pipeline: the
search strategy is the only thing that differs between the two arms, and it is
selected the way a deployment selects it (``WEB_SEARCH_STRATEGY`` set before the
gateway exists).

Offline by default. ``--plan`` (default), ``--validate-budget`` and
``--check-wiring`` send no request and need no provider key. ``--live`` is
refused unless:

* conservative prices and a per-process cap of at most 5 CNY are configured
  (two arms, so the run as a whole stays inside the authorised 10 CNY),
* ``LLM_SPEND_EXPERIMENT_ID`` is **not** set: the bounded research path does not
  bind an experiment invocation, so experiment mode would refuse every research
  call as ``send_not_admitted`` instead of measuring anything,
* ``--confirm`` carries the fixed token, so a paid run is a deliberate act.

The spend guard reserves the worst case before each send and fails closed. This
script adds the one limit the guard cannot know: a hard send count. It wraps
``reserve_call`` for the duration of the run, so the twentieth send in an arm is
the last one this process can make, whatever the model does. No request is
retried by this script; a failed question is recorded and the run moves on.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_CASES = (
    REPO_ROOT
    / "tests"
    / "fixtures"
    / "provider_routing"
    / "search_2_fact_checks_v1.json"
)
DEFAULT_OUTPUT_DIR = REPO_ROOT / "docs" / "research_quality" / "answer_ab"
#: Durable count of paid sends already made by the experiment.
SEND_STATE = DEFAULT_OUTPUT_DIR / "sends_state.json"

#: Frozen envelope. Changing one of these changes the experiment, so they are
#: constants rather than flags.
MAX_QUESTIONS = 10
#: 10 questions x 2 arms, plus the 21 sends the two aborted inline-tool-loop
#: attempts already spent. Raised from 40 to 45 with the owner's approval
#: (2026-10-30); the money caps did not change.
MAX_SENDS = 45
#: Per process. Two arms, so the pair still fits the authorised 10 CNY.
MAX_COST_PER_PROCESS_CNY = 5.0
CONFIRM_TOKEN = "ANSWER-AB-PAID"

ARMS = {"fallback": "", "ddg_first": "ddg_first"}

PRICE_KEYS = (
    "LLM_SPEND_INPUT_CNY_PER_MTOK",
    "LLM_SPEND_OUTPUT_CNY_PER_MTOK",
)
EXPERIMENT_ENV = "LLM_SPEND_EXPERIMENT_ID"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_cases(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases") if isinstance(payload, dict) else None
    if not isinstance(cases, list) or not cases:
        raise ValueError(f"no cases in {path}")
    return cases


def _float_env(name: str) -> float | None:
    raw = os.getenv(name, "").strip()
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


def _counters() -> dict[str, float]:
    from src.llm_spend_guard import remaining_cny, spend_cap_cny, spent_cny

    return {
        "cap_cny": spend_cap_cny(),
        "spent_cny": round(spent_cny(), 4),
        "remaining_cny": (
            None if remaining_cny() is None else round(remaining_cny() or 0.0, 4)
        ),
    }


def _durable_send_count() -> int:
    """Sends already spent by this experiment, across processes.

    The money cap is durable. The send cap has to be too, otherwise a resumed
    arm would silently get a fresh allowance. The experiment ledger cannot
    count for us here (experiment mode refuses the research path), so this file
    is the record; it is written after every question.
    """

    path = SEND_STATE
    if not path.exists():
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return max(0, int(payload.get("sends", 0)))
    except (OSError, ValueError, TypeError):
        return 0


def _record_sends(total: int) -> None:
    SEND_STATE.parent.mkdir(parents=True, exist_ok=True)
    SEND_STATE.write_text(
        json.dumps({"sends": int(total), "updated_at": _now()}), encoding="utf-8"
    )


def _ensure_ledger_schema() -> str:
    """Create the runtime schema when the ledger *is* the runtime database.

    The ledger deliberately refuses a database it cannot find its tables in.
    A fresh worktree has no runtime database yet, so the precheck would report
    "tables missing" for a ledger that a real run would migrate on first use.
    """

    if os.getenv("LLM_SPEND_LEDGER_DB", "").strip():
        return ""
    from src.application.runtime_repository import runtime_database_path
    from src.infrastructure.sqlite.database import RuntimeDatabase

    database = RuntimeDatabase(runtime_database_path())
    database.initialize()
    return str(database.path)


def validate_budget() -> tuple[bool, list[str], dict[str, Any]]:
    """Zero-cost check that a paid run could actually be stopped on budget."""

    from src.llm_spend_guard import spend_ledger_path

    problems: list[str] = []
    cap = _float_env("LLM_SPEND_CAP_CNY")
    prices = {key: _float_env(key) for key in PRICE_KEYS}
    report: dict[str, Any] = {
        "cap_cny_per_process": cap,
        "prices": prices,
        "experiment": os.getenv(EXPERIMENT_ENV, "") or "(unset, as required)",
        "ledger": os.getenv("LLM_SPEND_LEDGER_DB", "(runtime database)"),
        "limits": {
            "questions": MAX_QUESTIONS,
            "answers": MAX_QUESTIONS * len(ARMS),
            "sends_total": MAX_SENDS,
            "sends_already_reserved": _durable_send_count(),
            "cny_total": MAX_COST_PER_PROCESS_CNY * len(ARMS),
            "cny_per_process": MAX_COST_PER_PROCESS_CNY,
        },
    }
    if cap is None:
        problems.append("LLM_SPEND_CAP_CNY is not set")
    elif cap > MAX_COST_PER_PROCESS_CNY:
        problems.append(
            f"cap {cap} exceeds the per-process {MAX_COST_PER_PROCESS_CNY} CNY "
            f"(two arms must stay inside {MAX_COST_PER_PROCESS_CNY * 2} CNY)"
        )
    for key, value in prices.items():
        if value is None or value <= 0:
            problems.append(f"{key} is missing")
    if os.getenv(EXPERIMENT_ENV, "").strip():
        problems.append(
            f"{EXPERIMENT_ENV} must stay unset: the bounded research path does not "
            "bind an experiment invocation, so experiment mode refuses those sends"
        )
    if os.getenv("STUDY_AGENT_SETTLEMENT_ADMISSION", "").strip().lower() in {
        "1",
        "true",
        "on",
        "yes",
    }:
        problems.append(
            "STUDY_AGENT_SETTLEMENT_ADMISSION must stay off: the research "
            "interpreter is not wired to it and every call would be refused"
        )
    try:
        report["ledger_path"] = spend_ledger_path()
    except Exception as exc:  # noqa: BLE001
        problems.append(f"ledger path unavailable: {exc}")
    try:
        initialized = _ensure_ledger_schema()
        if initialized:
            report["ledger_initialized"] = initialized
    except Exception as exc:  # noqa: BLE001
        problems.append(f"ledger schema unavailable: {exc}")
    report["before"] = _counters()
    return (not problems), problems, report


def _evidence_summary(trace: dict[str, Any]) -> dict[str, Any]:
    """What the answer was allowed to see, without the whole page bodies."""

    calls = list(trace.get("calls") or [])
    searches: list[dict[str, Any]] = []
    reads: list[dict[str, Any]] = []
    for call in calls:
        name = str(call.get("name") or "")
        result = call.get("result") if isinstance(call.get("result"), dict) else {}
        if name == "web_search":
            results = result.get("results") or []
            searches.append(
                {
                    "query": str((call.get("arguments") or {}).get("query") or ""),
                    "status": result.get("status"),
                    "providers": result.get("providers_attempted"),
                    "fallback_used": result.get("fallback_used"),
                    "count": len(results),
                    "top": [
                        {
                            "title": str((row or {}).get("title") or "")[:120],
                            "url": str((row or {}).get("url") or ""),
                        }
                        for row in results[:3]
                    ],
                }
            )
        elif name == "web_read":
            reads.append(
                {
                    "url": str((call.get("arguments") or {}).get("url") or ""),
                    "ok": result.get("ok"),
                    "error": result.get("error") or "",
                    "error_code": result.get("error_code") or "",
                    "kind": result.get("kind") or "",
                }
            )
    return {"searches": searches, "reads": reads}


def _research_step(service: Any, query: str) -> dict[str, Any]:
    """The product's one-shot research run: create and execute."""
    started = time.monotonic()
    run = service.lookup(query, max_items=8)
    seconds = round(time.monotonic() - started, 2)
    attempts = []
    for attempt in getattr(run, "query_attempts", []) or []:
        if isinstance(attempt, dict):
            attempts.append(
                {
                    "query": str(attempt.get("query") or "")[:200],
                    "status": str(attempt.get("status") or ""),
                    "providers": attempt.get("providers_attempted"),
                }
            )
    sources = []
    for source in getattr(run, "selected_sources", []) or []:
        if not isinstance(source, dict):
            continue
        # A selected source is {assessment: {...}, item: {...}}: the assessment
        # owns the judged title/url, the item owns the raw search row.
        assessment = source.get("assessment") if isinstance(
            source.get("assessment"), dict
        ) else {}
        item = source.get("item") if isinstance(source.get("item"), dict) else {}
        sources.append(
            {
                "title": str(assessment.get("title") or item.get("title") or "")[:120],
                "url": str(assessment.get("url") or item.get("link") or ""),
                "relevance": assessment.get("relevance"),
                "directness": assessment.get("directness"),
            }
        )
    source_block = str(getattr(run, "source_block", "") or "")
    return {
        "run_id": getattr(run, "id", ""),
        "status": getattr(run, "status", ""),
        "provider_status": getattr(run, "provider_status", ""),
        "stop_reason": getattr(run, "stop_reason", ""),
        "answer_confidence": getattr(run, "answer_confidence", ""),
        "seconds": seconds,
        "source_block_chars": len(source_block),
        "source_block": source_block[:24_000],
        "sources": sources,
        "query_attempts": attempts,
        "warnings": [str(item)[:200] for item in (getattr(run, "warnings", []) or [])],
        "_source_block": source_block,
        "_run": run,
    }


def _answer_step(
    service: Any, question: str, research: dict[str, Any], *, intent: str
) -> dict[str, Any]:
    """The chat turn that answers from the completed research run.

    The command mirrors ``_chat_command`` for a run-backed turn: the run's
    source block is the evidence, the run id is the provenance, and the
    server-built validation plan gates the answer. No second research is asked
    for, because the user's follow-up is a normal question about evidence that
    already exists.
    """

    from src.application.policy_chat_service import PolicyChatCommand
    from src.application.research_evidence import (
        research_binding_rows,
        research_run_provenance,
        research_sources_snapshot,
    )

    run = research.get("_run")
    source_block = str(research.get("_source_block") or "")
    answer_validation = None
    if research_run_provenance(run):
        answer_validation = {
            "evidence_rows": research_binding_rows(run),
            "allowed_attempts": 1,
        }
    started = time.monotonic()
    prepared = service.start_turn(
        PolicyChatCommand(
            user_input=question,
            web_policy="auto",
            web_context=source_block,
            web_context_run_id=str(research.get("run_id") or ""),
            research_sources=research_sources_snapshot(run),
            answer_validation=answer_validation,
            task_intent=intent or None,  # type: ignore[arg-type]
            performance_mode="standard",
            context_mode="standard",
        )
    )
    prepared_seconds = round(time.monotonic() - started, 2)
    answer_started = time.monotonic()
    reply = service.generate(prepared)
    answer_seconds = round(time.monotonic() - answer_started, 2)
    return {
        "turn_id": prepared.turn.id,
        "session_id": prepared.thread.id,
        "text": reply,
        "seconds": answer_seconds,
        "prepared_seconds": prepared_seconds,
        "web_context_used": prepared.web_context_used,
        "validation_plan": bool(answer_validation),
        "route": {
            "mode": (prepared.route or {}).get("mode"),
            "model_profile": (prepared.route or {}).get("model_profile"),
            "task_intent": ((prepared.route or {}).get("task_contract") or {}).get(
                "task_intent"
            ),
            "answer_generation_calls": (prepared.route or {}).get(
                "answer_generation_calls"
            ),
        },
    }


def _check_strategy(arm: str) -> str:
    from src.application.runtime_repository import get_web_tool_agent

    actual = str(getattr(get_web_tool_agent().gateway, "search_strategy", ""))
    expected = ARMS[arm] or "fallback"
    if actual != expected:
        raise SystemExit(
            f"arm {arm} expected strategy {expected!r}, the gateway reports {actual!r}"
        )
    return actual


def _check_wiring(arm: str) -> int:
    """Prove the arm and the service graph before spending.

    Construction only: no provider request is made. This is the step that would
    catch "the strategy never reached the gateway", which is exactly the failure
    that would otherwise be paid for twenty times.
    """

    os.environ["WEB_SEARCH_STRATEGY"] = ARMS[arm]
    strategy = _check_strategy(arm)
    from src.application.runtime_repository import get_chat_service
    from src.llm_client import get_model_name

    service = get_chat_service()
    print(
        json.dumps(
            {
                "arm": arm,
                "strategy": strategy,
                "service": type(service).__name__,
                "model": get_model_name("flash"),
                "counters": _counters(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print("WIRING: PASS (no request sent)")
    return 0


class SendMeter:
    """Count paid sends and refuse the one after the arm's allowance.

    The guard bounds money, not count. This wraps the single function every paid
    request passes through, so no call path can escape the count.
    """

    def __init__(self, allowance: int) -> None:
        self.allowance = allowance
        self.count = 0
        self._original = None

    def __enter__(self) -> SendMeter:
        import src.llm_spend_guard as guard

        self._original = guard.reserve_call
        meter = self

        def counted(**kwargs: Any):
            if meter.count >= meter.allowance:
                raise RuntimeError(
                    f"answer_ab_send_budget_exhausted: {meter.count} sends used"
                )
            meter.count += 1
            return meter._original(**kwargs)  # type: ignore[misc]

        # ``llm_client`` imports this name inside each request build, so the
        # module attribute is what every paid call resolves.
        guard.reserve_call = counted  # type: ignore[assignment]
        return self

    def __exit__(self, *_exc: object) -> None:
        import src.llm_spend_guard as guard

        if self._original is not None:
            guard.reserve_call = self._original  # type: ignore[assignment]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", choices=sorted(ARMS), default="fallback")
    parser.add_argument(
        "--intent",
        default="quick_answer",
        help=(
            "explicit task intent for the answer turn (default: quick_answer, so the "
            "answer uses the attached run instead of asking for a second research)"
        ),
    )
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument(
        "--limit",
        type=int,
        default=MAX_QUESTIONS,
        help="how many questions this invocation may answer (pilot: 3)",
    )
    parser.add_argument(
        "--exclude",
        default="",
        help="comma-separated case ids already paid for and not to repeat",
    )
    parser.add_argument(
        "--skip",
        type=int,
        default=0,
        help="skip the first N cases (resume after a pilot without re-paying)",
    )
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--env-file", type=Path, default=REPO_ROOT / ".env")
    parser.add_argument(
        "--live", action="store_true", help="send paid calls (needs --confirm)"
    )
    parser.add_argument("--confirm", default="", help=f"must be {CONFIRM_TOKEN}")
    parser.add_argument(
        "--validate-budget", action="store_true", help="zero-cost budget precheck"
    )
    parser.add_argument(
        "--check-wiring",
        action="store_true",
        help="construct the real service graph, send nothing",
    )
    args = parser.parse_args(argv)

    if args.env_file.exists():
        from dotenv import load_dotenv

        load_dotenv(args.env_file, override=False)

    cases = _load_cases(args.cases)[: max(1, min(args.limit, MAX_QUESTIONS))]
    if args.skip:
        cases = cases[max(0, args.skip) :]
    excluded = {item.strip() for item in args.exclude.split(",") if item.strip()}
    if excluded:
        cases = [case for case in cases if case.get("id") not in excluded]
    if not cases:
        print("no cases selected")
        return 1
    profile = {name: _float_env(name) for name in PRICE_KEYS}
    print(f"=== plan: arm={args.arm} questions={len(cases)}")
    for case in cases:
        print(f"  {case['id']:<4} {case['query']}")
    print(
        f"  budget: <= {MAX_SENDS} sends for the whole experiment, "
        f"<= {MAX_COST_PER_PROCESS_CNY} CNY this process, no retries"
    )
    print(f"  prices: {profile}")

    ok, problems, report = validate_budget()
    if args.validate_budget:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if not ok:
            print("BUDGET PRECHECK: FAIL")
            for problem in problems:
                print(f"  - {problem}")
            return 1
        print("BUDGET PRECHECK: PASS (no request sent)")
        return 0
    if args.check_wiring:
        if not ok:
            print("WIRING: FAIL (budget precheck)")
            for problem in problems:
                print(f"  - {problem}")
            return 1
        return _check_wiring(args.arm)
    if not args.live:
        print("\nDRY RUN - no request sent.")
        if not ok:
            print("a paid run would currently refuse:")
            for problem in problems:
                print(f"  - {problem}")
        return 0

    if args.confirm != CONFIRM_TOKEN:
        print(f"REFUSED: --live needs --confirm {CONFIRM_TOKEN}")
        return 1
    if not ok:
        print("REFUSED: the budget precheck did not pass:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    os.environ["WEB_SEARCH_STRATEGY"] = ARMS[args.arm]
    strategy = _check_strategy(args.arm)
    from src.application.runtime_repository import (
        get_chat_service,
        get_web_lookup_service,
    )

    service = get_chat_service()
    print(f"  strategy in use: {strategy}")
    print(f"  counters before: {json.dumps(_counters())}")

    turns: list[dict[str, Any]] = []
    stopped = ""
    already = _durable_send_count()
    allowance = max(0, MAX_SENDS - already)
    print(f"  sends: {already} already reserved, allowance {allowance}")
    with SendMeter(allowance) as meter:
        for case in cases:
            if meter.count >= allowance:
                stopped = f"send budget: {already + meter.count}/{MAX_SENDS} used"
                break
            counters = _counters()
            if (counters["spent_cny"] or 0.0) >= MAX_COST_PER_PROCESS_CNY:
                stopped = f"cost budget: {counters['spent_cny']} CNY used"
                break
            row: dict[str, Any] = {"id": case["id"], "query": case["query"]}
            sends_before = meter.count
            research_service = get_web_lookup_service()
            try:
                research = _research_step(research_service, case["query"])
            except Exception as exc:  # noqa: BLE001 - recorded, never retried
                row["research_error"] = f"{type(exc).__name__}: {exc}"[:1000]
                row["sends_used"] = meter.count - sends_before
                turns.append(row)
                print(f"  {case['id']}: RESEARCH ERROR {row['research_error'][:140]}")
                if "send_budget_exhausted" in row["research_error"]:
                    stopped = f"send budget: {already + meter.count}/{MAX_SENDS} used"
                    break
                continue
            row["research"] = {
                key: value for key, value in research.items() if not key.startswith("_")
            }
            usable = research["status"] in {"completed", "partial"} and bool(
                research["_source_block"].strip()
            )
            print(
                f"  {case['id']} research: {research['status']} "
                f"{research['seconds']}s, {len(research['sources'])} sources, "
                f"{research['source_block_chars']} chars"
            )
            if usable:
                try:
                    row["answer"] = _answer_step(
                        service, case["query"], research, intent=args.intent
                    )
                    print(
                        f"  {case['id']} answer: {row['answer']['seconds']}s, "
                        f"{len(row['answer']['text'])} chars"
                    )
                except Exception as exc:  # noqa: BLE001 - recorded, never retried
                    row["answer_error"] = f"{type(exc).__name__}: {exc}"[:1000]
                    print(f"  {case['id']} ANSWER ERROR {row['answer_error'][:140]}")
            else:
                row["answer"] = None
                print(f"  {case['id']} answer: skipped (no usable evidence block)")
            row["sends_used"] = meter.count - sends_before
            row["sends_after"] = meter.count
            row["counters_after"] = _counters()
            turns.append(row)
            _record_sends(already + meter.count)

    output = args.output or (
        DEFAULT_OUTPUT_DIR / f"{args.arm}_{datetime.now().strftime('%Y%m%dT%H%M%S')}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "answer-quality-ab-v1",
        "generated_at": _now(),
        "arm": args.arm,
        "strategy": strategy,
        "intent": args.intent,
        "limits": report["limits"],
        "stopped": stopped,
        "sends_used": meter.count,
        "counters_after": _counters(),
        "turns": turns,
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {output}")
    print(f"  sends used {already + meter.count}/{MAX_SENDS}")
    if stopped:
        print(f"  STOPPED EARLY: {stopped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
