"""§162 A3-D: the qualification holdout clusters are fresh, frozen and provable.

Each cluster replaces the consumed §161 calibration set for qualification
selection. These tests pin what makes them usable: a byte-frozen source link,
expectations that cannot drift from the shared control table, the structure that
discriminated the previous reviewer, and no overlap with the consumed set.
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
REGISTRY = FIXTURES / "registry_v1.json"

CLUSTER_A = FIXTURES / "holdout_v1.json"
CLUSTER_B = FIXTURES / "holdout_cluster_b_v1.json"
CLUSTERS = (CLUSTER_A, CLUSTER_B)

CONSUMED_ANSWERS = (
    ROOT / "docs/research_quality/"
    "RELEASE_BENCHMARK_REMOTE_OBSERVATION_2026-09-29/answer_bundle.json"
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


@pytest.mark.parametrize("path", CLUSTERS, ids=[p.stem for p in CLUSTERS])
def test_fixture_digest_is_frozen(path: Path) -> None:
    fixture = _load(path)
    body = {key: value for key, value in fixture.items() if key != "content_sha256"}
    assert fixture["content_sha256"] == sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode("utf-8")
    ).hexdigest()


@pytest.mark.parametrize("path", CLUSTERS, ids=[p.stem for p in CLUSTERS])
def test_sources_are_byte_frozen(path: Path) -> None:
    fixture = _load(path)
    for source in fixture["sources"]:
        snapshot = ROOT / source["snapshot_path"]
        assert snapshot.exists(), source["snapshot_path"]
        assert sha256(snapshot.read_bytes()).hexdigest() == source["sha256"]


@pytest.mark.parametrize("path", CLUSTERS, ids=[p.stem for p in CLUSTERS])
def test_holdout_uses_sources_outside_the_consumed_set(path: Path) -> None:
    fixture = _load(path)
    consumed = set(fixture["consumed_set_scope"]["consumed_sources"])
    assert {source["source_id"] for source in fixture["sources"]} & consumed == set()


@pytest.mark.parametrize("path", CLUSTERS, ids=[p.stem for p in CLUSTERS])
def test_no_item_reuses_consumed_answer_text(path: Path) -> None:
    fixture = _load(path)
    bundle = _load(CONSUMED_ANSWERS)
    consumed_text = " ".join(row["answer"] for row in bundle["cases"]).lower()
    consumed_sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.])\s+", consumed_text)
        if len(sentence) > 60
    ]
    for instance in fixture["instances"]:
        answers = [instance["baseline"]["answer"]] + [
            control["answer"] for control in instance["controls"]
        ]
        for answer in answers:
            for sentence in consumed_sentences:
                assert sentence not in answer.lower()


@pytest.mark.parametrize("path", CLUSTERS, ids=[p.stem for p in CLUSTERS])
def test_expectations_match_the_shared_table(path: Path) -> None:
    fixture = _load(path)
    for instance in fixture["instances"]:
        for control in instance["controls"]:
            expectation = control_expectation(control["variant"])
            assert tuple(
                control["expected_axes"][axis] for axis in AXES
            ) == expectation.expected_axes
            assert control["required_issue"] == expectation.required_issue


@pytest.mark.parametrize("path", CLUSTERS, ids=[p.stem for p in CLUSTERS])
def test_baselines_are_clean_under_the_shared_rule(path: Path) -> None:
    fixture = _load(path)
    for instance in fixture["instances"]:
        baseline = instance["baseline"]
        judgment = {**baseline["expected_axes"], "issues": []}
        assert evaluate_clean_answer(dimension_consistent=True, judgment=judgment)


@pytest.mark.parametrize("path", CLUSTERS, ids=[p.stem for p in CLUSTERS])
def test_cluster_carries_the_discriminating_structure(path: Path) -> None:
    """False sentence + structurally valid citation to the real frozen locator."""
    fixture = _load(path)
    locators = {source["source_id"]: source["locator"] for source in fixture["sources"]}
    found = 0
    for instance in fixture["instances"]:
        for control in instance["controls"]:
            if control["variant"] != "unsupported_claim":
                continue
            assert locators[instance["source_id"]] in control["answer"]
            assert "invalid.example" not in control["answer"]
            assert control["expected_axes"]["evidence_grounding"] == "gap"
            assert control["expected_axes"]["citation_support"] == "gap"
            found += 1
    assert found >= 1, "cluster must retain the unsupported-but-cited structure"


@pytest.mark.parametrize("path", CLUSTERS, ids=[p.stem for p in CLUSTERS])
def test_wrong_citation_uses_real_but_unrelated_locators(path: Path) -> None:
    """A fake URL would let a reviewer pass on shape alone."""
    fixture = _load(path)
    real_locators = {
        source["locator"]
        for case in _load(REGISTRY)["cases"]
        for source in case["sources"]
    }
    seen = 0
    for instance in fixture["instances"]:
        for control in instance["controls"]:
            if control["variant"] != "wrong_citation":
                continue
            cited = re.findall(r"\]\((https?://[^)]+)\)", control["answer"])
            assert cited, "wrong_citation control must carry a citation"
            assert any(url.split("#", 1)[0] in real_locators for url in cited)
            assert "invalid.example" not in control["answer"]
            seen += 1
    assert seen == 2


@pytest.mark.parametrize("path", CLUSTERS, ids=[p.stem for p in CLUSTERS])
def test_cluster_measures_both_gates(path: Path) -> None:
    fixture = _load(path)
    controls = [
        control for instance in fixture["instances"] for control in instance["controls"]
    ]
    assert len(controls) == 6
    assert len(fixture["instances"]) == 2
    variants = [control["variant"] for control in controls]
    for variant in ("wrong_citation", "missing_aspect", "unsupported_claim"):
        assert variants.count(variant) == 2


@pytest.mark.parametrize("path", CLUSTERS, ids=[p.stem for p in CLUSTERS])
def test_frozen_excerpts_still_match_the_snapshot(path: Path) -> None:
    fixture = _load(path)
    snapshot = ROOT / fixture["sources"][0]["snapshot_path"]
    if snapshot.suffix.lower() == ".pdf":
        pytest.importorskip("pypdf")
        from pypdf import PdfReader

        pages = PdfReader(str(snapshot)).pages
        extracted = [
            _normalized(page.extract_text() or "") for page in pages
        ]
        for instance in fixture["instances"]:
            assert sha256(
                instance["source_text"].encode("utf-8")
            ).hexdigest() == instance["source_text_sha256"]
            assert _normalized(instance["source_text"]) in extracted[instance["page"] - 1]
        return

    import sys

    sys.path.insert(0, str(ROOT))
    from src.evals.release_benchmark_replay import _VisibleText

    parser = _VisibleText()
    parser.feed(snapshot.read_text(encoding="utf-8"))
    page_text = _normalized(" ".join(parser.parts))
    for instance in fixture["instances"]:
        assert sha256(
            instance["source_text"].encode("utf-8")
        ).hexdigest() == instance["source_text_sha256"]
        assert _normalized(instance["source_text"]) in page_text


@pytest.mark.parametrize("path", CLUSTERS, ids=[p.stem for p in CLUSTERS])
def test_constructor_is_recorded_as_disqualified(path: Path) -> None:
    fixture = _load(path)
    assert "disqualified" in fixture["constructor_disqualification"]
    assert "constructed_from_frozen_source" in fixture["answer_provenance"]


@pytest.mark.parametrize("path", CLUSTERS, ids=[p.stem for p in CLUSTERS])
def test_clusters_are_distinct_documents(path: Path) -> None:
    fixture = _load(path)
    other = CLUSTER_B if path == CLUSTER_A else CLUSTER_A
    other_fixture = _load(other)
    assert {s["sha256"] for s in fixture["sources"]} & {
        s["sha256"] for s in other_fixture["sources"]
    } == set()
    assert {
        instance["instance_id"] for instance in fixture["instances"]
    } & {instance["instance_id"] for instance in other_fixture["instances"]} == set()
