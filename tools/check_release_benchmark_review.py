"""Prepare a review packet or verify one independent review transport."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evals.release_benchmark_plan import load_release_benchmark_plan  # noqa: E402
from src.evals.release_benchmark_registry import load_gold, load_registry  # noqa: E402
from src.evals.release_benchmark_review import (  # noqa: E402
    ARTIFACT_SCHEMA,
    build_review_packet,
    check_github_review,
    check_independent_review_artifact,
    review_template,
)

FIXTURES = ROOT / "tests/fixtures/release_benchmark"
ARTIFACT_KEYS_ENV = "RELEASE_BENCHMARK_REVIEW_ARTIFACT_KEYS_JSON"


def _gh_api(endpoint: str, *, paginate: bool = False) -> Any:
    command = ["gh", "api", endpoint]
    if paginate:
        command.extend(["--paginate", "--slurp"])
    completed = subprocess.run(command, check=True, capture_output=True, text=True,
                               encoding="utf-8", cwd=ROOT, timeout=60)
    return json.loads(completed.stdout)


def _strict_json(path: Path) -> Any:
    def unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate independent review artifact key")
            result[key] = value
        return result

    def reject_constant(_: str) -> None:
        raise ValueError("non-finite independent review artifact value")

    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=unique_keys,
        parse_constant=reject_constant,
    )


def _trusted_artifact_issuers() -> dict[str, bytes]:
    raw = os.environ.get(ARTIFACT_KEYS_ENV)
    if raw is None:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{ARTIFACT_KEYS_ENV} must be a JSON object") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{ARTIFACT_KEYS_ENV} must be a JSON object")
    issuers: dict[str, bytes] = {}
    for issuer, secret_hex in parsed.items():
        if not isinstance(issuer, str) or not issuer or not isinstance(secret_hex, str):
            raise ValueError("invalid independent review trust entry")
        try:
            secret = bytes.fromhex(secret_hex)
        except ValueError as exc:
            raise ValueError("independent review trust secrets must be hex") from exc
        if len(secret) < 32:
            raise ValueError("independent review trust secret must be at least 32 bytes")
        issuers[issuer] = secret
    return issuers


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-id", action="append", dest="case_ids")
    parser.add_argument("--pr-number", type=int)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--review-id", type=int)
    modes.add_argument("--artifact", type=Path)
    args = parser.parse_args()

    plan = load_release_benchmark_plan(FIXTURES / "plan_v1.json")
    registry = load_registry(FIXTURES / "registry_v1.json", ROOT, plan)
    gold = load_gold(FIXTURES / "gold_v1.json", registry)
    packet = build_review_packet(registry, gold, case_ids=args.case_ids)

    if args.review_id is None and args.artifact is None and args.pr_number is None:
        print(json.dumps({
            "packet": packet,
            "github_review_template": review_template(packet),
            "independent_artifact_contract": {
                "schema_version": ARTIFACT_SCHEMA,
                "trust_source": ARTIFACT_KEYS_ENV,
                "note": (
                    "Artifact verification requires an out-of-band issuer key; "
                    "the artifact cannot authorize itself."
                ),
            },
            "admitted_release_cases": 0,
            "release_gate": "NO_GO",
        }, ensure_ascii=False, sort_keys=True))
        return

    if args.pr_number is None or args.pr_number < 1:
        parser.error("verification requires positive --pr-number")
    if args.review_id is None and args.artifact is None:
        parser.error("verification requires --review-id or --artifact")
    if args.review_id is not None and args.review_id < 1:
        parser.error("--review-id must be positive")

    local_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=10,
    ).stdout.strip()
    endpoint = f"repos/2002yy/study-agent/pulls/{args.pr_number}"
    pr = _gh_api(endpoint)

    if args.review_id is not None:
        pages = _gh_api(endpoint + "/reviews?per_page=100", paginate=True)
        if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
            raise ValueError("GitHub review pagination was not complete")
        reviews = [review for page in pages for review in page]
        result = check_github_review(
            packet,
            pr,
            reviews,
            review_id=args.review_id,
            expected_head_sha=local_sha,
        )
    else:
        artifact = _strict_json(args.artifact)
        if not isinstance(artifact, dict):
            raise ValueError("independent review artifact must be an object")
        user = pr.get("user")
        author_login = user.get("login") if isinstance(user, dict) else ""
        result = check_independent_review_artifact(
            packet,
            artifact,
            expected_head_sha=local_sha,
            author_login=author_login,
            trusted_issuers=_trusted_artifact_issuers(),
        )

    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
