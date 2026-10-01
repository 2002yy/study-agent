"""§162 A3-D: the qualification holdout is fresh, frozen and provable.

This fixture replaces the consumed §161 calibration set for qualification
selection. These tests pin the properties that make it usable for that: it links
to a byte-frozen source, its expectations cannot drift from the shared control
table, it carries the structure that discriminated the previous reviewer, and it
does not overlap the consumed set.
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re

import pytest

from src.evals.release_benchmark_semantic_controls import (
    AXES,
    control_expectation,
    evaluate_clean_answer,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/release_benchmark"
HOLDOUT = FIXTURES / "holdout_v1.json"
REGISTRY = FIXTURES / "registry_v1.json"

CONSUMED_ANSWERS = (
    ROOT / "docs/research_quality/"
    "RELEASE_BENCHMARK_REMOTE_OBSERVATION_2026-09-29/answer_bundle.json"
)


def _holdout() -> dict:
    return json.loads(HOLDOUT.read_text(encoding="utf-8"))


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def test_fixture_digest_is_frozen() -> None:
    fixture = _holdout()
    body = {key: value for key, value in fixture.items() if key != "content_sha256"}
    digest = sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert fixture["content_sha256"] == digest


def test_holdout_source_is_byte_frozen_and_registered() -> None:
    fixture = _holdout()
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    registered = {
        source["source_id"]: source
        for case in registry["cases"]
        for source in case["sources"]
    }
    for source in fixture["sources"]:
        assert source["source_id"] in registered
        assert source["sha256"] == registered[source["source_id"]]["sha256"]
        snapshot = ROOT / source["snapshot_path"]
        assert sha256(snapshot.read_bytes()).hexdigest() == source["sha256"]


def test_holdout_uses_sources_outside_the_consumed_set() -> None:
    fixture = _holdout()
    consumed = set(fixture["consumed_set_scope"]["consumed_sources"])
    assert {source["source_id"] for source in fixture["sources"]} & consumed == set()
    bundle = json.loads(CONSUMED_ANSWERS.read_text(encoding="utf-8"))
    consumed_text = " ".join(
        row["answer"] for row in bundle["cases"]
    ).lower()
    for instance in fixture["instances"]:
        answers = [instance["baseline"]["answer"]] + [
            control["answer"] for control in instance["controls"]
        ]
        for answer in answers:
            # No sentence of the consumed answers may reappear here.
            for sentence in re.split(r"(?<=[.])\s+", consumed_text):
                if len(sentence) > 60:
                    assert sentence.strip() not in answer.lower()


def test_every_control_expectation_matches_the_shared_table() -> None:
    fixture = _holdout()
    for instance in fixture["instances"]:
        for control in instance["controls"]:
            expectation = control_expectation(control["variant"])
            assert tuple(
                control["expected_axes"][axis] for axis in AXES
            ) == expectation.expected_axes
            assert control["required_issue"] == expectation.required_issue


def test_baselines_are_clean_under_the_shared_rule() -> None:
    fixture = _holdout()
    for instance in fixture["instances"]:
        baseline = instance["baseline"]
        judgment = {**baseline["expected_axes"], "issues": []}
        assert evaluate_clean_answer(dimension_consistent=True, judgment=judgment)
        assert tuple(
            baseline["expected_axes"][axis] for axis in AXES
        ) == ("covered", "supported", "supported")


def test_holdout_carries_the_discriminating_structure() -> None:
    """False sentence + structurally valid citation to the real frozen locator."""
    fixture = _holdout()
    locators = {source["source_id"]: source["locator"] for source in fixture["sources"]}
    found = 0
    for instance in fixture["instances"]:
        for control in instance["controls"]:
            if control["variant"] != "unsupported_claim":
                continue
            answer = control["answer"]
            real = locators[instance["source_id"]]
            # The citation is structurally valid: it points at the real locator.
            assert real in answer
            assert "invalid.example" not in answer
            assert control["expected_axes"]["evidence_grounding"] == "gap"
            assert control["expected_axes"]["citation_support"] == "gap"
            found += 1
    assert found >= 1, "holdout must retain the unsupported-but-cited structure"


def test_wrong_citation_controls_use_real_but_unrelated_locators() -> None:
    """A fake URL would let a reviewer pass on shape alone."""
    fixture = _holdout()
    real_locators = {
        source["locator"]
        for case in json.loads(REGISTRY.read_text(encoding="utf-8"))["cases"]
        for source in case["sources"]
    }
    for instance in fixture["instances"]:
        for control in instance["controls"]:
            if control["variant"] != "wrong_citation":
                continue
            cited = re.findall(r"\]\((https?://[^)]+)\)", control["answer"])
            assert cited, "wrong_citation control must carry a citation"
            assert any(url in real_locators for url in cited)
            assert "invalid.example" not in control["answer"]


def test_holdout_measures_both_gates() -> None:
    fixture = _holdout()
    controls = [
        control for instance in fixture["instances"] for control in instance["controls"]
    ]
    assert len(controls) == 6
    variants = [control["variant"] for control in controls]
    for variant in ("wrong_citation", "missing_aspect", "unsupported_claim"):
        assert variants.count(variant) == 2
    assert len(fixture["instances"]) == 2


def test_frozen_excerpts_still_match_the_snapshot() -> None:
    """The excerpt must remain extractable from the byte-frozen snapshot."""
    pytest.importorskip("pypdf")
    from pypdf import PdfReader

    fixture = _holdout()
    snapshot = ROOT / fixture["sources"][0]["snapshot_path"]
    pages = PdfReader(str(snapshot)).pages
    for instance in fixture["instances"]:
        excerpt = instance["source_text"]
        assert sha256(excerpt.encode("utf-8")).hexdigest() == instance["source_text_sha256"]
        page_text = _normalized(pages[instance["page"] - 1].extract_text() or "")
        assert _normalized(excerpt) in page_text


def test_constructor_is_recorded_as_disqualified() -> None:
    fixture = _holdout()
    assert "disqualified" in fixture["constructor_disqualification"]
    assert "constructed_from_frozen_source" in fixture["answer_provenance"]
