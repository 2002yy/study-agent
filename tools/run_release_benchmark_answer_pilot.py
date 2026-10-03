"""Generate diagnostic answers for the two reviewed frozen text/PDF cases."""

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
from src.evals.release_benchmark_answer_pilot import generate_frozen_answer  # noqa: E402
from src.evals.release_benchmark_plan import load_release_benchmark_plan  # noqa: E402
from src.evals.release_benchmark_registry import load_gold, load_registry  # noqa: E402

FIXTURES = ROOT / "tests/fixtures/release_benchmark"


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--provider", choices=("deepseek", "openai", "openrouter",
                                                "siliconflow"), default="deepseek")
    parser.add_argument("--model-profile", choices=("flash", "pro"), default="flash")
    args = parser.parse_args()
    if subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT,
        text=True, encoding="utf-8", timeout=10,
    ).strip():
        parser.error("answer pilot requires a clean tracked worktree")
    code_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT,
        text=True, encoding="utf-8", timeout=10,
    ).strip()
    plan = load_release_benchmark_plan(FIXTURES / "plan_v1.json")
    registry = load_registry(FIXTURES / "registry_v1.json", ROOT, plan)
    gold = load_gold(FIXTURES / "gold_v1.json", registry)
    reviewed = {review.case_id for review in gold.reviews if review.structurally_reviewed}
    cases = [case for case in registry.cases if case.case_id in reviewed
             and case.mode == "frozen" and case.modality in {"text", "pdf"}]
    model = llm_client.get_model_name(args.model_profile, args.provider)
    _, extra_body = llm_client.research_structured_output_capabilities(args.provider)

    def model_call(messages: list[dict[str, str]]) -> str:
        return llm_client.chat(
            messages, temperature=0, model_profile=args.model_profile,
            provider_profile=args.provider, max_tokens=800, timeout=45,
            response_format="json_object", request_max_retries=0,
            extra_body=extra_body, task_name="release_benchmark_answer",
        )

    # Write only after both calls pass strict parsing. No partial artifact can
    # be mistaken for a complete two-case answer run.
    results = [generate_frozen_answer(case, ROOT, model_call=model_call,
                                      provider=args.provider, model=model,
                                      code_sha=code_sha)
               for case in cases]
    artifact = {"schema_version": "release-benchmark-answer-pilot-bundle-v1",
                "code_sha": code_sha, "plan_digest": registry.plan_digest,
                "registry_digest": registry.digest, "gold_digest": gold.digest,
                "inference_network": "remote_model_api", "release_gate": "NO_GO",
                "cases": results}
    data = _json_bytes(artifact)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    path = args.output_dir / "answer_bundle.json"
    path.write_bytes(data)
    print(json.dumps({"code_sha": code_sha, "case_count": len(results),
                      "answer_bundle_sha256": sha256(data).hexdigest(),
                      "semantic_assessment": "pending_external_adjudication",
                      "release_gate": "NO_GO", "output": str(path.resolve())},
                     ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
