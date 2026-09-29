"""Run DeepSeek pro diagnostic review on frozen-source answer captures."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import llm_client  # noqa: E402
from src.evals.release_benchmark_answer_pilot import build_answer_review_packet  # noqa: E402
from src.evals.release_benchmark_plan import load_release_benchmark_plan  # noqa: E402
from src.evals.release_benchmark_registry import load_gold, load_registry  # noqa: E402
from src.evals.release_benchmark_semantic_probe import run_semantic_probe  # noqa: E402

FIXTURES = ROOT / "tests/fixtures/release_benchmark"


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--answer-bundle", required=True, type=Path)
    parser.add_argument("--review-packet", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    if subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT,
        text=True, encoding="utf-8", timeout=10,
    ).strip():
        parser.error("semantic probe requires a clean tracked worktree")
    code_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT,
        text=True, encoding="utf-8", timeout=10,
    ).strip()
    plan = load_release_benchmark_plan(FIXTURES / "plan_v1.json")
    registry = load_registry(FIXTURES / "registry_v1.json", ROOT, plan)
    gold = load_gold(FIXTURES / "gold_v1.json", registry)
    raw_bundle = args.answer_bundle.read_bytes()
    bundle = json.loads(raw_bundle)
    if raw_bundle != _json_bytes(bundle):
        parser.error("answer bundle bytes are not canonical")
    packet = build_answer_review_packet(bundle, registry, gold, ROOT)
    if args.review_packet.read_bytes() != _json_bytes(packet):
        parser.error("review packet does not match answer bundle")
    provider, model_profile = "deepseek", "pro"
    model = llm_client.get_model_name(model_profile, provider)
    _, extra_body = llm_client.research_structured_output_capabilities(provider)

    def model_call(messages: list[dict[str, str]]) -> str:
        return llm_client.chat(
            messages, temperature=0, model_profile=model_profile,
            provider_profile=provider, max_tokens=700, timeout=45,
            response_format="json_object", request_max_retries=0,
            extra_body=extra_body, task_name="release_benchmark_semantic_probe",
        )

    result = run_semantic_probe(
        bundle, registry, gold, ROOT, code_sha=code_sha,
        reviewer_provider=provider, reviewer_model=model, model_call=model_call,
    )
    data = _json_bytes(result)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    output = args.output_dir / "semantic_probe.json"
    output.write_bytes(data)
    print(json.dumps({
        "review_code_sha": code_sha,
        "answer_bundle_sha256": result["answer_bundle_sha256"],
        "probe_sha256": sha256(data).hexdigest(),
        "case_count": len(result["cases"]),
        "all_controls_detected": result["all_controls_detected"],
        "all_dimensions_consistent": result["all_dimensions_consistent"],
        "formal_semantic_label": False,
        "release_gate": "NO_GO",
        "output": str(output.resolve()),
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
