"""Replay a saved semantic probe and write a diagnostic-only calibration."""

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

from src.evals.release_benchmark_answer_pilot import build_answer_review_packet  # noqa: E402
from src.evals.release_benchmark_plan import load_release_benchmark_plan  # noqa: E402
from src.evals.release_benchmark_registry import load_gold, load_registry  # noqa: E402
from src.evals.release_benchmark_semantic_calibration import (  # noqa: E402
    calibrate_semantic_probe,
)

FIXTURES = ROOT / "tests/fixtures/release_benchmark"


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def _canonical(path: Path) -> dict[str, object]:
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict) or raw != _json_bytes(value):
        raise ValueError(f"noncanonical artifact: {path}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--answer-bundle", required=True, type=Path)
    parser.add_argument("--review-packet", required=True, type=Path)
    parser.add_argument("--semantic-probe", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    if subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT,
        text=True, encoding="utf-8", timeout=10,
    ).strip():
        parser.error("semantic calibration requires a clean tracked worktree")
    code_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT,
        text=True, encoding="utf-8", timeout=10,
    ).strip()
    plan = load_release_benchmark_plan(FIXTURES / "plan_v1.json")
    registry = load_registry(FIXTURES / "registry_v1.json", ROOT, plan)
    gold = load_gold(FIXTURES / "gold_v1.json", registry)
    bundle = _canonical(args.answer_bundle)
    packet = build_answer_review_packet(bundle, registry, gold, ROOT)
    if args.review_packet.read_bytes() != _json_bytes(packet):
        parser.error("review packet differs from verified answer bundle")
    probe = _canonical(args.semantic_probe)
    report = calibrate_semantic_probe(
        bundle, probe, registry, gold, ROOT, calibration_code_sha=code_sha,
    )
    args.output_dir.mkdir(parents=True, exist_ok=False)
    data = _json_bytes(report)
    output = args.output_dir / "semantic_calibration.json"
    output.write_bytes(data)
    print(json.dumps({
        "calibration_code_sha": code_sha,
        "answer_bundle_sha256": report["answer_bundle_sha256"],
        "probe_sha256": report["probe_sha256"],
        "calibration_sha256": sha256(data).hexdigest(),
        "target_controls_detected": report["target_controls_detected"],
        "specific_controls_passed": report["specific_controls_passed"],
        "controls_total": report["controls_total"],
        "specificity_gate": report["specificity_gate"],
        "qualified_judge": False,
        "formal_semantic_label": False,
        "release_gate": "NO_GO", "output": str(output.resolve()),
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
