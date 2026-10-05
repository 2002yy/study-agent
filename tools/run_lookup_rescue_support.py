"""Replay four provenance-bound L5 sources without granting generic publication rights."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MAIN = "7ff7451da608775324383968b4c7ed23c5687832"
CASE_IDS = {"alternate_official", "nonofficial_direct", "related_missing_field", "unbound_exhaustion"}


def validate_main_gate(proof: dict) -> None:
    if not (proof.get("databaseId") == 37314347931 and proof.get("headSha") == MAIN
            and proof.get("event") == "push" and proof.get("status") == "completed"
            and proof.get("conclusion") == "success"):
        raise ValueError("exact-main success proof required before L5 replay")


def load_sources(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases", [])
    if len(cases) != 4 or {row["id"] for row in cases} != CASE_IDS:
        raise ValueError("exactly the four frozen L5 cases are required")
    for row in cases:
        if row.get("query") != "Python 3.14什么时候发布":
            raise ValueError("frozen query changed")
        sources = row.get("sources", [])
        if len(sources) != (2 if row["id"] == "unbound_exhaustion" else 1):
            raise ValueError("unexpected source count")
        for source in sources:
            raw = (path.parent / source["payload_path"]).read_bytes()
            if not raw or hashlib.sha256(raw).hexdigest() != source.get("payload_sha256"):
                raise ValueError("frozen source payload digest mismatch")
            if not source.get("read_at") or source.get("kind") != "captured_public_html":
                raise ValueError("source capture provenance missing; synthetic controls are not qualification")
            source["html"] = raw.decode(source.get("encoding", "utf-8"), errors="replace")
    return cases


def replay(cases: list[dict]) -> list[dict]:
    from src.infrastructure.sqlite.database import RuntimeDatabase
    from src.news.article_fetcher import ArticleReadResult
    from src.news.readers.local_reader import read_html_locally
    from src.web import tool_gateway
    from src.web.research import official_resolver as resolver
    from src.web.research_recovery import recover_public_research, recovery_summary
    from tests.test_lookup_tier_qualification import saved_exit

    rows = []
    for case in cases:
        sources = {source["url"]: source for source in case["sources"]}
        backend_reads, queries = [], []

        class FailedDirect:
            def open(self, request, timeout):
                backend_reads.append(request.full_url)
                raise TimeoutError("controlled official direct failure")

        def reader(url, **kwargs):
            backend_reads.append(url)
            result = read_html_locally(sources[url]["html"], url, kwargs["max_chars"])
            return ArticleReadResult(ok=bool(result.text), requested_url=url, final_url=url,
                                     text=result.text, method=result.method, author=result.author)

        gateway = tool_gateway.GeneralWebGateway()

        def search(query, **_kwargs):
            queries.append(query)
            return {"status": "ok", "results": [
                {"url": url, "title": source["title"], "snippet": "frozen discovery candidate"}
                for url, source in sources.items()]}

        started = time.monotonic()
        connections = []
        connect = RuntimeDatabase.connect

        def tracked_connect(database):
            connection = connect(database)
            connections.append(connection)
            return connection

        with patch.object(resolver, "build_opener", lambda *_a: FailedDirect()), \
                patch.object(tool_gateway, "fetch_article_read_result", reader), \
                patch.object(gateway, "search_exact", search), \
                patch.object(RuntimeDatabase, "connect", tracked_connect), \
                tempfile.TemporaryDirectory() as temporary:
            try:
                calls = recover_public_research(gateway, case["query"])
                saved, audit = saved_exit(Path(temporary), case["query"], calls)
            finally:
                for connection in connections:
                    connection.close()
        summary = recovery_summary(calls)
        elapsed = time.monotonic() - started
        if len(queries) > 2 or summary["reads"] > 3 or elapsed > 30:
            raise ValueError("Lookup bounded replay exceeded its budget")
        if audit["assertion_refs"] or audit["answer_generation_calls"] or audit["status"] != "abstained":
            raise ValueError("generic replay unexpectedly acquired publication authority")
        rows.append({"id": case["id"], "sources": [{k: v for k, v in source.items() if k != "html"}
                    for source in sources.values()], "backend_reads": backend_reads, "queries": queries,
                    "elapsed_seconds": elapsed, "summary": summary, "raw_calls": calls,
                    "publication": audit, "saved_answer": saved.assistant_message,
                    "claim_support": "NOT_QUALIFIED", "dangerous_publish": 0})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--main-ci", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    validate_main_gate(json.loads(args.main_ci.read_text(encoding="utf-8")))
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip():
        raise ValueError("clean candidate required")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    cases = load_sources(args.manifest)
    rows = replay(cases)
    result = {"head": head, "base": MAIN, "kind": "frozen-source replay; not live discovery",
              "official_direct_failure": "controlled injection", "runs": rows,
              "generic_rescue_publication": "NOT_QUALIFIED", "lookup": "NOT_CLOSED"}
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"runs": len(rows), "head": head, "artifact": str(args.output)}))


if __name__ == "__main__":
    main()
