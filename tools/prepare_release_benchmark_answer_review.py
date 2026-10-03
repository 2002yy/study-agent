"""Verify a frozen answer diagnostic and prepare its semantic review packet."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evals.release_benchmark_answer_pilot import build_answer_review_packet  # noqa: E402
from src.evals.release_benchmark_plan import load_release_benchmark_plan  # noqa: E402
from src.evals.release_benchmark_registry import load_gold, load_registry  # noqa: E402

FIXTURES = ROOT / "tests/fixtures/release_benchmark"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--answer-bundle", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    plan = load_release_benchmark_plan(FIXTURES / "plan_v1.json")
    registry = load_registry(FIXTURES / "registry_v1.json", ROOT, plan)
    gold = load_gold(FIXTURES / "gold_v1.json", registry)
    raw = args.answer_bundle.read_bytes()
    bundle = json.loads(raw)
    packet = build_answer_review_packet(bundle, registry, gold, ROOT)
    canonical = (json.dumps(bundle, ensure_ascii=False, sort_keys=True,
                            separators=(",", ":")) + "\n").encode("utf-8")
    if raw != canonical:
        parser.error("answer bundle bytes are not canonical")
    if args.output.exists():
        parser.error("review packet output already exists")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes((json.dumps(packet, ensure_ascii=False, sort_keys=True,
                                        separators=(",", ":")) + "\n").encode("utf-8"))
    print(json.dumps({"answer_bundle_sha256": packet["answer_bundle_sha256"],
                      "case_count": len(packet["cases"]),
                      "semantic_assessment": packet["semantic_assessment"],
                      "release_gate": packet["release_gate"],
                      "output": str(args.output.resolve())},
                     ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
