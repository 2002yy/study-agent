"""Map a change set to the CI scope it actually needs.

The previous classifier answered a single yes/no question - does this need the frontend -
and defaulted to the full historical gate on anything it did not recognise. That is too
coarse in both directions: a research-only change still paid for the browser gates, and a
frontend-only change still paid for the research qualification.

This maps each changed path to one of a small set of categories, and derives the gates
from the categories. Unknown paths stay conservative: they widen the scope rather than
silently narrowing it.

It is a pure function over a list of paths, so the routing can be tested without CI.
"""

from __future__ import annotations

import argparse
import json
from fnmatch import fnmatch
import sys

# Ordered so the first match wins; most specific categories come first.
_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "qualification",
        (
            "tests/test_rq1c_*",
            "tests/test_*qualification*",
            "tests/test_stage_gate*",
            "tests/stage_gates.json",
            "tools/rq1c_*",
            "tools/run_*qualification*",
            "tools/l3_preflight.py",
            "config/*qualification*",
        ),
    ),
    (
        "shared-core",
        (
            "src/domain/*",
            "src/infrastructure/sqlite/*",
        ),
    ),
    (
        "persistence",
        (
            "src/repositories/*",
            "src/infrastructure/*",
        ),
    ),
    (
        "browser",
        (
            "src/web/research/*browser*",
            "src/web/research/*crawl4ai*",
            "tests/test_browser_*",
            "tests/fixtures/research_quality/browser_*",
        ),
    ),
    (
        "frontend",
        (
            "frontend/*",
        ),
    ),
    (
        "research-backend",
        (
            "src/web/research/*",
            "src/web/*",
            "tools/run_research_*",
            "tools/run_rag_*",
            "tools/run_answer_claim_*",
        ),
    ),
    (
        "learning-backend",
        (
            "src/application/*",
            "src/tools/*",
            "src/news/*",
        ),
    ),
    (
        "docs",
        (
            "docs/*",
            "AGENTS.md",
            "README*",
            "*.md",
        ),
    ),
)

CATEGORIES = tuple(name for name, _ in _RULES)

# Categories whose presence makes a change a legitimate force-L3 candidate.
_L3_CATEGORIES = frozenset({"qualification", "shared-core", "persistence"})

# Categories that require the frontend toolchain.
_FRONTEND_CATEGORIES = frozenset({"frontend"})


def classify_path(path: str) -> str:
    """Return the category for one path, or ``unknown``."""

    normalized = str(path or "").strip().replace("\\", "/")
    if not normalized:
        return "unknown"
    for name, patterns in _RULES:
        if any(fnmatch(normalized, pattern) for pattern in patterns):
            return name
    return "unknown"


def classify(paths: list[str]) -> dict:
    """Derive the CI scope from a change set.

    Unknown paths widen the scope: they request the full gate rather than a narrow one,
    so a path this map does not understand can never silently skip a required gate.
    """

    by_category: dict[str, list[str]] = {}
    unknown: list[str] = []
    for path in paths:
        category = classify_path(path)
        if category == "unknown":
            unknown.append(path)
        else:
            by_category.setdefault(category, []).append(path)

    categories = sorted(by_category)
    frontend_required = bool(_FRONTEND_CATEGORIES & set(categories)) or bool(unknown)
    l3_eligible = bool(_L3_CATEGORIES & set(categories)) or bool(unknown)
    full_scope = bool(unknown)
    return {
        "categories": categories,
        "paths_by_category": {k: sorted(v) for k, v in by_category.items()},
        "unknown_paths": sorted(unknown),
        "frontend_required": frontend_required,
        "l3_eligible": l3_eligible,
        "full_scope": full_scope,
        "scope": (
            "full"
            if full_scope
            else "research-backend-only"
            if categories == ["research-backend"]
            else "tiered"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Classify a change set into a CI scope")
    parser.add_argument("--paths-file", required=True, help="file with one path per line")
    parser.add_argument("--json", action="store_true", help="emit the full result as JSON")
    args = parser.parse_args(argv)

    try:
        with open(args.paths_file, encoding="utf-8") as handle:
            paths = [line.strip() for line in handle if line.strip()]
    except OSError as exc:
        print(f"ci_scope_unreadable: {type(exc).__name__}", file=sys.stderr)
        return 2

    result = classify(paths)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        print(f"scope={result['scope']}")
        print(f"frontend_required={'true' if result['frontend_required'] else 'false'}")
        print(f"l3_eligible={'true' if result['l3_eligible'] else 'false'}")
        print(f"categories={','.join(result['categories']) or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
