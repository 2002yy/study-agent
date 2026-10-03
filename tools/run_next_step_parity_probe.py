"""§165-C Independent NextStep parity probe (path 2, thin comparator).

Answers one local question only: what is the relationship between the durable primary
NextStep text and the legacy ``unresolved_gap``?

Design constraints (frozen by the 165-C ruling):

* does NOT modify ``build_durable_projection`` or the §164 parity instrument v1
* does NOT change the ``_classify_next_step`` semantics (it reuses them)
* reads only ``snapshot.next_step_text`` and ``legacy.unresolved_gap``
* results are §165 evidence and must not be mixed into §164 v1 statistics

The comparator is deliberately thin: adapt inputs, call the existing classifier, record.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from src.domain.learner_state_parity import (
    DurableLearnerProjection,
    LegacyLearnerProjection,
    _classify_next_step,
)

PROBE_NAMESPACE = "learner-next-step-parity-probe-165"

# Representative relationships between the two producers.
CASES = (
    ("both empty", "", ""),
    ("legacy only", "why does recovery span turns", ""),
    ("durable only", "", "review the recovery boundary"),
    ("identical text", "review the recovery boundary", "review the recovery boundary"),
    ("different text", "why does recovery span turns", "review the recovery boundary"),
)


def classify(legacy_gap: str, durable_text: str) -> dict[str, object]:
    legacy = LegacyLearnerProjection(next_step_hint=legacy_gap)
    durable = DurableLearnerProjection(
        next_steps=(durable_text,) if durable_text else ()
    )
    verdict = _classify_next_step(legacy, durable)
    return {
        "legacy_unresolved_gap": legacy_gap,
        "durable_next_step_text": durable_text,
        "classification": verdict.classification,
        "reason": getattr(verdict, "reason", ""),
    }


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("next_step_probe.json")
    rows = [{"case": name, **classify(gap, text)} for name, gap, text in CASES]
    payload = {
        "schema_version": "next-step-parity-probe-v1",
        "namespace": PROBE_NAMESPACE,
        "contract": "165-C",
        "note": (
            "independent thin comparator; reuses the frozen classifier semantics; "
            "does NOT modify the 164 parity instrument; results are 165 evidence only "
            "and must not be mixed into 164 v1 statistics"
        ),
        "case_count": len(rows),
        "classifications": sorted({r["classification"] for r in rows}),
        "rows": rows,
    }
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    for r in rows:
        print(f"{r['case']}: {r['classification']} ({r['reason']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
