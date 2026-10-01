"""§164-C2: collect the real legacy-vs-durable parity distribution.

Records observations only. It never tunes the observer, the classifier or the
isolation primitives, and it does not decide anything about phase 2.

The first C2 condition is deliberately the honest one: these representative turns
never go through a closure commit, so durable truth is empty. Whatever the
distribution turns out to be - including unflattering proportions - is recorded
as the real product state, not treated as a measurement fault.
"""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.application.chat_service import (  # noqa: E402
    ChatCommand,
    ChatDependencies,
    ChatService,
)
from src.application.learner_state_parity_observer import (  # noqa: E402
    LearnerStateParityCollector,
)
from src.application.learner_state_shadow_seam import SHADOW_FLAG  # noqa: E402
from src.application.shadow_isolation import BestEffortTelemetry  # noqa: E402
from src.domain.learner_state_parity import (  # noqa: E402
    DIMENSIONS,
    SHADOW_OK,
)
from src.domain.learner_model import LearnerModelSnapshot  # noqa: E402
from src.infrastructure.sqlite.database import RuntimeDatabase  # noqa: E402
from src.mode_manager import RuntimeModes  # noqa: E402
from src.pedagogy.engine import PedagogyEngine  # noqa: E402
from src.pedagogy.evaluation import PedagogyEvaluationService  # noqa: E402
from src.repositories.runtime_repository import RuntimeRepository  # noqa: E402
from src.tools.web_agent import WebToolTrace  # noqa: E402

# Pre-registered populations. Only the population changes between batches; the
# observer, classifier and isolation primitives stay frozen.
#
# Stratum A - legacy sparse / durable absent: ordinary turns in direct-answer
# mode, which do not populate a legacy objective or known points.
TURNS_A = (
    "explain how hashing works",
    "hashing maps keys to buckets using a hash function",
    "hashing is sort of like sorting",
    "the moon does not rotate on its own axis",
    "what is the weather today",
)

# Stratum B - legacy substantive / durable absent: socratic multi-turns on an
# empirical topic, which deterministically populate the legacy objective. The
# inclusion rule is fixed before the results are seen and never selects samples
# by their eventual parity category.
TURNS_B = (
    "why does the sky appear blue during the day",
    "so scattering depends on wavelength then",
    "let me conclude: shorter wavelengths scatter more strongly",
    "does that also explain red sunsets",
)

# Stratum B-prime candidates: screened by the **actual** classifier output, not by
# semantics. The classifier keys on Chinese external-fact markers, so English
# candidates can never satisfy the precondition; the declared kind is recorded
# alongside the actual one so a mismatch is visible.
TURNS_B_PRIME = (
    "哪一年出现了史上最强的飓风",
    "最新的 Python 版本是多少",
)

POPULATIONS = {
    "A": ("legacy_sparse_durable_absent", TURNS_A, "普通"),
    "B": ("legacy_sparse_durable_absent", TURNS_B, "苏格拉底"),
    "B_PRIME": ("legacy_substantive_durable_absent", TURNS_B_PRIME, "苏格拉底"),
}

SCHEMA = "learner-state-parity-collection-v1"


class _FakeRag:
    context = "local context"

    def to_dict(self) -> dict[str, object]:
        return {"status": "found", "context": self.context, "result_count": 1, "results": []}


def _service(tmp_path: Path, *, telemetry, mode: str, reader=None) -> ChatService:
    repository = RuntimeRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    dependencies = ChatDependencies(
        load_runtime_modes=lambda: RuntimeModes(
            memory_mode="preview", performance_mode="standard"
        ),
        read_memory_bundle=lambda context_mode: {},
        build_role_prompt=lambda role, **kwargs: f"role:{role}",
        route_request=lambda **kwargs: {
            "role": "nahida", "mode": mode, "model_profile": "flash", "reason": "test",
        },
        retrieve_local_knowledge=lambda *args, **kwargs: _FakeRag(),
        build_messages=lambda **kwargs: [
            {"role": "system", "content": kwargs["role_prompt"]},
            {"role": "user", "content": kwargs["user_input"]},
        ],
        chat=lambda *args, **kwargs: "complete reply",
        stream_chat=lambda *args, **kwargs: iter(["part"]),
        chat_max_tokens=lambda performance_mode: 1000,
        resolve_web_tools=lambda *args, **kwargs: WebToolTrace(enabled=False),
        pedagogy_engine=PedagogyEngine(),
        pedagogy_evaluation=PedagogyEvaluationService(),
        # Durable truth is empty: these turns never close.
        read_learner_model=reader or (lambda thread_id: LearnerModelSnapshot(thread_id=thread_id)),
    )
    return ChatService(repository, dependencies, shadow_telemetry=telemetry)


