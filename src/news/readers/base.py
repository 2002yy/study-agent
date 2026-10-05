"""Shared reader backend types for article extraction."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReaderResult:
    """Normalized output from any article reader backend."""

    text: str = ""
    method: str = ""
    error: str = ""
    # Best-effort byline. Empty means "not established" - never guessed.
    author: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.text)
