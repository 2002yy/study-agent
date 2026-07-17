"""Record one compact GitHub provider replay through the production service path."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.application.runtime_repository import (
    get_github_change_impact_service,
    get_github_work_item_service,
)
from src.web.github_pr_review_context import GitHubPRReviewContextService
from src.web.github_pr_review_recording import record_github_replay_context


def _repository_url(value: str) -> str:
    resolved = value.strip()
    if "://" not in resolved and resolved.count("/") == 1:
        return f"https://github.com/{resolved}"
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("repository", help="GitHub owner/name or repository URL")
    parser.add_argument("pull_request", type=int)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-provider-requests", type=int, default=32)
    parser.add_argument("--max-pages-per-collection", type=int, default=10)
    args = parser.parse_args()

    service = GitHubPRReviewContextService(
        get_github_work_item_service(),
        get_github_change_impact_service(),
    )
    result = record_github_replay_context(
        service,
        _repository_url(args.repository),
        args.pull_request,
        max_provider_requests=max(1, min(args.max_provider_requests, 128)),
        max_pages_per_collection=max(1, min(args.max_pages_per_collection, 50)),
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
