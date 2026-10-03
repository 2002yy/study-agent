"""§162 A3-B0: operator transport between the repo and an isolated reviewer.

Two mutually exclusive modes:

  --emit-packet   write the reviewer-visible packet, the repository-only
                  manifest, and a fill-in template into an output directory;
  --ingest        validate a returned raw response against the frozen manifest
                  and write the normalized calibration facts.

This is transport only. It adds no reviewer semantics, no calibration rule and
no authority: it never grants a judge and never produces a semantic label, and
it re-derives everything from the library contract instead of re-assembling
rubrics or sources here. The operator moves bytes; the operator is not a
reviewer.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evals.release_benchmark_blind_review import (  # noqa: E402
    TRANSPORT_MANUAL_COPY_PASTE,
    build_blind_review_packet,
    build_holdout_packet,
    ingest_holdout_review_run,
    ingest_review_run,
    render_packet_text,
)
from src.evals.release_benchmark_plan import load_release_benchmark_plan  # noqa: E402
from src.evals.release_benchmark_registry import load_gold, load_registry  # noqa: E402
from src.evals.release_benchmark_reviewer_qualification import (  # noqa: E402
    make_identity,
)
from src.evals.release_benchmark_semantic_probe import (  # noqa: E402
    materialize_review_items,
)

FIXTURES = ROOT / "tests/fixtures/release_benchmark"
DEFAULT_BUNDLE = (ROOT / "docs/research_quality/"
                  "RELEASE_BENCHMARK_REMOTE_OBSERVATION_2026-09-29/answer_bundle.json")
DEFAULT_COMPOSITE = (ROOT / "tests/fixtures/release_benchmark/"
                     "qualification_holdout_v1.json")

BOUNDARY_BEGIN = "=== REVIEWER-VISIBLE PACKET BEGIN ==="
BOUNDARY_END = "=== REVIEWER-VISIBLE PACKET END ==="


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def _load_frozen(bundle_path: Path) -> dict[str, object]:
    plan = load_release_benchmark_plan(FIXTURES / "plan_v1.json")
    registry = load_registry(FIXTURES / "registry_v1.json", ROOT, plan)
    gold = load_gold(FIXTURES / "gold_v1.json", registry)
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    return materialize_review_items(bundle, registry, gold, ROOT)


def _build(bundle_path: Path, review_run_id: str) -> dict[str, object]:
    return build_blind_review_packet(
        _load_frozen(bundle_path),
        review_run_id=review_run_id,
        answer_bundle_sha256=sha256(bundle_path.read_bytes()).hexdigest(),
        registry_sha256=sha256((FIXTURES / "registry_v1.json").read_bytes()).hexdigest(),
        gold_sha256=sha256((FIXTURES / "gold_v1.json").read_bytes()).hexdigest(),
    )


def _emit_packet(bundle_path: Path, review_run_id: str, out_dir: Path) -> None:
    built = _build(bundle_path, review_run_id)
    packet = built["packet"]
    manifest = built["manifest"]
    assert isinstance(packet, dict) and isinstance(manifest, dict)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Only the bounded block may leave the repository.
    packet_text = (
        f"{BOUNDARY_BEGIN}\n"
        f"{render_packet_text(packet)}"
        f"{BOUNDARY_END}\n"
    )
    (out_dir / "packet.txt").write_text(packet_text, encoding="utf-8")
    (out_dir / "private_manifest.json").write_bytes(_json_bytes(manifest))
    template = {
        "review_run_id": review_run_id,
        "observations": [
            {
                "blind_case_id": item["blind_case_id"],
                "question_coverage": "",
                "evidence_grounding": "",
                "citation_support": "",
                "issues": [],
            }
            for item in packet["items"]
        ],
    }
    (out_dir / "ingest_template.json").write_bytes(_json_bytes(template))
    print(f"packet_sha256={manifest['packet_sha256']}")
    print(f"input_manifest_hash={packet['input_manifest_hash']}")
    print(f"items={len(packet['items'])}")
    print(f"wrote packet.txt, private_manifest.json, ingest_template.json to {out_dir}")


def _ingest(
    bundle_path: Path, review_run_id: str, response_path: Path,
    manifest_path: Path, out_path: Path, *, provider: str, model_family: str,
    model_id: str, revision: str, invocation_id: str, timestamp: str,
    transport: str,
) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("manifest is not an object")
    if manifest.get("review_run_id") != review_run_id:
        raise ValueError("manifest belongs to a different review run")
    built = _build(bundle_path, review_run_id)
    packet = built["packet"]
    assert isinstance(packet, dict)
    if manifest.get("packet_sha256") != built["manifest"]["packet_sha256"]:
        raise ValueError("frozen packet does not match the recorded manifest")
    raw_bytes = response_path.read_bytes()
    raw = raw_bytes.decode("utf-8")
    materialized = _load_frozen(bundle_path)
    families = sorted({str(case["answer_provider"])
                       for case in materialized["cases"]})  # type: ignore[index]
    artifact = ingest_review_run(
        packet=packet,
        manifest=manifest,
        raw_response_text=raw,
        reviewer_identity=make_identity(
            reviewer_kind="model",
            provider=provider,
            model_family=model_family,
            model_id=model_id,
            revision=revision,
        ),
        invocation_id=invocation_id,
        timestamp=timestamp,
        answer_model_families=families,
        transport=transport,
        raw_response_bytes=raw_bytes,
    )
    # Transport never decides qualification.
    if artifact.get("qualified_judge") is not False:
        raise ValueError("transport artifact must not carry a granted judge")
    if "qualification" in artifact:
        raise ValueError("transport artifact must not carry a qualification decision")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # The raw response is preserved beside the normalized artifact so the
    # parse can always be replayed instead of trusted.
    raw_copy = out_path.with_name("raw_reviewer_response.txt")
    # Byte-for-byte, so the parse can be replayed against the original payload.
    raw_copy.write_bytes(raw_bytes)
    out_path.write_bytes(_json_bytes(artifact))
    print(f"output_hash={artifact['output_hash']}")
    print(f"calibration_pass={artifact['calibration_pass']}")
    print(f"eligible_for_authority_review={artifact['eligible_for_authority_review']}")
    print("qualified_judge=False formal_semantic_label=False release_gate=NO_GO")
    print(f"wrote {out_path.name} and {raw_copy.name} to {out_path.parent}")


def _build_holdout(composite_path: Path, review_run_id: str) -> dict[str, object]:
    composite = json.loads(composite_path.read_text(encoding="utf-8"))
    return build_holdout_packet(
        composite=composite, root=ROOT, review_run_id=review_run_id
    )


def _emit_holdout_packet(composite_path: Path, review_run_id: str, out_dir: Path) -> None:
    built = _build_holdout(composite_path, review_run_id)
    packet = built["packet"]
    manifest = built["manifest"]
    assert isinstance(packet, dict) and isinstance(manifest, dict)
    out_dir.mkdir(parents=True, exist_ok=True)
    packet_text = (
        f"{BOUNDARY_BEGIN}\n"
        f"{render_packet_text(packet)}"
        f"{BOUNDARY_END}\n"
    )
    (out_dir / "packet.txt").write_text(packet_text, encoding="utf-8")
    (out_dir / "private_manifest.json").write_bytes(_json_bytes(manifest))
    template = {
        "review_run_id": review_run_id,
        "observations": [
            {
                "blind_case_id": item["blind_case_id"],
                "question_coverage": "",
                "evidence_grounding": "",
                "citation_support": "",
                "issues": [],
            }
            for item in packet["items"]
        ],
    }
    (out_dir / "ingest_template.json").write_bytes(_json_bytes(template))
    print(f"packet_sha256={manifest['packet_sha256']}")
    print(f"input_manifest_hash={packet['input_manifest_hash']}")
    print(f"items={len(packet['items'])}")
    print(f"wrote packet.txt, private_manifest.json, ingest_template.json to {out_dir}")


def _ingest_holdout(
    composite_path: Path, review_run_id: str, response_path: Path,
    manifest_path: Path, out_path: Path, *, provider: str, model_family: str,
    model_id: str, revision: str, invocation_id: str, timestamp: str,
    transport: str, answer_model_families: list[str],
) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("manifest is not an object")
    if manifest.get("review_run_id") != review_run_id:
        raise ValueError("manifest belongs to a different review run")
    built = _build_holdout(composite_path, review_run_id)
    packet = built["packet"]
    assert isinstance(packet, dict)
    if manifest.get("packet_sha256") != built["manifest"]["packet_sha256"]:
        raise ValueError("frozen packet does not match the recorded manifest")
    raw_bytes = response_path.read_bytes()
    raw = raw_bytes.decode("utf-8")
    artifact = ingest_holdout_review_run(
        packet=packet,
        manifest=manifest,
        raw_response_text=raw,
        reviewer_identity=make_identity(
            reviewer_kind="model",
            provider=provider,
            model_family=model_family,
            model_id=model_id,
            revision=revision,
        ),
        invocation_id=invocation_id,
        timestamp=timestamp,
        answer_model_families=tuple(answer_model_families),
        transport=transport,
        raw_response_bytes=raw_bytes,
    )
    if artifact.get("qualified_judge") is not False:
        raise ValueError("transport artifact must not carry a granted judge")
    if "qualification" in artifact:
        raise ValueError("transport artifact must not carry a qualification decision")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    raw_copy = out_path.with_name("raw_reviewer_response.txt")
    raw_copy.write_bytes(raw_bytes)
    out_path.write_bytes(_json_bytes(artifact))
    print(f"output_hash={artifact['output_hash']}")
    for cluster_id, result in sorted(
        artifact["cluster_results"].items()  # type: ignore[union-attr]
    ):
        print(f"  {cluster_id}: target={result['target_detected']}/{result['target_total']} "
              f"specificity={result['specificity_correct']}/{result['specificity_total']} "
              f"pass={result['cluster_pass']}")
    print(f"overall_pass={artifact['overall_pass']}")
    print(f"eligible_for_authority_review={artifact['eligible_for_authority_review']}")
    print("qualified_judge=False formal_semantic_label=False release_gate=NO_GO")
    print(f"wrote {out_path.name} and {raw_copy.name} to {out_path.parent}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--emit-packet", action="store_true")
    mode.add_argument("--ingest", action="store_true")
    mode.add_argument("--emit-holdout-packet", action="store_true")
    mode.add_argument("--ingest-holdout", action="store_true")
    parser.add_argument("--review-run-id", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--bundle", default=str(DEFAULT_BUNDLE))
    parser.add_argument("--composite", default=str(DEFAULT_COMPOSITE))
    parser.add_argument("--answer-model-family", action="append", default=None)
    parser.add_argument("--response")
    parser.add_argument("--manifest")
    parser.add_argument("--provider", default="OpenAI")
    parser.add_argument("--model-family", default="GPT")
    parser.add_argument("--model-id", default="gpt-5.6-sol")
    parser.add_argument("--revision", default="2026-10")
    parser.add_argument("--invocation-id")
    parser.add_argument("--timestamp")
    parser.add_argument("--transport", default=TRANSPORT_MANUAL_COPY_PASTE)
    args = parser.parse_args()

    bundle_path = Path(args.bundle)
    composite_path = Path(args.composite)
    families = args.answer_model_family or ["deepseek"]
    if args.emit_packet:
        _emit_packet(bundle_path, args.review_run_id, Path(args.output))
        return
    if args.emit_holdout_packet:
        _emit_holdout_packet(composite_path, args.review_run_id, Path(args.output))
        return

    if not args.response or not args.manifest:
        parser.error("--ingest requires --response and --manifest")
    timestamp = args.timestamp or datetime.now(timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )
    if args.ingest_holdout:
        _ingest_holdout(
            composite_path, args.review_run_id, Path(args.response),
            Path(args.manifest), Path(args.output), provider=args.provider,
            model_family=args.model_family, model_id=args.model_id,
            revision=args.revision,
            invocation_id=args.invocation_id or args.review_run_id,
            timestamp=timestamp, transport=args.transport,
            answer_model_families=families,
        )
        return
    _ingest(
        bundle_path, args.review_run_id, Path(args.response), Path(args.manifest),
        Path(args.output), provider=args.provider, model_family=args.model_family,
        model_id=args.model_id, revision=args.revision,
        invocation_id=args.invocation_id or args.review_run_id,
        timestamp=timestamp, transport=args.transport,
    )


if __name__ == "__main__":
    main()
