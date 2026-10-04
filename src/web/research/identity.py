"""Product-specific identity rules. A planner proposal is never identity proof."""
from __future__ import annotations

from dataclasses import dataclass
import re


_ALIASES = {
    "python": "python", "fastapi": "fastapi", "sqlite": "sqlite",
    "cuda": "cuda", "opus": "opus", "claude opus": "opus",
    "sonnet": "sonnet", "claude sonnet": "sonnet",
    "qwen": "qwen", "gpt": "gpt",
}
# Missing release components mean zero only for these known release schemes.
# Model generations deliberately retain precision: GPT 6 != GPT 6.1.
_RELEASE_WIDTH = {"python": 3, "fastapi": 3, "sqlite": 3, "cuda": 2}
_MIN_WIDTH = {"python": 2, "fastapi": 2, "sqlite": 2, "cuda": 1}


@dataclass(frozen=True)
class ResearchIdentity:
    product: str
    version: str


def resolve_identity(product: str, version: str) -> ResearchIdentity | None:
    """Resolve an exact release, without selecting a latest patch or stable build.

    Version-family intent is a separate planner input; this operation never turns
    an exact request into a wildcard. Unsupported syntax fails closed.
    """
    canonical = _ALIASES.get(" ".join(product.casefold().split()))
    match = re.fullmatch(r"(\d+(?:\.\d+)*)(?:(a|b|rc)(\d+))?", version.strip(), re.I)
    if canonical is None or match is None:
        return None
    parts = tuple(int(part) for part in match[1].split("."))
    width = _RELEASE_WIDTH.get(canonical)
    if width:
        if not _MIN_WIDTH[canonical] <= len(parts) <= width:
            return None
        parts += (0,) * (width - len(parts))
    elif len(parts) > 3 or match[2]:
        return None
    suffix = f"{match[2].lower()}{int(match[3])}" if match[2] else ""
    return ResearchIdentity(canonical, ".".join(map(str, parts)) + suffix)


def same_identity(requested: ResearchIdentity, observed: ResearchIdentity) -> bool:
    """Both inputs must already be resolved; product and exact version must match."""
    return requested == observed


_ANCHOR = re.compile(
    r"(?<![\w])(?P<product>Claude\s+Opus|Claude\s+Sonnet|Python|FastAPI|SQLite|CUDA|Opus|Sonnet|Qwen|GPT)"
    r"[\s-]*(?P<version>\d+(?:\.\d+)*(?:(?:a|b|rc)\d+)?)(?![\w.])", re.I,
)


def identities_in_text(text: str) -> tuple[ResearchIdentity, ...]:
    return tuple(identity for match in _ANCHOR.finditer(text)
                 if (identity := resolve_identity(match["product"], match["version"])) is not None)
