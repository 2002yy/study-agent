"""Map a change set to the CI scope it actually needs.

The previous classifier answered a single yes/no question - does this need the frontend -
and defaulted to the full historical gate on anything it did not recognise. That is too
coarse in both directions: a research-only change still paid for the browser gates, and a
frontend-only change still paid for the research qualification.

This maps each changed path to one of a small set of categories, and derives the gates
from the categories. Unknown paths stay conservative: they widen the scope rather than
silently narrowing it.

The frontend side has three independent tiers, not one:

    frontend_required            unit tests, type check, production build
    frontend_e2e_required        a registered browser-interaction surface changed
    research_browser_required    the research web-fetch path changed

They are derived from different things on purpose. A single ``browser_required`` switch
used to conflate them: it was driven by the research-crawler category, so a React
interaction change skipped the browser gates while a crawler change paid for them.

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
        "developer-cli",
        ("tools/studyctl.py", "tools/studyctl_execution.py", "tools/studyctl_research.py", "tools/studyctl_recording.py", "tools/studyctl_compare.py", "tools/studyctl_ci.py", "tools/studyctl_github.py", "tests/test_studyctl_github.py", "tests/test_studyctl_github_cli.py", "tests/test_studyctl.py", "tests/test_studyctl_plan.py", "tests/test_studyctl_execution.py", "tests/test_studyctl_research.py", "tests/test_studyctl_catalog.py", "tests/test_studyctl_recording.py", "tests/test_studyctl_compare.py", "tests/test_studyctl_ci.py", "tests/test_studyctl_ci_cli.py", "tests/test_studyctl_event_pages.py"),
    ),
    (
        "conversation-decision",
        (
            "src/application/conversation_decision.py",
            "src/application/conversation_decision_runner.py",
            "src/application/conversation_action_dispatch.py",
            "src/application/conversation_action_step.py",
            "src/application/conversation_observation_followup.py",
            "src/application/conversation_bounded_loop.py",
            "src/application/conversation_loop_session.py",
            "src/application/conversation_observation_trail.py",
            "src/application/conversation_answer_input.py",
            "src/application/conversation_answer_runner.py",
            "src/application/conversation_answer_generator.py",
            "src/application/conversation_deepseek_transport.py",
            "src/application/conversation_deepseek_session.py",
            "src/application/conversation_deepseek_service.py",
            "src/application/conversation_progress_stream.py",
            "src/application/conversation_owned_binding.py",
            "src/api/routes/conversation_events_routes.py",
            "tests/test_conversation_decision.py",
            "tests/test_conversation_decision_runner.py",
            "tests/test_conversation_action_dispatch.py",
            "tests/test_conversation_action_step.py",
            "tests/test_conversation_observation_followup.py",
            "tests/test_conversation_bounded_loop.py",
            "tests/test_conversation_loop_session.py",
            "tests/test_conversation_observation_trail.py",
            "tests/test_conversation_answer_input.py",
            "tests/test_conversation_answer_runner.py",
            "tests/test_conversation_answer_generator.py",
            "tests/test_conversation_deepseek_transport.py",
            "tests/test_conversation_deepseek_session.py",
            "tests/test_conversation_deepseek_service.py",
            "tests/test_conversation_progress_stream.py",
            "tests/test_conversation_owned_binding.py",
            "tests/test_conversation_events_routes.py",
        ),
    ),
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
        "standard",
        (
            "src/application/standard_*.py",
            "src/repositories/standard_*.py",
            "src/web/research/standard_*.py",
            "tests/test_standard_*.py",
            "tests/test_lookup_terminal.py",
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
        "ci-tooling",
        (
            ".github/workflows/*",
            "tools/ci_*.py",
            "tools/check_ci_outcomes.py",
            "tools/run_stage_gate.py",
            "tests/test_ci_*.py",
            "tests/test_l3_preflight.py",
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

# Categories that require the frontend toolchain (unit tests, types, production build).
_FRONTEND_CATEGORIES = frozenset({"frontend"})

# Registered browser-interaction surfaces -> the Playwright specs that cover them.
#
# The old router had a single switch called ``browser_required`` that was driven by the
# research-crawler category, so a React component change never reached the browser gates
# while a crawler change did. Registration is explicit per surface: a component does not
# inherit browser coverage from the directory it happens to live in, and a path that is
# not registered here simply keeps the cheap frontend tier.
#
# Every pattern must match at least one file on disk and every named spec must exist;
# tests/test_ci_scope.py fails otherwise, so a renamed component or spec cannot leave a
# dead registration behind and pretend the surface is still covered.
_FRONTEND_E2E_SURFACES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "frontend/src/features/single-chat/*",
        (
            "e2e/answer-interactions.spec.ts",
            "e2e/chat-role-settings.spec.ts",
            "e2e/chat-search-equivalence.spec.ts",
            "e2e/composer-layout.spec.ts",
            "e2e/recovery-visibility.spec.ts",
        ),
    ),
    (
        "frontend/src/features/reading/*",
        (
            "e2e/reading-panels.spec.ts",
            "e2e/panel-resizing.spec.ts",
            "e2e/complex-content.spec.ts",
        ),
    ),
    (
        "frontend/src/features/chat/*",
        (
            "e2e/answer-interactions.spec.ts",
            "e2e/chat-search-equivalence.spec.ts",
        ),
    ),
    (
        "frontend/src/features/answer-ui/*",
        (
            "e2e/answer-interactions.spec.ts",
            "e2e/answer-labs.spec.ts",
        ),
    ),
    (
        "frontend/src/features/sessions/*",
        (
            "e2e/bootstrap-journeys.spec.ts",
            "e2e/closure-session-journeys.spec.ts",
        ),
    ),
)

# Frontend feature directories that have no registered browser-interaction contract yet.
#
# Explicit, never implicit: the coverage test compares this list plus the surfaces above
# against the directories that actually exist under frontend/src/features, so adding a new
# feature forces a decision instead of silently shipping without browser coverage.
_FRONTEND_E2E_UNREGISTERED = frozenset(
    {
        "evidence",
        "extensions",
        "group-chat",
        "learning",
        "learning-memory",
        "migration",
        "pedagogy",
        "rag",
        "roles",
        "route",
        "settings",
        "task",
        "tools",
        "web-lookup",
        "wechat-workspace",
        "workflows",
    }
)

# Frontend paths that never carry an interaction contract of their own.
_FRONTEND_E2E_IGNORED_PATTERNS: tuple[str, ...] = (
    "frontend/e2e/*",
    "frontend/src/*.test.ts",
    "frontend/src/*.test.tsx",
    "frontend/*.json",
    "frontend/*.ts",
    "frontend/*.md",
    "frontend/*.html",
    "frontend/public/*",
)

# The routing machinery itself. A change here can alter what every later change is allowed
# to skip, so it is never treated as a narrow, self-exempting edit: it requests all three
# frontend-side tiers. It deliberately does *not* force ``full_scope``, because the
# fast-tier pytest path is itself the thing being changed and its own unit tests are what
# prove the router still routes.
_CI_ROUTER_PATHS = frozenset(
    {
        ".github/workflows/ci.yml",
        "tools/ci_scope.py",
        "tools/check_ci_outcomes.py",
        "tests/test_ci_scope.py",
        "tests/test_ci_outcomes.py",
        "tests/test_ci_workflow_routing.py",
    }
)

# Category -> the named impact set in tests/stage_gates.json that covers it. The workflow
# consumes this name; it must not keep its own list of test files.
#
# Only an exact, registered mapping belongs here. A broad mapping such as "any research
# path -> one research set" would look fast while silently narrowing what is verified, so
# an unregistered subsystem deliberately falls through to the full scope instead.
_IMPACT_SET_BY_CATEGORY: dict[str, str] = {
    "developer-cli": "studyctl",
    "conversation-decision": "conversation_decision_1b",
    "standard": "standard_research_loop",
}

# Categories that never choose an impact set on their own. Only prose does: a real slice
# almost always carries docs alongside its product change.
_IMPACT_NEUTRAL_CATEGORIES = frozenset({"docs"})

# The stage-gate manifest may ride along with a product slice as its registration. It is
# neutral *only* in that role; any other qualification path (a contract change, a protocol
# probe) is a real change and must not be treated as an attachment.
_MANIFEST_ATTACHMENT = "tests/stage_gates.json"


def _is_impact_neutral(path: str, category: str) -> bool:
    """True when this path must not block the product slice's impact set."""

    if category in _IMPACT_NEUTRAL_CATEGORIES:
        return True
    return str(path or "").replace("\\", "/") == _MANIFEST_ATTACHMENT


