"""§162 A3-B0: the transport CLI moves bytes and decides nothing."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/run_release_benchmark_blind_review.py"
RUN_ID = "rq-review-20261001-001"

_VARIANTS = ("wrong_citation", "missing_aspect", "unsupported_claim")

_JUDGMENT = {
    "actual": (("covered", "supported", "supported"), ()),
    "wrong_citation": (("covered", "supported", "gap"), ("wrong_citation",)),
    "missing_aspect": (("partial", "supported", "supported"), ("coverage_gap",)),
    "unsupported_claim": (("covered", "gap", "gap"), ("unsupported_claim",)),
}


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        cwd=ROOT, capture_output=True, text=True, timeout=300,
    )


def _emit(tmp_path: Path) -> Path:
    out = tmp_path / "review"
    result = _run("--emit-packet", "--review-run-id", RUN_ID, "--output", str(out))
    assert result.returncode == 0, result.stderr
    return out


def _response(manifest: dict) -> str:
    rows = []
    for item in manifest["items"]:
        axes, issue_types = _JUDGMENT[item["variant"]]
        rows.append({
            "blind_case_id": item["blind_case_id"],
            "question_coverage": axes[0],
            "evidence_grounding": axes[1],
            "citation_support": axes[2],
            "issues": [
                {"issue_type": issue_type, "reason": "source-bound", "evidence_refs": []}
                for issue_type in issue_types
            ],
        })
    return json.dumps({"review_run_id": RUN_ID, "observations": rows}, ensure_ascii=False)


# ------------------------------------------------------------------- emit

def test_emit_writes_the_three_transport_artifacts(tmp_path):
    out = _emit(tmp_path)
    assert sorted(p.name for p in out.iterdir()) == [
        "ingest_template.json", "packet.txt", "private_manifest.json"
    ]
    manifest = json.loads((out / "private_manifest.json").read_text(encoding="utf-8"))
    assert manifest["review_run_id"] == RUN_ID
    assert manifest["packet_sha256"]
    assert {item["variant"] for item in manifest["items"]} == {
        "actual", "wrong_citation", "missing_aspect", "unsupported_claim"
    }


def _packet_payload(text: str) -> dict:
    body = text.split("INPUT JSON:", 1)[1]
    body = body.rsplit("=== REVIEWER-VISIBLE PACKET END ===", 1)[0]
    return json.loads(body)


def test_packet_file_is_bounded_and_manifest_free(tmp_path):
    out = _emit(tmp_path)
    text = (out / "packet.txt").read_text(encoding="utf-8")
    assert text.count("=== REVIEWER-VISIBLE PACKET BEGIN ===") == 1
    assert text.count("=== REVIEWER-VISIBLE PACKET END ===") == 1
    assert text.index("BEGIN") < text.index("END")
    payload = _packet_payload(text)
    manifest = json.loads((out / "private_manifest.json").read_text(encoding="utf-8"))
    for item in payload["items"]:
        assert not (set(item) & set(_VARIANTS))
        assert not ({str(value) for value in item.values()} & set(_VARIANTS))
    blob = json.dumps(payload["items"], ensure_ascii=False)
    for item in manifest["items"]:
        assert item["case_id"] not in blob
    assert "variant" not in blob
    assert "packet_sha256" not in text


def test_packet_file_does_not_announce_totals(tmp_path):
    out = _emit(tmp_path)
    text = (out / "packet.txt").read_text(encoding="utf-8")
    instructions = text.split("INPUT JSON:", 1)[0].lower()
    for forbidden in ("control", "expected", "specificity", "calibration",
                      "remaining", "total", "balance", "case "):
        assert forbidden not in instructions
    assert not re.search(r"\\b\\d+\\s+(?:items|cases|samples)\\b", instructions)
    payload = _packet_payload(text)
    # No count is announced anywhere in the packet structure either; the frozen
    # source text may legitimately contain words like 'total'.
    assert not ({"count", "total", "item_count", "size"} & set(payload))
    assert "items=" not in text
    assert not re.search(r"\\bcase\\s+\\d+\\s+of\\b", text, re.IGNORECASE)


def test_emit_is_reproducible_for_the_same_frozen_state(tmp_path):
    first = _emit(tmp_path / "a")
    second = _emit(tmp_path / "b")
    assert (first / "packet.txt").read_bytes() == (second / "packet.txt").read_bytes()
    assert (first / "private_manifest.json").read_bytes() == (
        second / "private_manifest.json"
    ).read_bytes()


def test_emit_requires_a_review_run_id(tmp_path):
    result = _run("--emit-packet", "--output", str(tmp_path / "x"))
    assert result.returncode != 0


# ------------------------------------------------------------------ ingest

def _ingest(tmp_path: Path, *, manifest_mutator=None, run_id=RUN_ID, transport=None):
    out = _emit(tmp_path)
    manifest = json.loads((out / "private_manifest.json").read_text(encoding="utf-8"))
    if manifest_mutator is not None:
        manifest = manifest_mutator(manifest)
        (out / "private_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n",
            encoding="utf-8",
        )
    response = out / "reviewer_response.json"
    response.write_text(_response(manifest), encoding="utf-8")
    target = out / "ingested_review.json"
    args = [
        "--ingest", "--review-run-id", run_id, "--response", str(response),
        "--manifest", str(out / "private_manifest.json"), "--output", str(target),
    ]
    if transport is not None:
        args += ["--transport", transport]
    result = _run(*args)
    return out, target, result


def test_ingest_writes_normalized_facts_and_preserves_the_raw_response(tmp_path):
    out, target, result = _ingest(tmp_path)
    assert result.returncode == 0, result.stderr
    artifact = json.loads(target.read_text(encoding="utf-8"))
    assert artifact["calibration_pass"] is True
    assert artifact["eligible_for_authority_review"] is True
    assert artifact["calibration"]["target_detected"] == 6
    assert artifact["calibration"]["specificity_correct"] == 6
    # Transport never crosses into authority.
    assert artifact["qualified_judge"] is False
    assert artifact["formal_semantic_label"] is False
    assert artifact["release_observation"] is False
    assert artifact["release_gate"] == "NO_GO"
    assert "qualification" not in artifact
    # The raw response survives ingest so the parse can be replayed.
    raw = (out / "raw_reviewer_response.txt").read_text(encoding="utf-8")
    assert raw == (out / "reviewer_response.json").read_text(encoding="utf-8")
    assert artifact["output_hash"] == __import__("hashlib").sha256(
        raw.encode("utf-8")
    ).hexdigest()


def test_ingest_records_the_operator_as_transport_not_a_reviewer(tmp_path):
    _, target, result = _ingest(tmp_path)
    assert result.returncode == 0, result.stderr
    artifact = json.loads(target.read_text(encoding="utf-8"))
    assert artifact["transport"] == "manual_copy_paste"
    assert artifact["reviewer"]["reviewer_kind"] == "model"
    assert artifact["reviewer"]["provider"] == "OpenAI"
    assert artifact["reviewer"]["model_family"] == "GPT"
    assert artifact["answer_model_families"] == ["deepseek"]
    assert artifact["invocation_id_kind"] == "harness_assigned_run_id"


def test_ingest_refuses_a_packet_that_no_longer_matches_the_manifest(tmp_path):
    def tamper(manifest):
        manifest["packet_sha256"] = "0" * 64
        return manifest

    _, _, result = _ingest(tmp_path, manifest_mutator=tamper)
    assert result.returncode != 0
    assert "does not match" in (result.stderr + result.stdout)


def test_ingest_refuses_a_manifest_from_another_run(tmp_path):
    _, _, result = _ingest(tmp_path, run_id="rq-review-20261001-999")
    assert result.returncode != 0
    assert "different review run" in (result.stderr + result.stdout)


def test_ingest_requires_response_and_manifest(tmp_path):
    result = _run("--ingest", "--review-run-id", RUN_ID, "--output", str(tmp_path / "x"))
    assert result.returncode != 0


def test_emit_and_ingest_are_mutually_exclusive(tmp_path):
    result = _run(
        "--emit-packet", "--ingest", "--review-run-id", RUN_ID,
        "--output", str(tmp_path / "x"),
    )
    assert result.returncode != 0


@pytest.mark.parametrize("mode", ["--emit-packet", "--ingest"])
def test_cli_never_prints_a_qualification_verdict(tmp_path, mode):
    if mode == "--emit-packet":
        out = _emit(tmp_path)
        text = (out / "packet.txt").read_text(encoding="utf-8")
        assert "GRANTED" not in text
        return
    _, _, result = _ingest(tmp_path)
    assert "GRANTED" not in result.stdout
    assert "qualified_judge=False" in result.stdout
