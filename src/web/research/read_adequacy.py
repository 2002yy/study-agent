"""§71C-3a production read adequacy: is this read worth escalating?

The §46 characterization classified reads with extra signals (HTML size, local
extractor yields) that the runtime does not have. Production only sees the
reader payload, so this module freezes the decision that actually matters for
escalation:

    ok                  enough text, no shell/anti-bot signature
    read_failed         the reader itself failed
    anti_bot_or_error   challenge/interstitial markers in the text
    js_shell            an "enable javascript"-style shell
    short_doc           less text than a real document

The §46 tool imports these constants so measurement and production cannot drift.
This module decides nothing else: it is a gate for *starting one escalation*,
not an evidence judgement - extraction, support and the Gate keep that
authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

SHORT_CHAR_THRESHOLD = 800

JS_SHELL_MARKERS = (
    "enable javascript",
    "javascript is required",
    "please turn on javascript",
    "noscript",
)

ANTI_BOT_MARKERS = (
    "captcha",
    "access denied",
    "are you a robot",
    "unusual traffic",
    "just a moment",
    "checking your browser",
)

ADEQUATE_SHAPE = "ok"
FAILED_SHAPE = "read_failed"


@dataclass(frozen=True)
class ReadAdequacy:
    """Shape plus the two numbers behind it; purely descriptive."""

    shape: str
    chars: int
    adequate: bool

    def to_dict(self) -> dict[str, Any]:
        return {"shape": self.shape, "chars": self.chars, "adequate": self.adequate}


def classify_reader_result(result: Mapping[str, Any] | None) -> ReadAdequacy:
    """Classify one production reader payload (never raises)."""

    payload = result if isinstance(result, Mapping) else {}
    text = str(payload.get("content") or "")
    chars = len(text)
    if payload.get("ok") is not True:
        return ReadAdequacy(shape=FAILED_SHAPE, chars=chars, adequate=False)
    lowered = text.lower()
    if any(marker in lowered for marker in JS_SHELL_MARKERS):
        return ReadAdequacy(shape="js_shell", chars=chars, adequate=False)
    if any(marker in lowered for marker in ANTI_BOT_MARKERS):
        return ReadAdequacy(shape="anti_bot_or_error", chars=chars, adequate=False)
    if chars < SHORT_CHAR_THRESHOLD:
        return ReadAdequacy(shape="short_doc", chars=chars, adequate=False)
    return ReadAdequacy(shape=ADEQUATE_SHAPE, chars=chars, adequate=True)


def reader_shape(result: Mapping[str, Any] | None) -> str:
    return classify_reader_result(result).shape


def is_adequate(result: Mapping[str, Any] | None) -> bool:
    return classify_reader_result(result).adequate


__all__ = [
    "ADEQUATE_SHAPE",
    "ANTI_BOT_MARKERS",
    "FAILED_SHAPE",
    "JS_SHELL_MARKERS",
    "ReadAdequacy",
    "SHORT_CHAR_THRESHOLD",
    "classify_reader_result",
    "is_adequate",
    "reader_shape",
]
