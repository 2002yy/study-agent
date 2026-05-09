from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PERF_LOG = ROOT / "logs" / "perf_log.jsonl"


@dataclass
class PerfMetrics:
    route_time: float = 0.0
    memory_read_time: float = 0.0
    context_build_time: float = 0.0
    llm_first_token_time: float = 0.0
    llm_total_time: float = 0.0
    ui_render_time: float = 0.0
    total_time: float = 0.0
    llm_calls: int = 0
    context_mode: str = ""
    performance_mode: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class PerfTracker:
    def __init__(self) -> None:
        self._marks: dict[str, float] = {}
        self.metrics = PerfMetrics()
        self._run_started = time.perf_counter()

    def start(self, name: str) -> None:
        self._marks[name] = time.perf_counter()

    def stop(self, name: str, target_attr: str) -> float:
        started = self._marks.pop(name, None)
        if started is None:
            return 0.0
        elapsed = time.perf_counter() - started
        setattr(self.metrics, target_attr, elapsed)
        return elapsed

    def set(self, target_attr: str, value: float) -> None:
        setattr(self.metrics, target_attr, value)

    def finish(self) -> PerfMetrics:
        self.metrics.total_time = time.perf_counter() - self._run_started
        return self.metrics


def write_perf_log(metrics: PerfMetrics) -> None:
    PERF_LOG.parent.mkdir(parents=True, exist_ok=True)
    with PERF_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(metrics.to_dict(), ensure_ascii=False) + "\n")
