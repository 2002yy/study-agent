from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class ModelStats:
    flash_calls: int = 0
    pro_calls: int = 0
    flash_tokens: int = 0
    pro_tokens: int = 0
    total_latency: float = 0.0
    last_latency: float = 0.0
    slow_requests: int = 0
    llm_router_calls: int = 0
    last_perf: dict = field(default_factory=dict)

    @property
    def total_calls(self) -> int:
        return self.flash_calls + self.pro_calls

    @property
    def avg_latency(self) -> float:
        return self.total_latency / max(1, self.total_calls)

    def to_dict(self) -> dict:
        return {
            "Flash calls": self.flash_calls,
            "Pro calls": self.pro_calls,
            "LLM Router calls": self.llm_router_calls,
            "Flash tokens": self.flash_tokens,
            "Pro tokens": self.pro_tokens,
            "Average latency": f"{self.avg_latency:.2f}s",
            "Slow requests": self.slow_requests,
        }


_stats = ModelStats()
PRICING = {"flash": 1.0, "pro": 2.0}


def record_call(model: str, tokens: int, latency: float) -> None:
    if model == "flash":
        _stats.flash_calls += 1
        _stats.flash_tokens += tokens
    elif model == "pro":
        _stats.pro_calls += 1
        _stats.pro_tokens += tokens
    _stats.total_latency += latency
    _stats.last_latency = latency
    if latency > 10:
        _stats.slow_requests += 1


def track_latency(model: str):
    class _Tracker:
        def __init__(self, model_name: str, tokens: int = 0):
            self.model = model_name
            self.tokens = tokens
            self.start = 0.0

        def __enter__(self):
            self.start = time.time()
            return self

        def __exit__(self, *_args):
            record_call(self.model, self.tokens, time.time() - self.start)

    return _Tracker(model)


def get_stats() -> ModelStats:
    return _stats


def get_stats_dict() -> dict:
    return _stats.to_dict()


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 2)


def suggest_model_by_rules(user_input: str, performance_mode: str = "standard") -> str:
    if performance_mode == "fast":
        return "flash"
    if performance_mode == "deep":
        return "pro"

    text = user_input.lower()
    pro_keywords = ["论文", "代码", "bug", "方案", "架构", "原理", "机制"]
    flash_keywords = ["复盘", "总结", "简单", "闲聊", "入门"]
    pro_score = sum(1 for kw in pro_keywords if kw in text)
    flash_score = sum(1 for kw in flash_keywords if kw in text)
    if pro_score > flash_score or len(text) > 200:
        return "pro"
    return "flash"


def estimated_cost() -> float:
    flash_cost = _stats.flash_tokens / 1_000_000 * PRICING["flash"]
    pro_cost = _stats.pro_tokens / 1_000_000 * PRICING["pro"]
    return flash_cost + pro_cost


def record_llm_router_call(latency: float, tokens: int = 50) -> None:
    _stats.llm_router_calls += 1
    record_call("flash", tokens, latency)


def record_perf(metrics: dict) -> None:
    _stats.last_perf = dict(metrics)


def reset_stats() -> None:
    global _stats
    _stats = ModelStats()
