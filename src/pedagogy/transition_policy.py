from __future__ import annotations

from dataclasses import replace

from src.pedagogy.types import LearningState

MODE_PROTOCOLS = {
    "普通": "direct_answer",
    "苏格拉底": "socratic_rediscovery",
    "费曼": "feynman_diagnosis",
    "项目": "project_execution",
}


class ModeTransitionPolicy:
    def prepare(self, state: LearningState, mode: str) -> LearningState:
        protocol = MODE_PROTOCOLS.get(mode, "direct_answer")
        if state.protocol in {"", protocol}:
            return replace(state, protocol=protocol, protocol_version=2)

        suspended = dict(state.suspended)
        if state.protocol:
            suspended[state.protocol] = state.to_dict()
        restored = suspended.pop(protocol, None)
        if restored:
            resumed = LearningState.from_dict(restored)
            return replace(
                resumed,
                protocol=protocol,
                protocol_version=2,
                suspended=suspended,
            )
        return LearningState(
            protocol=protocol,
            protocol_version=2,
            objective=state.objective,
            suspended=suspended,
        )
