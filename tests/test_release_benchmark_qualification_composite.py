"""§162 A3-D: the composite holdout gates per source cluster, never on a total."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/release_benchmark"
COMPOSITE = FIXTURES / "qualification_holdout_v1.json"

CONTROL_VARIANTS = ("wrong_citation", "missing_aspect", "unsupported_claim")


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_composite_digest_is_frozen() -> None:
    composite = _load(COMPOSITE)
    body = {key: value for key, value in composite.items() if key != "content_sha256"}
    assert composite["content_sha256"] == sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def test_every_cluster_reference_resolves_and_matches_its_digest() -> None:
    composite = _load(COMPOSITE)
    assert len(composite["clusters"]) == 2
    for cluster in composite["clusters"]:
        manifest = ROOT / cluster["manifest"]
        assert manifest.exists(), cluster["manifest"]
        fixture = _load(manifest)
        assert fixture["content_sha256"] == cluster["content_sha256"]
        # Cluster A is frozen and carries no cluster_id; when a manifest declares
        # one it must agree with the composite label.
        if "cluster_id" in fixture:
            assert fixture["cluster_id"] == cluster["cluster_id"]
        assert cluster["instances"] == len(fixture["instances"])
        assert cluster["controls"] == sum(
            len(instance["controls"]) for instance in fixture["instances"]
        )


def test_gate_rule_is_per_cluster_and_forbids_a_blended_total() -> None:
    rule = _load(COMPOSITE)["gate_rule"]
    assert rule["blended_total_forbidden"] is True
    assert "AND" in rule["overall_pass"]
    assert rule["per_cluster"] == "target_detection all AND specificity all"


def test_cluster_gates_require_all_of_both_gates() -> None:
    composite = _load(COMPOSITE)
    for cluster in composite["clusters"]:
        assert cluster["gate"] == {"target_detection": "all", "specificity": "all"}
        assert cluster["controls"] == 6


def test_composite_exposes_no_averaged_score() -> None:
    """A blended field would let a cluster failure hide behind the other."""
    blob = json.dumps(_load(COMPOSITE), ensure_ascii=False).lower()
    for forbidden in ("average", "mean", "total_score", "accuracy", "f1"):
        assert forbidden not in blob


def test_independence_flags_are_frozen_exactly() -> None:
    flags = _load(COMPOSITE)["source_cluster_independence"]
    assert flags == {
        "document_independent": True,
        "topic_independent": True,
        "claim_instance_independent": True,
        "publisher_independent": False,
    }


def test_known_limitation_states_the_publisher_boundary() -> None:
    limitation = _load(COMPOSITE)["known_limitation"]
    assert "publisher-level generalization" in limitation
    assert "cross-document/cross-topic" in limitation


def test_composite_measures_twelve_controls_over_two_documents() -> None:
    composite = _load(COMPOSITE)
    snapshots = set()
    controls = 0
    for cluster in composite["clusters"]:
        fixture = _load(ROOT / cluster["manifest"])
        for source in fixture["sources"]:
            snapshots.add(source["sha256"])
        for instance in fixture["instances"]:
            variants = [control["variant"] for control in instance["controls"]]
            assert sorted(variants) == sorted(CONTROL_VARIANTS)
            controls += len(variants)
    assert controls == 12
    assert len(snapshots) == 2


@pytest.mark.parametrize("field", ["purpose", "frozen_at", "composite_id"])
def test_composite_declares_its_identity(field: str) -> None:
    value = _load(COMPOSITE)[field]
    assert isinstance(value, str) and value.strip()