def _substantive(*, objective: str, known: int) -> bool:
    return bool(str(objective or "").strip()) or known > 0


def collect(tmp_dir: Path, *, population: str = "A") -> dict[str, object]:
    import os

    from src.pedagogy.classifier import classify_knowledge

    stratum_hint, turns, mode = POPULATIONS[population]
    snapshots: list[object] = []
    os.environ[SHADOW_FLAG] = "1"
    try:
        collector = LearnerStateParityCollector()
        telemetry = BestEffortTelemetry(collector)

        def _reader(thread_id: str) -> object:
            snapshot = LearnerModelSnapshot(thread_id=thread_id)
            snapshots.append(snapshot)
            return snapshot

        service = _service(tmp_dir, telemetry=telemetry, mode=mode, reader=_reader)
        records: list[dict[str, object]] = []
        for index, text in enumerate(turns):
            prepared = service.start_turn(
                ChatCommand(user_input=text, thread_id=f"c2-thread-{index}")
            )
            before = prepared.learning_state_before
            snapshot = snapshots[-1] if snapshots else None
            durable_known = len(
                getattr(snapshot, "claim_states", ()) or ()
            )
            observed = {
                "legacy_substantive": _substantive(
                    objective=before.objective, known=len(before.confirmed_points)
                ),
                "legacy_objective_present": bool(before.objective.strip()),
                "legacy_confirmed_points_count": len(before.confirmed_points),
                "durable_substantive": _substantive(
                    objective=getattr(snapshot, "objective", ""), known=durable_known
                ),
            }
            # stratum_assignment is recomputable from observed_state ALONE: it never
            # reads the declared kind and never reads the parity outcome.
            if observed["legacy_substantive"] and not observed["durable_substantive"]:
                assigned = "B"
            elif not observed["legacy_substantive"] and not observed["durable_substantive"]:
                assigned = "A"
            else:
                assigned = "other"
            records.append({
                "turn": text,
                "construction_precondition": {
                    "mode": mode,
                    "knowledge_kind_declared": "empirical",
                    "knowledge_kind_actual": classify_knowledge(text),
                },
                "observed_state": observed,
                "stratum_assignment": assigned,
            })
        telemetry.flush(timeout=2.0)

        observations = collector.observations()
        overall = Counter()
        per_dimension: dict[str, Counter[str]] = {name: Counter() for name in DIMENSIONS}
        shadow_status = Counter()
        for payload in observations:
            observation = payload["observation"]
            shadow_status[observation["shadow_status"]] += 1
            if observation["shadow_status"] != SHADOW_OK:
                continue
            overall[observation["overall_classification"]] += 1
            for verdict in observation["dimensions"]:
                per_dimension[verdict["dimension"]][verdict["classification"]] += 1
        telemetry.close()
        # Attach parity AFTER stratum assignment is fixed.
        payloads = list(observations)
        for record, payload in zip(records, payloads, strict=False):
            observation = payload["observation"]
            record["parity"] = {
                "overall": observation["overall_classification"],
                "five_dimensions": {
                    verdict["dimension"]: verdict["classification"]
                    for verdict in observation["dimensions"]
                },
            }
        return {
            "schema_version": SCHEMA,
            "population": population,
            "stratum_hint": stratum_hint,
            "stratum_from_observed_state": sorted({r["stratum_assignment"] for r in records}),
            "records": records,
            "condition": "durable_truth_empty_no_closure",
            "turns": list(turns),
            "observation_count": len(observations),
            "shadow_status": dict(sorted(shadow_status.items())),
            "overall_classification": dict(sorted(overall.items())),
            "per_dimension": {
                name: dict(sorted(counts.items()))
                for name, counts in sorted(per_dimension.items())
            },
        }
    finally:
        os.environ.pop(SHADOW_FLAG, None)


def main() -> None:
    import argparse
    import tempfile

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--population", default="A", choices=sorted(POPULATIONS))
    args = parser.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="c2-parity-"))
    report = collect(tmp, population=args.population)
    out = ROOT / "docs/research_quality" / (
        f"LEARNER_STATE_PARITY_C2_{args.population}_2026-10-01.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
