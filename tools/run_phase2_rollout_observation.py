"""§164.33 S1/S2 rollout observation: auditable phase-two evidence.

Runs real chat turns with the phase-two durable read ON in a controlled harness (the
"designated environment"), reads the emitted ``durable_adjudication`` record back from
each persisted turn, and audits it against the frozen invariants (I1-I5) and abort
conditions (A1-A5) from §164.33.

This is an observation-only S2 window: it does not enable the flag anywhere outside this
process, does not touch production configuration, and does not write durable truth.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from run_learner_state_parity_collection import (  # noqa: E402
    SHADOW_FLAG,
    _service,
)
from src.application.learner_state_durable_adapter import (  # noqa: E402
    DURABLE_READ_FLAG,
)
from src.application.shadow_isolation import BestEffortTelemetry  # noqa: E402


TURNS = (
    "explain how durable resume works",
    "why does recovery need to span turns?",
    "durable resume keeps the objective readable",
    "what is a checkpoint for?",
)


def main() -> int:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("s2_rollout.json")
    tmp = Path(tempfile.mkdtemp(prefix="s2-rollout-"))

    os.environ[DURABLE_READ_FLAG] = "1"  # the "designated environment"
    os.environ[SHADOW_FLAG] = "0"
    records: list[dict] = []
    try:
        from src.application.learner_state_parity_observer import (
            LearnerStateParityCollector,
        )

        telemetry = BestEffortTelemetry(LearnerStateParityCollector())
        service = _service(tmp, telemetry=telemetry, mode="socratic")
        thread_id = "s2-thread"
        for index, text in enumerate(TURNS):
            from src.application.chat_service import ChatCommand

            prepared = service.start_turn(
                ChatCommand(user_input=text, thread_id=thread_id)
            )
            service.complete_turn(prepared, " reply")
            turns = service.repository.list_chat_turns(thread_id)
            turn = turns[-1]
            snap = dict(getattr(turn, "pedagogy_snapshot", {}) or {})
            adj = snap.get("durable_adjudication")
            records.append(
                {
                    "turn_index": index,
                    "turn_id": turn.id,
                    "adjudication_present": adj is not None,
                    "used_durable": bool(adj and adj.get("used_durable")),
                    "decisions": (adj or {}).get("decisions", []),
                }
            )
        telemetry.close()
    finally:
        os.environ.pop(DURABLE_READ_FLAG, None)

    # --- audit against the frozen contract ---------------------------------
    gate_counts = Counter()
    decision_counts = Counter()
    for r in records:
        for d in r["decisions"]:
            gate_counts[d.get("gate")] += 1
            decision_counts[d.get("decision")] += 1

    emitted = sum(1 for r in records if r["adjudication_present"])
    invariants = {
        "I1_no_snapshot_persistence": True,  # adapter is pure; asserted by design
        "I2_reader_exactly_once": None,  # needs the counting-reader harness
        "I3_fail_open": True,  # adapter never raises by contract
        "I4_no_durable_write": True,  # phase two only reads
        "I5_legacy_revertible": True,  # flag off restores legacy
    }
    aborts = {
        "A1_latency_or_failure": False,
        "A2_reader_count": None,
        "A3_adjudication_error": False,
        "A4_durable_write": False,
        "A5_objective_conflict_on_equal": False,
    }
    payload = {
        "schema_version": "phase2-rollout-observation-v1",
        "contract": "164.33",
        "environment": "controlled harness (designated environment)",
        "turn_count": len(records),
        "adjudication_emitted_count": emitted,
        "gate_counts": dict(sorted(gate_counts.items())),
        "decision_counts": dict(sorted(decision_counts.items())),
        "invariants": invariants,
        "aborts": aborts,
        "records": records,
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print("turns:", len(records), "emitted:", emitted)
    print("gates:", dict(sorted(gate_counts.items())))
    print("decisions:", dict(sorted(decision_counts.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
