"""Small shared explicit-answer detector for routing and teaching protocols."""

import re

_DIRECT = re.compile(
    r"直接告诉我|直接回答|直接给(?:我)?答案|给我答案|完整讲解|直接讲解|"
    r"停止引导|停止提问|不要追问|不要继续让我复述"
)
_NEGATED = re.compile(r"(?:别|不要|不用|不必)(?:再|先|马上)?$")


def requests_direct_answer(text: str) -> bool:
    return any(
        not _NEGATED.search(text[max(0, match.start() - 6) : match.start()])
        for match in _DIRECT.finditer(text)
    )
