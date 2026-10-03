"""Record the approved frozen reader pilots and produce a bounded score report."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evals.release_benchmark_plan import load_release_benchmark_plan  # noqa: E402
from src.evals.release_benchmark_recorded_pilot import (  # noqa: E402
    BUNDLE_SCHEMA,
    build_frozen_pilot_observation,
)
from src.evals.release_benchmark_registry import load_gold, load_registry  # noqa: E402
from src.evals.release_benchmark_replay import (  # noqa: E402
    run_frozen_mixed_pilot,
    run_frozen_pdf_pilot,
    run_frozen_text_pilot,
    run_frozen_visual_pilot,
)
from src.evals.release_benchmark_scoring import (  # noqa: E402
    parse_recording,
    score_recordings,
)

FIXTURES = ROOT / "tests/fixtures/release_benchmark"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT,
        text=True, encoding="utf-8", timeout=10,
    ).strip():
        parser.error("recorded pilot requires a clean tracked worktree")
    code_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT,
        text=True, encoding="utf-8", timeout=10,
    ).strip()
    plan = load_release_benchmark_plan(FIXTURES / "plan_v1.json")
    registry = load_registry(FIXTURES / "registry_v1.json", ROOT, plan)
    gold = load_gold(FIXTURES / "gold_v1.json", registry)
    reviewed = {review.case_id for review in gold.reviews if review.structurally_reviewed}
    cases = [case for case in registry.cases
             if case.mode == "frozen" and case.case_id in reviewed]
    if not cases:
        parser.error("no approved frozen cases are available")
    dispatch = {
        "text": run_frozen_text_pilot,
        "pdf": run_frozen_pdf_pilot,
        "image": run_frozen_visual_pilot,
        "chart": run_frozen_visual_pilot,
        "mixed": run_frozen_mixed_pilot,
    }
    started_at = _utc_now()
    pilots = []
    for case in cases:
        result = dispatch[case.modality](case, ROOT)
        pilots.append({"case_id": case.case_id,
                       "observed_at": _utc_now(), "result": result})
    bundle = {
        "schema_version": BUNDLE_SCHEMA,
        "code_sha": code_sha,
        "started_at": started_at,
        "ended_at": _utc_now(),
        "pilots": pilots,
    }
    bundle_bytes = _json_bytes(bundle)
    observation = build_frozen_pilot_observation(
        plan, registry, gold, code_sha=code_sha, bundle=bundle,
        transcript_sha256=sha256(bundle_bytes).hexdigest(),
    )
    recording = parse_recording(observation, plan, registry, gold, code_sha)
    score = score_recordings(plan, registry, gold, (recording,))
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / "pilot_bundle.json").write_bytes(bundle_bytes)
    (args.output_dir / "observation.json").write_bytes(_json_bytes(observation))
    (args.output_dir / "score.json").write_bytes(_json_bytes(score))
    print(json.dumps({
        "code_sha": code_sha,
        "pilot_transcript_sha256": sha256(bundle_bytes).hexdigest(),
        "frozen_observations": len(observation["cases"]),
        "missing_observations": score["missing_observations"],
        "admitted_release_cases": score["admitted_release_cases"],
        "release_gate": score["release_gate"],
        "output_dir": str(args.output_dir.resolve()),
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
