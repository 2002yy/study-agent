"""Offline release-case and hidden-gold admission contracts.

This module validates candidate cases. It never creates sources, gold labels,
human review, or release approval on behalf of an evaluator.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any

from src.evals.release_benchmark_plan import (
    FOCUSES,
    MODALITIES,
    MODES,
    ReleaseBenchmarkPlan,
    plan_digest,
)

REGISTRY_SCHEMA_VERSION = "release-benchmark-registry-v1"
GOLD_SCHEMA_VERSION = "release-benchmark-gold-v1"
_CASE_ID = re.compile(r"REL-[A-Z0-9][A-Z0-9-]{2,63}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_ROLES = {"primary", "supporting", "contradicting"}


def canonical_digest(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                             separators=(",", ":"))
                  .encode("utf-8")).hexdigest()


def _read_json(path: str | Path, label: str) -> Any:
    def unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate {label} JSON key")
            result[key] = value
        return result

    def reject_constant(_: str) -> None:
        raise ValueError(f"non-finite {label} JSON value")

    try:
        return json.loads(Path(path).read_text(encoding="utf-8"),
                          object_pairs_hook=unique_keys,
                          parse_constant=reject_constant)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"unreadable {label}") from exc


def _object(raw: Any, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(raw, dict) or set(raw) != keys:
        raise ValueError(f"invalid {label} fields")
    return raw


def _text(raw: Any, label: str, limit: int = 4000) -> str:
    if not isinstance(raw, str) or not raw.strip() or raw != raw.strip() or len(raw) > limit:
        raise ValueError(f"invalid {label}")
    return raw


def _text_list(raw: Any, label: str, *, required: bool = False) -> tuple[str, ...]:
    if not isinstance(raw, list) or (required and not raw):
        raise ValueError(f"invalid {label}")
    values = tuple(_text(item, label, 200) for item in raw)
    if len(values) != len(set(values)):
        raise ValueError(f"duplicate {label}")
    return values


def _timestamp(raw: Any, label: str) -> str:
    value = _text(raw, label, 40)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid {label}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError(f"{label} must be UTC")
    return value


def _digest(raw: Any, label: str) -> str:
    if not isinstance(raw, str) or not _SHA256.fullmatch(raw):
        raise ValueError(f"invalid {label}")
    return raw


def case_content_digest(raw: dict[str, Any]) -> str:
    """Bind every case field except its self-referential digest."""
    return canonical_digest({key: value for key, value in raw.items() if key != "content_sha256"})


@dataclass(frozen=True)
class ReleaseSource:
    source_id: str
    role: str
    locator: str
    snapshot_path: str | None
    sha256: str | None
    page: int | None
    region: str | None


@dataclass(frozen=True)
class ReleaseCase:
    case_id: str
    revision: int
    mode: str
    modality: str
    primary_focus: str
    question: str
    aspects: tuple[str, ...]
    required_units: tuple[str, ...]
    expected_conflicts: tuple[str, ...]
    limitations: tuple[str, ...]
    sources: tuple[ReleaseSource, ...]
    frozen_at: str
    freshness_requirement: str | None
    visual_evidence_required: bool
    content_sha256: str


@dataclass(frozen=True)
class ReleaseRegistry:
    plan_digest: str
    cases: tuple[ReleaseCase, ...]
    digest: str


@dataclass(frozen=True)
class GoldReview:
    case_id: str
    case_content_sha256: str
    annotator: str
    reviewer: str
    state: str
    source_verified: bool
    leakage_checked: bool
    difficulty_checked: bool
    modality_checked: bool
    aspect_rubric: tuple[tuple[str, str], ...]
    unit_sources: tuple[tuple[str, tuple[str, ...]], ...]

    @property
    def structurally_reviewed(self) -> bool:
        return (
            self.state == "approved"
            and self.annotator != self.reviewer
            and all((self.source_verified, self.leakage_checked,
                     self.difficulty_checked, self.modality_checked))
        )


@dataclass(frozen=True)
class ReleaseGold:
    registry_digest: str
    reviews: tuple[GoldReview, ...]
    digest: str


def load_registry(path: str | Path, root: Path, plan: ReleaseBenchmarkPlan) -> ReleaseRegistry:
    return parse_registry(_read_json(path, "release registry"), root, plan)


def parse_registry(raw: Any, root: Path, plan: ReleaseBenchmarkPlan) -> ReleaseRegistry:
    data = _object(raw, {"schema_version", "plan_digest", "cases"}, "release registry")
    if data["schema_version"] != REGISTRY_SCHEMA_VERSION or data["plan_digest"] != plan_digest(plan):
        raise ValueError("release registry schema or plan digest mismatch")
    rows = data["cases"]
    if not isinstance(rows, list) or len(rows) > plan.target_total:
        raise ValueError("invalid release case list")
    cases = tuple(_parse_case(row, root) for row in rows)
    ids = [case.case_id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate release case ID")
    cell_limits = {(cell.mode, cell.modality): cell.count for cell in plan.cells}
    focus_limits = dict(plan.focus_targets)
    for cell, limit in cell_limits.items():
        if sum((case.mode, case.modality) == cell for case in cases) > limit:
            raise ValueError("release case cell exceeds plan")
    for focus, limit in focus_limits.items():
        if sum(case.primary_focus == focus for case in cases) > limit:
            raise ValueError("release focus exceeds plan")
    return ReleaseRegistry(data["plan_digest"], cases, canonical_digest(data))


def _parse_case(raw: Any, root: Path) -> ReleaseCase:
    data = _object(raw, {
        "case_id", "revision", "mode", "modality", "primary_focus", "question",
        "aspects", "required_units", "expected_conflicts", "limitations", "sources",
        "frozen_at", "freshness_requirement", "visual_evidence_required", "content_sha256",
    }, "release case")
    case_id = _text(data["case_id"], "release case ID", 68)
    if not _CASE_ID.fullmatch(case_id):
        raise ValueError("release case must use the REL namespace")
    if type(data["revision"]) is not int or data["revision"] < 1:
        raise ValueError("invalid release case revision")
    mode, modality, focus = data["mode"], data["modality"], data["primary_focus"]
    if mode not in MODES or modality not in MODALITIES or focus not in FOCUSES:
        raise ValueError("invalid release case stratum")
    aspects = _text_list(data["aspects"], "question aspects", required=True)
    units = _text_list(data["required_units"], "required units", required=True)
    conflicts = _text_list(data["expected_conflicts"], "expected conflicts")
    limitations = _text_list(data["limitations"], "limitations")
    if not isinstance(data["sources"], list) or not data["sources"]:
        raise ValueError("release case requires original sources")
    sources = tuple(_parse_source(item, root, mode) for item in data["sources"])
    source_ids = [source.source_id for source in sources]
    if len(source_ids) != len(set(source_ids)) or not any(source.role == "primary" for source in sources):
        raise ValueError("release case requires distinct sources and a primary source")
    if mode == "frozen":
        if data["freshness_requirement"] is not None:
            raise ValueError("frozen case cannot carry live freshness requirement")
        if modality in {"image", "chart", "mixed"} and not any(
            source.page is not None and source.region for source in sources
        ):
            raise ValueError("frozen visual case requires page and region")
    else:
        _text(data["freshness_requirement"], "live freshness requirement")
    visual = data["visual_evidence_required"]
    if type(visual) is not bool or (visual and modality not in {"image", "chart", "mixed"}):
        raise ValueError("invalid visual evidence eligibility")
    digest = _digest(data["content_sha256"], "case content digest")
    if digest != case_content_digest(data):
        raise ValueError("release case content digest mismatch")
    return ReleaseCase(
        case_id, data["revision"], mode, modality, focus,
        _text(data["question"], "question"), aspects, units, conflicts, limitations,
        sources, _timestamp(data["frozen_at"], "case freeze time"),
        data["freshness_requirement"], visual, digest,
    )


def _parse_source(raw: Any, root: Path, mode: str) -> ReleaseSource:
    data = _object(raw, {
        "source_id", "role", "locator", "snapshot_path", "sha256", "page", "region",
    }, "release source")
    source_id = _text(data["source_id"], "source ID", 100)
    role = data["role"]
    if role not in _ROLES:
        raise ValueError("invalid source role")
    locator = _text(data["locator"], "source locator", 2000)
    page, region = data["page"], data["region"]
    if page is not None and (type(page) is not int or page < 1):
        raise ValueError("invalid source page")
    if region is not None:
        region = _text(region, "source region", 300)
    snapshot, digest = data["snapshot_path"], data["sha256"]
    if mode == "live":
        if snapshot is not None or digest is not None:
            raise ValueError("live registry cannot embed a source snapshot")
    else:
        snapshot = _text(snapshot, "frozen snapshot path", 500)
        digest = _digest(digest, "frozen source digest")
        prefix = Path("tests/fixtures/release_benchmark/sources")
        relative = Path(snapshot)
        base = root.resolve()
        source_root = (base / prefix).resolve()
        target = (base / relative).resolve()
        if (relative.is_absolute() or not source_root.is_relative_to(base)
                or not target.is_relative_to(source_root) or not target.is_file()):
            raise ValueError("frozen source must be a local release snapshot")
        if sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError("frozen source digest mismatch")
    return ReleaseSource(source_id, role, locator, snapshot, digest, page, region)


def load_gold(path: str | Path, registry: ReleaseRegistry) -> ReleaseGold:
    return parse_gold(_read_json(path, "release gold"), registry)


def parse_gold(raw: Any, registry: ReleaseRegistry) -> ReleaseGold:
    data = _object(raw, {"schema_version", "registry_digest", "reviews"}, "release gold")
    if data["schema_version"] != GOLD_SCHEMA_VERSION or data["registry_digest"] != registry.digest:
        raise ValueError("release gold schema or registry digest mismatch")
    rows = data["reviews"]
    if not isinstance(rows, list):
        raise ValueError("invalid release gold reviews")
    cases = {case.case_id: case for case in registry.cases}
    reviews = tuple(_parse_review(row, cases) for row in rows)
    ids = [review.case_id for review in reviews]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate release gold review")
    return ReleaseGold(registry.digest, reviews, canonical_digest(data))


def _parse_review(raw: Any, cases: dict[str, ReleaseCase]) -> GoldReview:
    data = _object(raw, {
        "case_id", "case_content_sha256", "annotator", "reviewer", "state",
        "source_verified", "leakage_checked", "difficulty_checked", "modality_checked",
        "aspect_rubric", "unit_sources",
    }, "release gold review")
    case = cases.get(data["case_id"])
    if case is None or data["case_content_sha256"] != case.content_sha256:
        raise ValueError("release gold has no matching case revision")
    state = data["state"]
    if state not in {"pending", "approved"}:
        raise ValueError("invalid gold review state")
    annotator = _text(data["annotator"], "gold annotator", 100)
    reviewer = _text(data["reviewer"], "gold reviewer", 100)
    flags = tuple(data[key] for key in (
        "source_verified", "leakage_checked", "difficulty_checked", "modality_checked",
    ))
    if any(type(flag) is not bool for flag in flags):
        raise ValueError("invalid gold review flags")
    if state == "approved" and (annotator == reviewer or not all(flags)):
        raise ValueError("gold approval requires independent complete review")
    rubric = data["aspect_rubric"]
    support = data["unit_sources"]
    if not isinstance(rubric, dict) or set(rubric) != set(case.aspects):
        raise ValueError("gold aspect rubric mismatch")
    if not isinstance(support, dict) or set(support) != set(case.required_units):
        raise ValueError("gold unit support mismatch")
    sources = {source.source_id for source in case.sources}
    unit_sources: list[tuple[str, tuple[str, ...]]] = []
    for unit_id, raw_ids in support.items():
        ids = _text_list(raw_ids, "gold support source IDs", required=True)
        if not set(ids) <= sources:
            raise ValueError("gold cites unknown source")
        unit_sources.append((unit_id, ids))
    return GoldReview(
        case.case_id, case.content_sha256, annotator, reviewer, state,
        flags[0], flags[1], flags[2], flags[3],
        tuple((key, _text(value, "aspect rubric")) for key, value in rubric.items()),
        tuple(unit_sources),
    )


def admission_report(plan: ReleaseBenchmarkPlan, registry: ReleaseRegistry,
                     gold: ReleaseGold) -> dict[str, object]:
    reviews = {review.case_id: review for review in gold.reviews}
    reviewed_candidates = tuple(case for case in registry.cases
                                if (review := reviews.get(case.case_id)) is not None
                                and review.structurally_reviewed)
    candidate_cell_counts = {
        f"{cell.mode}/{cell.modality}": sum(
            (case.mode, case.modality) == (cell.mode, cell.modality)
            for case in reviewed_candidates
        ) for cell in plan.cells
    }
    candidate_focus_counts = {
        focus: sum(case.primary_focus == focus for case in reviewed_candidates)
        for focus, _ in plan.focus_targets
    }
    pending = [
        {"case_id": case.case_id, "reason": "gold_review_missing_or_incomplete"}
        for case in registry.cases if case not in reviewed_candidates
    ]
    admitted = len(reviewed_candidates)
    return {
        "schema_version": "release-benchmark-admission-v2",
        "plan_digest": plan_digest(plan),
        "registry_digest": registry.digest,
        "gold_digest": gold.digest,
        "target_total": plan.target_total,
        "registered_cases": len(registry.cases),
        "reviewed_candidate_cases": len(reviewed_candidates),
        "admission_basis": "structural_gold_review",
        "admitted_release_cases": admitted,
        "missing_release_cases": plan.target_total - admitted,
        "candidate_cell_counts": candidate_cell_counts,
        "candidate_focus_counts": candidate_focus_counts,
        "pending_admission": pending,
        "release_gate": "NO_GO",
        "reason": "release_cases_incomplete" if admitted < plan.target_total else
                  "release_execution_not_evaluated",
    }
