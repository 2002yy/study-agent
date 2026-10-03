"""§44C-Alt url-proposal qualification: DeepSeek-only domain-targeted retrieval.

The project depends only on the DeepSeek API, so the Brave replacement route is
off the table. This harness qualifies the constraint-compliant alternative:
the model **proposes** up to three official deep-page URLs for a claim, and the
existing reader **verifies** them (ok + non-empty content). The evidence gate
still guards correctness downstream; the proposal step only proposes.

Per target: exact_hit, same_domain_hit, read_ok / read_chars, latency, and the
proposed list. Frozen hard gate: Docker and PostgreSQL must be proposed
exactly; every case must yield at least one readable official page.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

from tools.run_recall_target_audit import TARGETS, TargetSpec  # noqa: E402

SCHEMA_VERSION = "url-proposal-qualification-v1"
MAX_PROPOSALS = 3

PROPOSAL_SYSTEM_PROMPT = (
    "You are a web-research planner with knowledge of official documentation "
    "sites. Given a claim, propose up to "
    f"{MAX_PROPOSALS} candidate official-documentation URLs that would directly "
    "state the needed fact. Only official sources (vendor docs, official "
    "repositories, standards bodies). Copy full https URLs, most likely first. "
    'Reply with strict JSON: {"urls": ["https://...", ...]}'
)


@dataclass
class ProposalRow:
    case_id: str
    target: str
    claim: str
    proposals: list[str] = field(default_factory=list)
    exact_hit: bool = False
    same_domain_hit: bool = False
    read_ok: bool = False
    read_chars: int = 0
    read_url: str = ""
    latency_ms: int = 0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "target": self.target,
            "claim": self.claim,
            "proposals": list(self.proposals),
            "exact_hit": self.exact_hit,
            "same_domain_hit": self.same_domain_hit,
            "read_ok": self.read_ok,
            "read_chars": self.read_chars,
            "read_url": self.read_url,
            "latency_ms": self.latency_ms,
            "error": self.error,
        }


def _domain(url: str) -> str:
    match = re.match(r"https?://([^/]+)", str(url or ""))
    return (match.group(1) if match else "").lower()


def evaluate_proposals(
    proposals: Sequence[str], target: TargetSpec
) -> dict[str, Any]:
    normalized = target.url.rstrip("/")
    target_domain = _domain(target.url)
    exact = any(str(url).rstrip("/") == normalized for url in proposals)
    same_domain = any(_domain(url) == target_domain for url in proposals)
    return {"exact_hit": exact, "same_domain_hit": same_domain}


def claim_for_target(target: TargetSpec) -> str:
    """Short claim per target (the fact the deep page must state)."""

    claims = {
        "rq1c-current-policy-container-registry": (
            "Docker Hub pull-rate limits for unauthenticated and authenticated users"
        ),
        "rq1c-current-support-postgresql": (
            "PostgreSQL supported major versions and the support duration of the oldest release"
        ),
        "rq1c-simple-license-uv": (
            "the open-source license of Astral's uv project, per its official repository"
        ),
        "rq1c-historical-current-node-modules": (
            "which module systems current Node.js officially supports"
        ),
    }
    return claims.get(target.case_id) or target.semantic_query


def evaluate_gate(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    hard = (
        "rq1c-current-policy-container-registry",
        "rq1c-current-support-postgresql",
    )
    hard_failures = [
        case_id
        for case_id in hard
        if not any(
            row["case_id"] == case_id and row["exact_hit"] for row in rows
        )
    ]
    unreadable = [row["case_id"] for row in rows if not row["read_ok"]]
    return {
        "passed": not hard_failures and not unreadable,
        "hard_gate_failures": sorted(set(hard_failures)),
        "unreadable_cases": sorted(set(unreadable)),
        "note": (
            "Docker and PostgreSQL must be proposed exactly; every case must "
            "yield at least one readable page (proposal + reader verification)"
        ),
    }


def run_qualification(
    *,
    output_path: Path,
    proposer: Callable[[str], list[str]] | None = None,
    reader: Callable[[str], Mapping[str, Any]] | None = None,
    targets: Sequence[TargetSpec] = TARGETS,
) -> dict[str, Any]:
    load_dotenv(REPO_ROOT / ".env")
    propose = proposer or _live_proposer()
    read = reader or _live_reader()
    rows: list[ProposalRow] = []
    for target in targets:
        claim = claim_for_target(target)
        row = ProposalRow(case_id=target.case_id, target=target.url, claim=claim)
        started = time.monotonic()
        try:
            row.proposals = list(propose(claim))[:MAX_PROPOSALS]
        except Exception as exc:
            row.error = f"{type(exc).__name__}: {exc}"[:200]
        row.latency_ms = int((time.monotonic() - started) * 1000)
        evaluation = evaluate_proposals(row.proposals, target)
        row.exact_hit = bool(evaluation["exact_hit"])
        row.same_domain_hit = bool(evaluation["same_domain_hit"])
        for url in row.proposals:
            raw = read(url) or {}
            content = str(raw.get("content") or "")
            if raw.get("ok") is True and content.strip():
                row.read_ok = True
                row.read_chars = len(content)
                row.read_url = url
                break
        rows.append(row)
        print(
            f"{target.case_id}: exact={row.exact_hit} same_domain={row.same_domain_hit} "
            f"read_ok={row.read_ok} chars={row.read_chars} ({row.latency_ms}ms)"
        )
        for url in row.proposals:
            print("   -", url)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "diagnostic_only": True,
        "qualification_evidence": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider": "deepseek_api_only",
        "status": "completed",
        "rows": [row.to_dict() for row in rows],
        "gate": evaluate_gate([row.to_dict() for row in rows]),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return payload


def _live_proposer() -> Callable[[str], list[str]]:
    from src.llm_client import chat

    def propose(claim: str) -> list[str]:
        raw = chat(
            [
                {"role": "system", "content": PROPOSAL_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps({"claim": claim}, ensure_ascii=False)},
            ],
            temperature=0.0,
            model_profile="flash",
            max_tokens=300,
            response_format="json_object",
            task_name="url_proposal",
            request_max_retries=0,
            extra_body={"thinking": {"type": "disabled"}},
        )
        try:
            payload = json.loads(raw)
        except Exception:
            return []
        urls = payload.get("urls")
        return [str(item) for item in urls][:MAX_PROPOSALS] if isinstance(urls, list) else []

    return propose


def _live_reader() -> Callable[[str], Mapping[str, Any]]:
    from src.web.research.active_adapter import ActiveResearchGateway

    gateway = ActiveResearchGateway()

    def read(url: str) -> Mapping[str, Any]:
        return dict(gateway.read(url, max_chars=6000) or {})

    return read


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    payload = run_qualification(output_path=args.output.resolve())
    print(json.dumps(payload["gate"], ensure_ascii=False, sort_keys=True))
    return 0 if payload["gate"]["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
