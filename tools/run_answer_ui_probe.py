"""Bounded live-provider prompt A/B; never claims publication or product latency.

Uses the production TypeScript parser to replay actual text chunks. Does not
write sessions, call search, or enable a research publication authority.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
NODE_BRIDGE = r"""
import fs from 'node:fs';
import { createRequire } from 'node:module';
const require = createRequire(process.cwd() + '/frontend/package.json');
const ts = require('typescript');
const source = fs.readFileSync('frontend/src/features/answer-ui/answerUiProtocol.ts', 'utf8');
const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
const protocol = await import('data:text/javascript;base64,' + Buffer.from(js).toString('base64'));
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
if (input.prompt) console.log(JSON.stringify({ prompt: protocol.ANSWER_UI_CONTEXT }));
else {
  let content = '', firstCard = null;
  for (const chunk of input.chunks) {
    content += chunk.text;
    if (firstCard === null && protocol.splitAnswerContent(content, true).some(p => p.kind === 'card')) firstCard = chunk.seconds;
  }
  const parts = protocol.splitAnswerContent(content);
  const cards = parts.filter(p => p.kind === 'card').map(p => p.card.type);
  console.log(JSON.stringify({ first_card_seconds: firstCard, card_types: cards,
    cards: parts.filter(p => p.kind === 'card').map(p => p.card),
    rejected_fence: parts.some(p => p.kind === 'markdown' && /```study-ui|~~~study-ui/.test(p.content)) }));
}
"""

CASES = (
    ("simple", "Java 中 null 表示什么？请用一句话说明。", False),
    (
        "java_references",
        '用一个可操作的 Java 引用实验解释 Student a = new Student("甲"); '
        "Student b = a; 修改 b.name 和给 b 重新赋值有何区别。"
        "我要能按按钮对比引用和对象的变化，简洁说明。",
        True,
    ),
)


def bridge(payload: dict[str, Any]) -> dict[str, Any]:
    result = subprocess.run(
        ["node", "--input-type=module", "-e", NODE_BRIDGE],
        input=json.dumps(payload),
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
        cwd=ROOT,
        timeout=20,
    )
    return json.loads(result.stdout)


def percentile(values: list[float], proportion: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * proportion
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return round(
        ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower), 3
    )


def summarize(trials: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for arm in ("text_baseline", "ui_context"):
        rows = [row for row in trials if row["arm"] == arm]
        metrics: dict[str, Any] = {
            "samples": len(rows),
            "errors": sum("error" in r for r in rows),
        }
        for key in ("first_token_seconds", "first_card_seconds", "complete_seconds"):
            values = [
                r[key]
                for r in rows
                if "error" not in r and isinstance(r.get(key), (float, int))
            ]
            metrics[key] = {
                "n": len(values),
                "p50": percentile(values, 0.5),
                "p95": percentile(values, 0.95),
            }
        result[arm] = metrics
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3, choices=range(1, 6))
    parser.add_argument("--timeout", type=float, default=45)
    parser.add_argument(
        "--replay", type=Path, help="Re-evaluate saved chunks without provider requests"
    )
    args = parser.parse_args()
    if args.replay:
        report = json.loads(args.replay.read_text(encoding="utf-8"))
        for row in report["trials"]:
            if "error" not in row:
                row.update(bridge({"chunks": row["chunks"]}))
                row["empty_reply"] = not row["chunks"]
                row["selection_matches_request"] = (
                    not row["empty_reply"]
                    and not row["rejected_fence"]
                    and bool(row["card_types"]) == row["expects_card"]
                )
        report["summary"] = summarize(report["trials"])
        report["by_case"] = {
            name: summarize([r for r in report["trials"] if r["case"] == name])
            for name, _, _ in CASES
        }
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return
    # Imports stay lazy so deterministic reporting tests never open a provider.
    import sys

    sys.path.insert(0, str(ROOT))
    from dotenv import load_dotenv

    load_dotenv(args.env, override=False)
    from src.llm_client import get_model_name, get_provider_settings, stream_chat

    settings = get_provider_settings()
    prompt = bridge({"prompt": True})["prompt"]
    trials: list[dict[str, Any]] = []
    for repeat in range(args.repeats):
        for case, question, expects_card in CASES:
            # Alternate arm order to reduce a fixed warm-up/order bias.
            arms = (
                ("text_baseline", "ui_context")
                if repeat % 2 == 0
                else ("ui_context", "text_baseline")
            )
            for arm in arms:
                system = "你是学习助手。用中文简洁准确地回答，不虚构来源。"
                if arm == "ui_context":
                    system += "\n\n" + prompt
                row: dict[str, Any] = {
                    "case": case,
                    "repeat": repeat,
                    "arm": arm,
                    "expects_card": expects_card,
                    "ttuv_seconds": None,
                }
                chunks: list[dict[str, Any]] = []
                started = time.monotonic()
                try:
                    for text in stream_chat(
                        [
                            {"role": "system", "content": system},
                            {"role": "user", "content": question},
                        ],
                        model_profile="flash",
                        temperature=0,
                        max_tokens=1000,
                        timeout=args.timeout,
                        request_max_retries=0,
                        extra_body={"thinking": {"type": "disabled"}}
                        if settings.research_disable_thinking
                        else None,
                    ):
                        elapsed = time.monotonic() - started
                        chunks.append({"text": text, "seconds": elapsed})
                        row.setdefault("first_token_seconds", elapsed)
                    row["complete_seconds"] = time.monotonic() - started
                    row.update(bridge({"chunks": chunks}))
                    row["empty_reply"] = not chunks
                    row["selection_matches_request"] = (
                        not row["empty_reply"]
                        and not row["rejected_fence"]
                        and bool(row["card_types"]) == expects_card
                    )
                except Exception as exc:
                    # No raw exception/provider URLs/credentials in artifacts.
                    row["error"] = type(exc).__name__
                    row["elapsed_seconds"] = time.monotonic() - started
                row["chunks"] = chunks
                trials.append(row)
                report = {
                    "scope": "direct-provider prompt pilot, not chat/research/browser A/B",
                    "provider": settings.profile_name,
                    "model": get_model_name("flash"),
                    "ui_head": subprocess.check_output(
                        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
                    ).strip(),
                    "ttuv_status": "not measured: no verified research publication in this probe",
                    "qualification": "exploratory; small samples; no product speed claim",
                    "trials": trials,
                    "summary": summarize(trials),
                    "by_case": {
                        name: summarize([r for r in trials if r["case"] == name])
                        for name, _, _ in CASES
                    },
                }
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(
                    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                print(
                    json.dumps(
                        {k: v for k, v in row.items() if k != "chunks"},
                        ensure_ascii=False,
                    ),
                    flush=True,
                )


if __name__ == "__main__":
    main()