def _is_e2e_ignored(path: str) -> bool:
    normalized = str(path or "").strip().replace("\\", "/")
    return any(fnmatch(normalized, pattern) for pattern in _FRONTEND_E2E_IGNORED_PATTERNS)


def frontend_e2e_specs(path: str) -> tuple[str, ...]:
    """Return the Playwright specs registered for one frontend path, or ``()``.

    An empty result means "this path carries no registered browser contract", not "the
    surface is covered". The distinction is what keeps a new component from inheriting
    coverage it never had.
    """

    normalized = str(path or "").strip().replace("\\", "/")
    for pattern, specs in _FRONTEND_E2E_SURFACES:
        if fnmatch(normalized, pattern):
            return specs
    return ()


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
    category_set = set(categories)

    # A change to the routing machinery can decide what every later change may skip, so it
    # must not be the one change that runs the fewest gates.
    router_changed = any(
        str(path or "").strip().replace("\\", "/") in _CI_ROUTER_PATHS for path in paths
    )

    # Three independent tiers. They used to be two, and the browser tier was driven by the
    # research-crawler category, which meant a React interaction change never reached the
    # browser gates while a crawler change did.
    #
    #   frontend_required        unit tests, type check, production build
    #   frontend_e2e_required    the registered browser-interaction surfaces changed
    #   research_browser_required  the research web-fetch path changed
    frontend_required = (
        bool(_FRONTEND_CATEGORIES & category_set) or bool(unknown) or router_changed
    )

    e2e_specs: set[str] = set()
    e2e_surface_changed = False
    for path in by_category.get("frontend", []):
        if _is_e2e_ignored(path):
            continue
        specs = frontend_e2e_specs(path)
        if specs:
            e2e_surface_changed = True
            e2e_specs.update(specs)
    frontend_e2e_required = e2e_surface_changed or bool(unknown) or router_changed

    research_browser_required = (
        "browser" in category_set or bool(unknown) or router_changed
    )

    # Deprecated alias. It used to mean "the research crawler category matched", which is
    # why a frontend change skipped the browser gates. It now means exactly
    # ``frontend_e2e_required`` and is kept only so existing receipts and
    # check_ci_outcomes keep reading the same key. Do not add new readers; use
    # ``frontend_e2e_required`` or ``research_browser_required``.
    browser_required = frontend_e2e_required

    qualification_required = "qualification" in category_set or bool(unknown)
    # Eligibility means "this change may be part of a final L3 candidate". It is NOT the
    # same as "this PR must run L3 before merge": an intermediate slice that merely
    # registers or updates an impact set is eligible but not required.
    l3_eligible = bool(_L3_CATEGORIES & category_set) or bool(unknown)
    full_scope = bool(unknown)

    # The workflow consumes a named impact set instead of keeping its own file list.
    # Docs, CI tooling and a stage-gate registration ride along with a real slice, so they
    # are ignored here. Every remaining product category must be registered and agree on a
    # single set; an unknown path or an unregistered product category yields no impact set
    # and therefore the full scope, never a narrower run than the change actually needs.
    impact_set = ""
    if not full_scope:
        # Only genuinely neutral paths are set aside. Every other category must be
        # registered and agree on a single set, so a real qualification or CI change riding
        # along with a product slice cannot be silently dropped from the run.
        blocking: set[str] = set()
        for name, paths in by_category.items():
            if any(not _is_impact_neutral(p, name) for p in paths):
                blocking.add(name)
        if blocking and all(_IMPACT_SET_BY_CATEGORY.get(name) for name in blocking):
            mapped = {_IMPACT_SET_BY_CATEGORY[name] for name in blocking}
            if len(mapped) == 1:
                impact_set = next(iter(mapped))

    # L3 is explicitly triggered (ci-l3.yml / the run-l3 label), never inferred here.
    l3_required_for_merge = False

    return {
        "categories": categories,
        "paths_by_category": {k: sorted(v) for k, v in by_category.items()},
        "unknown_paths": sorted(unknown),
        "impact_set": impact_set,
        "frontend_required": frontend_required,
        "frontend_e2e_required": frontend_e2e_required,
        "frontend_e2e_specs": sorted(e2e_specs),
        "research_browser_required": research_browser_required,
        "browser_required": browser_required,
        "qualification_required": qualification_required,
        "l3_eligible": l3_eligible,
        "l3_required_for_merge": l3_required_for_merge,
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
        # utf-8-sig tolerates a BOM, which some shells add when writing the list.
        with open(args.paths_file, encoding="utf-8-sig") as handle:
            paths = [line.strip() for line in handle if line.strip()]
    except OSError as exc:
        print(f"ci_scope_unreadable: {type(exc).__name__}", file=sys.stderr)
        return 2

    result = classify(paths)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        # Machine-stable keys only; the workflow must not re-derive the routing itself.
        print(f"scope={result['scope']}")
        print(f"impact_set={result['impact_set']}")
        print(f"frontend_required={'true' if result['frontend_required'] else 'false'}")
        print(
            f"frontend_e2e_required="
            f"{'true' if result['frontend_e2e_required'] else 'false'}"
        )
        print(f"frontend_e2e_specs={','.join(result['frontend_e2e_specs'])}")
        print(
            f"research_browser_required="
            f"{'true' if result['research_browser_required'] else 'false'}"
        )
        # Deprecated alias of frontend_e2e_required; kept for existing receipts.
        print(f"browser_required={'true' if result['browser_required'] else 'false'}")
        print(
            f"qualification_required="
            f"{'true' if result['qualification_required'] else 'false'}"
        )
        print(f"l3_eligible={'true' if result['l3_eligible'] else 'false'}")
        print(
            f"l3_required_for_merge="
            f"{'true' if result['l3_required_for_merge'] else 'false'}"
        )
        print(f"full_scope={'true' if result['full_scope'] else 'false'}")
        print(f"categories={','.join(result['categories']) or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
