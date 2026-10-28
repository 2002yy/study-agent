"""QP-1C: raw question vs current production planning vs the QP-1B instruction.

Offline by default: without ``--live`` the script prints what it would do and
exits, so running the archived harness cannot spend money. A paid rerun needs
``--live --experiment-id ... --cap-cny ... --ledger <existing ledger>`` and an
environment where ``STUDY_AGENT_SETTLEMENT_ADMISSION`` is already enabled; the
script never enables admission itself and never relaxes a stricter cap or price
already present in the environment.

The historical run used 10 questions, at most 2 model calls per question, 20
calls in total and a 3 CNY cap. The guard is configured before any client is
built, so a missing price or a bad model id fails closed instead of spending.

Groups, all searched with the same provider and the same result limit:

- A: the user sentence, no model call.
- B: the production instruction before QP-1B (`BASELINE_INSTRUCTION`).
- C: the current production instruction (`_TURN_INSTRUCTION`, QP-1B).

Each query is searched separately, so DirectHit@6 and MRR@6 use the first query
only and the cumulative figure is reported separately for the second query.
Answer generation is not run, and no second planning round is attempted (QP-1D).
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
import uuid
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

MAX_MODEL_CALLS = 20
EXPERIMENT_CAP_CNY = "3"
# Conservative upper bounds so the cap holds even if the invoice exceeds the
# published rate. Twenty short calls stay far below either way.
INPUT_CNY_PER_MTOK = "4"
OUTPUT_CNY_PER_MTOK = "16"

BASELINE_INSTRUCTION = (
    "Interpret the latest turn relative to this research episode and plan public-web queries. "
    "Decide intent from latest_message, NOT from the older episode's unanswered questions. "
    "When active_task_exists=false the episode is a provisional container, not existing research: "
    "an explicit question must be NEW_RESEARCH. A retry without an active task must ABSTAIN. "
    "CONTINUE preserves the original topic; retry/control words are never search subjects. "
    "A different person/name/entity (even a short bare name) is NEW_RESEARCH and saves the old episode. "
    "Do not treat unrelated bare names as a continuation. REFINE can add questions/preferences. "
    "Decompose identity, capabilities/performance, comparison when asked. Preserve all existing RQs on continuation. "
    "Plan 2 or 3 short queries (2-8 meaningful terms), bound each to an RQ; "
    "include one site:OFFICIAL_DOMAIN query with the entity and requested facet, "
    "using a known publisher domain only as a search lead, never evidence or proof. "
    "Do not append generic words official release model documentation to every query. "
    "Prefer precise official release/model docs, "
    "then independent tests for comparisons. Use as_of_date for current information. "
    "Do not silently substitute other versions or infer a named version doesn't exist. "
    "Do not claim knowledge or evidence. "
    "Allowed constraint keys: focus, source_preference, excluded_page_types, persistence. "
)

QUESTIONS: list[dict[str, Any]] = [
    {
        "id": "A01",
        "question": "《崩坏：星穹铁道》当前版本是多少？上下半卡池分别是谁？下一版本已经官宣了什么？",
        "anchors": ["星穹铁道", "崩坏", "卡池", "版本"],
        "focus": ["当前", "上半", "下半", "官宣"],
    },
    {
        "id": "B01",
        "question": "《星铁》黄泉队里的千冶·刃应该用什么遗器？与其他辅助相比有什么优势？",
        "anchors": ["星穹铁道", "星铁", "千冶", "刃", "黄泉"],
        "focus": ["遗器", "配装", "辅助", "优势"],
    },
    {
        "id": "B02",
        "question": "《星铁》虚构叙事中，黄泉队、流萤队、Archer 队哪个更适合自动战斗？",
        "anchors": ["星穹铁道", "星铁", "黄泉", "流萤", "Archer"],
        "focus": ["虚构叙事", "自动战斗", "配队"],
    },
    {
        "id": "C01",
        "question": "《星铁》虚构叙事怎样才能拿满 60000 分？从敌人机制、配队、行动顺序和自动战斗策略分析。",
        "anchors": ["星穹铁道", "星铁", "虚构叙事"],
        "focus": ["60000", "敌人", "配队", "自动战斗"],
    },
    {
        "id": "D01",
        "question": "帮我研究当前《星铁》虚构叙事的配队。",
        "anchors": ["星穹铁道", "星铁", "虚构叙事"],
        "focus": ["配队", "当前"],
    },
    {
        "id": "A04",
        "question": "最近一周有哪些值得关注的开源 AI 模型发布？哪些提供了可下载权重？",
        "anchors": ["开源", "模型"],
        "focus": ["权重", "发布", "一周"],
    },
    {
        "id": "A05",
        "question": "Python 和 Node.js 当前稳定版本分别是多少？近期有哪些重要变化？",
        "anchors": ["Python", "Node.js"],
        "focus": ["稳定版本", "变化"],
    },
    {
        "id": "B04",
        "question": "《异星工厂》《戴森球计划》《幸福工厂》有什么区别？哪个更适合长期单人游玩？",
        "anchors": ["异星工厂", "戴森球计划", "幸福工厂"],
        "focus": ["区别", "单人"],
    },
    {
        "id": "B05",
        "question": "RTX 5060 Laptop 8GB 本地运行 9B 语言模型，Q4、Q5、Q8 哪种更合适？",
        "anchors": ["RTX 5060", "8GB", "9B"],
        "focus": ["Q4", "Q5", "Q8", "显存"],
    },
    {
        "id": "C04",
        "question": "研究轻量化遥感变化检测模型近年来的发展，比较精度、参数量、FLOPs 和实际部署成本。",
        "anchors": ["遥感", "变化检测"],
        "focus": ["参数量", "FLOPs", "精度", "部署"],
    },
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _effective_cap(requested: float) -> str:
    """Never relax a cap the caller already set to something stricter."""

    existing = os.environ.get("LLM_SPEND_CAP_CNY", "").strip()
    if not existing:
        return str(requested)
    try:
        return str(min(requested, float(existing)))
    except ValueError:
        return existing


def _configure_spend_guard(
    ledger_path: Path, *, experiment_id: str, requested_cap_cny: float
) -> None:
    # The enabling flag is never set here: a paid rerun requires an operator who
    # already turned admission on. Everything else uses setdefault so a caller's
    # stricter value (cap, prices, allowed models) survives.
    os.environ["LLM_SPEND_CAP_CNY"] = _effective_cap(requested_cap_cny)
    os.environ["LLM_SPEND_EXPERIMENT_CAP_CNY"] = os.environ["LLM_SPEND_CAP_CNY"]
    os.environ["LLM_SPEND_EXPERIMENT_ID"] = experiment_id
    os.environ.setdefault("LLM_EXPERIMENT_ALLOWED_MODELS", "deepseek-flash")
    os.environ.setdefault("LLM_SPEND_INPUT_CNY_PER_MTOK", INPUT_CNY_PER_MTOK)
    os.environ.setdefault("LLM_SPEND_OUTPUT_CNY_PER_MTOK", OUTPUT_CNY_PER_MTOK)
    os.environ["LLM_SPEND_LEDGER_DB"] = str(ledger_path)


def _relevant(result: dict[str, Any], case: dict[str, Any]) -> bool:
    surface = " ".join(
        str(result.get(key) or "") for key in ("title", "url", "snippet")
    ).casefold()
    anchors = sum(1 for token in case["anchors"] if token.casefold() in surface)
    focus = sum(1 for token in case["focus"] if token.casefold() in surface)
    return anchors >= 2 or (anchors >= 1 and focus >= 1)


def _search_one(gateway, query: str, limit: int) -> dict[str, Any]:
    started = time.monotonic()
    payload = gateway.search_detailed(query, max_results=limit)
    results = [item for item in payload.get("results", []) if item.get("url")]
    return {
        "query": query,
        "status": payload.get("status"),
        "results": results,
        "elapsed": round(time.monotonic() - started, 2),
    }


def _plan(
    make_completion,
    case: dict[str, Any],
    instruction: str,
    calls: list[int],
    *,
    label: str,
) -> dict[str, Any]:
    from src.web import semantic_recovery as sr

    original = sr._TURN_INSTRUCTION
    sr._TURN_INSTRUCTION = instruction
    try:
        if calls[0] >= MAX_MODEL_CALLS:
            raise RuntimeError("model_call_budget_exhausted")
        calls[0] += 1
        episode = sr.ResearchEpisode(
            f"qp1c-{case['id']}",
            "qp1c-thread",
            case["question"],
            [
                {"id": "rq-main", "question": case["question"]},
                {"id": "rq-detail", "question": "关键细节与当期信息"},
            ],
        )
        session = sr.ResearchSemanticSession(
            make_completion(label),
            deadline=time.monotonic() + 60,
            should_cancel=lambda: False,
            # The admission layer identifies a send as operation#round#stage.
            task_identity=lambda stage: f"qp1c-{label}#r1#{stage}",
        )
        decision = session.interpret(episode, case["question"])
        return {
            "queries": [row["query"] for row in decision.proposed_queries][:2],
            "all_queries": [row["query"] for row in decision.proposed_queries],
            "rq_binding": [row["rq_id"] for row in decision.proposed_queries],
            "intent": decision.intent,
        }
    except Exception as exc:  # noqa: BLE001 - recorded, not raised
        return {"error": f"{type(exc).__name__}: {exc}", "queries": []}
    finally:
        sr._TURN_INSTRUCTION = original


def _score_group(gateway, case: dict[str, Any], queries: list[str], limit: int) -> dict[str, Any]:
    searches = [_search_one(gateway, query, limit) for query in queries]
    per_query = []
    for search in searches:
        flags = [_relevant(item, case) for item in search["results"]]
        first = next((index for index, flag in enumerate(flags, start=1) if flag), None)
        per_query.append(
            {
                "query": search["query"],
                "status": search["status"],
                "result_count": len(search["results"]),
                "relevant_count": sum(flags),
                "first_relevant_rank": first,
                "elapsed": search["elapsed"],
            }
        )
        time.sleep(2.0)

    first_row = per_query[0] if per_query else {}
    cumulative_urls: set[str] = set()
    cumulative_relevant = 0
    for search in searches:
        for item in search["results"]:
            url = str(item.get("url") or "")
            if url in cumulative_urls:
                continue
            cumulative_urls.add(url)
            if _relevant(item, case):
                cumulative_relevant += 1
    return {
        "queries": queries,
        "per_query": per_query,
        "hit_at_6": bool(first_row.get("relevant_count")),
        "mrr_at_6": (
            round(1 / first_row["first_relevant_rank"], 3)
            if first_row.get("first_relevant_rank")
            else 0.0
        ),
        "cumulative_results": len(cumulative_urls),
        "cumulative_relevant": cumulative_relevant,
        "elapsed": round(sum(row["elapsed"] for row in per_query), 2),
    }


def _summarise(cases: list[dict[str, Any]], calls: int) -> dict[str, Any]:
    summary: dict[str, Any] = {"model_calls_used": calls, "groups": {}}
    for group in ("A", "B", "C"):
        rows = [case["groups"].get(group, {}) for case in cases]
        summary["groups"][group] = {
            "cases": len(rows),
            "with_results": sum(1 for row in rows if row.get("cumulative_results")),
            "hit_at_6": sum(1 for row in rows if row.get("hit_at_6")),
            "mean_mrr_at_6": round(
                sum(row.get("mrr_at_6", 0.0) for row in rows) / max(1, len(rows)), 3
            ),
            "cumulative_relevant": sum(row.get("cumulative_relevant", 0) for row in rows),
            "mean_elapsed": round(
                sum(row.get("elapsed", 0.0) for row in rows) / max(1, len(rows)), 2
            ),
        }
    retention: dict[str, Any] = {}
    for group in ("B", "C"):
        kept = 0
        for case in cases:
            anchors = next(q["anchors"] for q in QUESTIONS if q["id"] == case["id"])
            text = " ".join(case.get(f"plan_{group.lower()}", {}).get("queries", [])).casefold()
            if any(anchor.casefold() in text for anchor in anchors):
                kept += 1
        retention[group] = round(kept / max(1, len(cases)), 3)
    summary["entity_retention"] = retention
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "docs" / "research_quality" / "QP1C_QUERY_PLANNING_AB.json",
    )
    parser.add_argument("--limit", type=int, default=6)
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument(
        "--live",
        action="store_true",
        help="actually call the model and run searches; without it nothing is sent",
    )
    parser.add_argument(
        "--experiment-id",
        default="",
        help="new, explicit spend-experiment identity for this rerun",
    )
    parser.add_argument(
        "--cap-cny",
        type=float,
        default=0.0,
        help="budget for this rerun; a stricter cap already in the environment wins",
    )
    parser.add_argument(
        "--ledger",
        type=Path,
        default=None,
        help="existing settlement ledger; a paid rerun must point at one explicitly",
    )
    args = parser.parse_args()

    if not args.live:
        print(
            "offline: no model call, no search. A paid rerun needs --live, "
            "--experiment-id, --cap-cny, --ledger, and an environment where "
            "STUDY_AGENT_SETTLEMENT_ADMISSION is already enabled."
        )
        return 0

    load_dotenv(REPO_ROOT / ".env")

    if os.environ.get("STUDY_AGENT_SETTLEMENT_ADMISSION", "").strip().lower() not in {
        "1",
        "true",
        "on",
        "yes",
    }:
        raise SystemExit(
            "refusing paid run: STUDY_AGENT_SETTLEMENT_ADMISSION is not enabled"
        )
    if not args.experiment_id.strip():
        raise SystemExit("refusing paid run: --experiment-id is required")
    if args.cap_cny <= 0:
        raise SystemExit("refusing paid run: --cap-cny must be positive")
    if args.ledger is None:
        raise SystemExit(
            "refusing paid run: --ledger is required so earlier spend stays visible"
        )

    args.ledger.parent.mkdir(parents=True, exist_ok=True)
    _configure_spend_guard(
        args.ledger.resolve(),
        experiment_id=args.experiment_id.strip(),
        requested_cap_cny=args.cap_cny,
    )

    # The settlement ledger lives in a runtime database; a bare file has no
    # settlement tables and the guard refuses to reserve against it.
    from src.infrastructure.sqlite.database import RuntimeDatabase

    RuntimeDatabase(args.ledger.resolve()).initialize()

    from src.application.admitted_chat import admitted_completion_for
    from src.application.spend_admission_factory import build_settlement_admission
    from src.llm_client import get_model_name
    from src.llm_spend_guard import spend_scope
    from src.web import semantic_recovery as sr
    from src.web.semantic_recovery import configured_completion
    from src.web.tool_gateway import GeneralWebGateway

    run_id = uuid.uuid4().hex
    model_name = get_model_name("flash")

    def make_completion(label: str):
        # One admission per operation: the logical quota is per operation, not
        # per run, so a single shared admission caps the whole experiment.
        admission = build_settlement_admission(
            model=model_name,
            kind="research",
            scope_id=f"qp1c-{run_id}-{label}",
            attempts=1,
            ledger_path=str(args.ledger.resolve()),
        )
        if admission is None:
            raise RuntimeError("settlement_admission_disabled")
        return admitted_completion_for(
            configured_completion, admission, estimate_output_tokens=1400
        )

    # Fail closed before any send: this also proves the configuration is complete.
    probe = build_settlement_admission(
        model=model_name,
        kind="research",
        scope_id=f"qp1c-{run_id}-probe",
        attempts=1,
        ledger_path=str(args.ledger.resolve()),
    )
    if probe is None:
        raise SystemExit("settlement admission disabled: refusing to spend")

    gateway = GeneralWebGateway()
    current_instruction = sr._TURN_INSTRUCTION
    calls = [0]
    artifact: dict[str, Any] = {
        "schema_version": "qp1c-query-planning-ab-v1",
        "run_id": run_id,
        "started_at": _utc_now(),
        "budget": {
            "max_model_calls": MAX_MODEL_CALLS,
            "cap_cny": args.cap_cny,
            "experiment_id": args.experiment_id.strip(),
        },
        "pricing_cny_per_mtok": {"input": INPUT_CNY_PER_MTOK, "output": OUTPUT_CNY_PER_MTOK},
        "provider": "auto (SearXNG/bing)",
        "result_limit": args.limit,
        "cases": [],
        "not_measured": ["answer_quality", "evidence_support", "second_planning_round"],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)

    selected = [case for case in QUESTIONS if not args.case or case["id"] in args.case]

    # Every paid call must be bound to this experiment invocation; without a
    # scope the ledger refuses the reservation instead of guessing.
    from contextlib import ExitStack

    stack = ExitStack()
    stack.enter_context(
        spend_scope(
            run_id=run_id,
            operation_id="qp1c",
            experiment=args.experiment_id.strip(),
        )
    )

    for case in selected:
        plan_b = _plan(make_completion, case, BASELINE_INSTRUCTION, calls, label=f"{case['id']}-b")
        plan_c = _plan(
            make_completion,
            case,
            current_instruction,
            calls,
            label=f"{case['id']}-c",
        )
        record: dict[str, Any] = {
            "id": case["id"],
            "question": case["question"],
            "plan_b": plan_b,
            "plan_c": plan_c,
            "groups": {},
        }
        record["groups"]["A"] = _score_group(gateway, case, [case["question"]], args.limit)
        for group, plan in (("B", plan_b), ("C", plan_c)):
            queries = plan.get("queries") or []
            record["groups"][group] = (
                _score_group(gateway, case, queries, args.limit)
                if queries
                else {"queries": [], "error": plan.get("error", "no_queries")}
            )
        artifact["cases"].append(record)
        args.output.write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(
            f"[{case['id']}] calls={calls[0]} "
            f"B={plan_b.get('queries')} C={plan_c.get('queries')}",
            flush=True,
        )

    artifact["completed_at"] = _utc_now()
    stack.close()
    artifact["model_calls_used"] = calls[0]
    artifact["summary"] = _summarise(artifact["cases"], calls[0])
    args.output.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(artifact["summary"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
