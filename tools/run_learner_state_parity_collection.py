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

# Representative turns: plain question, a claim-shaped answer, a partial answer,
# a misconception-shaped answer, and an off-topic remark.
TURNS = (
    "explain how hashing works",
    "hashing maps keys to buckets using a hash function",
    "hashing is sort of like sorting",
    "the moon does not rotate on its own axis",
    "what is the weather today",
)

SCHEMA = "learner-state-parity-collection-v1"


class _FakeRag:
    context = "local context"

    def to_dict(self) -> dict[str, object]:
        return {"status": "found", "context": self.context, "result_count": 1, "results": []}


def _service(tmp_path: Path, *, telemetry) -> ChatService:
    repository = RuntimeRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    dependencies = ChatDependencies(
        load_runtime_modes=lambda: RuntimeModes(
            memory_mode="preview", performance_mode="standard"
        ),
        read_memory_bundle=lambda context_mode: {},
        build_role_prompt=lambda role, **kwargs: f"role:{role}",
        route_request=lambda **kwargs: {
            "role": "nahida", "mode": "普通", "model_profile": "flash", "reason": "test",
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
        read_learner_model=lambda thread_id: LearnerModelSnapshot(thread_id=thread_id),
    )
    return ChatService(repository, dependencies, shadow_telemetry=telemetry)


def collect(tmp_dir: Path) -> dict[str, object]:
    import os

    os.environ[SHADOW_FLAG] = "1"
    try:
        collector = LearnerStateParityCollector()
        telemetry = BestEffortTelemetry(collector)
        service = _service(tmp_dir, telemetry=telemetry)
        for index, text in enumerate(TURNS):
            service.start_turn(
                ChatCommand(user_input=text, thread_id=f"c2-thread-{index}")
            )
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
        return {
            "schema_version": SCHEMA,
            "condition": "durable_truth_empty_no_closure",
            "turns": list(TURNS),
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
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="c2-parity-"))
    report = collect(tmp)
    out = ROOT / "docs/research_quality" / "LEARNER_STATE_PARITY_C2_2026-10-01.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
