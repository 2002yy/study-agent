"""Score a fresh frozen-source run with disclosed remote answer inference."""

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

from src.evals.release_benchmark_plan import load_release_benchmark_plan  # noqa: E402
from src.evals.release_benchmark_registry import load_gold, load_registry  # noqa: E402
from src.evals.release_benchmark_remote_observation import (  # noqa: E402
    build_remote_answer_observation,
)
from src.evals.release_benchmark_scoring import (  # noqa: E402
    parse_recording,
    score_recordings,
)

FIXTURES = ROOT / "tests/fixtures/release_benchmark"


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--answer-bundle", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    if subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT,
        text=True, encoding="utf-8", timeout=10,
    ).strip():
        parser.error("remote observation requires a clean tracked worktree")
    code_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT,
        text=True, encoding="utf-8", timeout=10,
    ).strip()
    raw_bundle = args.answer_bundle.read_bytes()
    bundle = json.loads(raw_bundle)
    if raw_bundle != _json_bytes(bundle):
        parser.error("answer bundle bytes are not canonical")
    plan = load_release_benchmark_plan(FIXTURES / "plan_v1.json")
    registry = load_registry(FIXTURES / "registry_v1.json", ROOT, plan)
    gold = load_gold(FIXTURES / "gold_v1.json", registry)
    observation = build_remote_answer_observation(
        plan, registry, gold, ROOT, bundle=bundle, expected_code_sha=code_sha,
    )
    recording = parse_recording(observation, plan, registry, gold, code_sha)
    score = score_recordings(plan, registry, gold, (recording,))
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / "observation.json").write_bytes(_json_bytes(observation))
    (args.output_dir / "score.json").write_bytes(_json_bytes(score))
    print(json.dumps({
        "code_sha": code_sha,
        "answer_bundle_sha256": sha256(raw_bundle).hexdigest(),
        "completed_cases": sum(row["state"] == "completed" for row in score["cases"]),
        "missing_observations": score["missing_observations"],
        "semantic_labels_observed": sum(
            label["state"] == "observed" and name in {
                "question_coverage", "evidence_grounding", "citation_support",
                "answer_utility",
            }
            for row in score["cases"] for name, label in row["metrics"].items()
        ),
        "release_gate": score["release_gate"],
        "output_dir": str(args.output_dir.resolve()),
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
