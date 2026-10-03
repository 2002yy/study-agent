"""§168-D Independent Misconception parity probe (path 2, thin comparator).

Answers one local question: what is the relationship between the durable misconception
records and the legacy evaluator observation?

Constraints (same as the next-step probe):

* does NOT modify the §164 parity instrument or its frozen projection
* reuses the ``_classify_misconception`` semantics unchanged for the label-set relation
* additionally reports the durable promotion state (status / count), which the frozen
  classifier cannot see because it compares labels only
* results are §168 evidence and must not be mixed into §164 v1 statistics
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from src.domain.learner_state_parity import (
    DurableLearnerProjection,
    LegacyLearnerProjection,
    _classify_misconception,
)

PROBE_NAMESPACE = "learner-misconception-parity-probe-168"


@dataclass
class DurableMisconceptionView:
    description: str
    status: str = "suspected"
    occurrence_count: int = 1

    @property
    def promoted(self) -> bool:
        return self.status == "confirmed"


@dataclass
class Case:
    name: str
    legacy_observations: tuple[str, ...] = ()
    durable: tuple[DurableMisconceptionView, ...] = field(default_factory=tuple)


CASES = (
    Case("neither side"),
    Case("legacy observation only", legacy_observations=("replays full history",)),
    Case(
        "durable suspected only",
        durable=(DurableMisconceptionView("replays full history"),),
    ),
    Case(
        "both, same text",
        legacy_observations=("replays full history",),
        durable=(DurableMisconceptionView("replays full history"),),
    ),
    Case(
        "both, different text",
        legacy_observations=("replays full history",),
        durable=(DurableMisconceptionView("bucket drift"),),
    ),
    Case(
        "durable confirmed",
        legacy_observations=("replays full history",),
        durable=(DurableMisconceptionView("replays full history", "confirmed", 4),),
    ),
)


def classify(case: Case) -> dict[str, object]:
    legacy = LegacyLearnerProjection(
        misconception_labels=case.legacy_observations
    )
    durable = DurableLearnerProjection(
        misconception_labels=tuple(d.description for d in case.durable)
    )
    verdict = _classify_misconception(legacy, durable)
    return {
        "case": case.name,
        "legacy_observations": list(case.legacy_observations),
        "durable_descriptions": [d.description for d in case.durable],
        "label_relation": verdict.classification,
        "durable_statuses": [d.status for d in case.durable],
        "any_promoted": any(d.promoted for d in case.durable),
    }


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("misconception_probe.json")
    rows = [classify(c) for c in CASES]
    payload = {
        "schema_version": "misconception-parity-probe-v1",
        "namespace": PROBE_NAMESPACE,
        "contract": "168-D",
        "note": (
            "independent thin comparator; reuses the frozen classifier for the label "
            "relation and reports the promotion state separately; does NOT modify the "
            "164 parity instrument; results are 168 evidence only"
        ),
        "case_count": len(rows),
        "label_relations": sorted({str(r["label_relation"]) for r in rows}),
        "rows": rows,
    }
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    for r in rows:
        print(
            f"{r['case']}: {r['label_relation']} | durable_statuses={r['durable_statuses']} "
            f"promoted={r['any_promoted']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
