"""Capability gate for the A/B/C research experiment.

The experiment compares three arms that differ only in which read paths are
available. Without a gate the model can always reach every path, so a run cannot
be attributed to one arm. This module is the single owner of that decision.

Production behaviour is unchanged while ``RESEARCH_EXPERIMENT_ARM`` is unset.
An unknown value fails closed on purpose: a typo must not silently hand an arm
the full capability set and invalidate the comparison.
"""

from __future__ import annotations

import os
from typing import Final

ARM_ENV: Final = "RESEARCH_EXPERIMENT_ARM"

#: Features an arm may use. ``platform`` is the HN/Stack Exchange/Discourse
#: API dispatch; ``discussion`` is the comment extraction inside a read;
#: ``comments`` is the Bilibili comment reader; ``video`` is the transcript
#: reader (subtitles, ASR, burned-in OCR).
_ARM_FEATURES: Final[dict[str, frozenset[str]]] = {
    "a": frozenset(),
    "b": frozenset({"platform", "discussion", "comments"}),
    "c": frozenset({"platform", "discussion", "comments", "video"}),
}

INVALID_ARM: Final = "invalid"


def experiment_arm() -> str:
    """Return the configured arm, "" for production, or ``invalid``."""

    raw = os.getenv(ARM_ENV, "").strip().lower()
    if not raw:
        return ""
    return raw if raw in _ARM_FEATURES else INVALID_ARM


def feature_allowed(feature: str) -> bool:
    arm = experiment_arm()
    if not arm:
        return True
    if arm == INVALID_ARM:
        return False
    return feature in _ARM_FEATURES[arm]


def disabled_result(feature: str, url: str) -> dict[str, object]:
    """A deterministic failure the model can see and stop retrying."""

    return {
        "ok": False,
        "kind": "web_page",
        "url": url,
        "error": f"{feature} reads are disabled in experiment arm "
        f"{experiment_arm()!r}",
        "error_code": "arm_disabled",
    }
