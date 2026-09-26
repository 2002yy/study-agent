"""§71C-2 Wigolo fetch-only shadow bakeoff.

Shadow only: the current reader path is measured exactly as production does it
(``probe_url`` from the §46 read-adequacy probe), Wigolo is measured through the
§71B ``ReadBackend`` surface, and **nothing here feeds the runtime**. A Wigolo
timeout, 5xx, browser crash or artifact-validation failure is recorded as
diagnostics and can never change a Study Agent result.

Runs one pass per invocation so cold and warm (cache/domain-routing) results are
never mixed::

    python -m tools.run_wigolo_shadow_bakeoff --pass cold --output <artifact>
    python -m tools.run_wigolo_shadow_bakeoff --pass warm --output <artifact>

Decision metrics reported: rescue_rate, false_escalation_value, added latency
(cold/warm separately) and artifact correctness (Wigolo content classified with
the same §46 adequacy classifier, plus expected-heading recall).
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from tools.run_read_adequacy_probe import _live_components, classify_read, probe_url

from src.web.research.retrieval_backends import ReadRequest
from src.web.research.wigolo_backend import WigoloShadowReadBackend

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "research_quality" / "WIGOLO_SHADOW.json"

SHORT_CHAR_THRESHOLD = 800  # mirrors the §46 classifier threshold


@dataclass(frozen=True)
class CorpusEntry:
    url: str
    klass: str
    expected_headings: tuple[str, ...] = ()
    note: str = ""


CORPUS: tuple[CorpusEntry, ...] = (
    CorpusEntry(
        "https://docs.docker.com/docker-hub/usage/pulls/",
        "A_known_thin",
        ("pull", "rate limit"),
        "§47 case: HTML ~350k, extracted ~520 chars",
    ),
    CorpusEntry(
        "https://docs.docker.com/",
        "A_known_thin",
        ("docker", "documentation"),
        "large shell, thin extraction observed",
    ),
    CorpusEntry("https://hub.docker.com/", "B_js_heavy", ("docker", "hub")),
    CorpusEntry(
        "https://docs.docker.com/search/?q=pull+rate+limits",
        "B_js_heavy",
        ("search", "pull"),
        "client-rendered search page",
    ),
    CorpusEntry(
        "https://nodejs.org/api/modules.html",
        "C_already_pass",
        ("modules", "CommonJS", "ECMAScript"),
        "current reader passes (161k chars)",
    ),
    CorpusEntry(
        "https://www.postgresql.org/support/versioning/",
        "C_already_pass",
        ("version", "support"),
    ),
    CorpusEntry("https://redis.io/docs/latest/", "C_already_pass", ("redis",)),
    CorpusEntry("https://github.com/astral-sh/uv", "D_spa_shell", ("uv", "astral")),
    CorpusEntry(
        "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf",
        "E_complex_body",
        (),
        "PDF contract stability",
    ),
    CorpusEntry(
        "https://github.com/sitemap.xml",
        "F_blocked",
        (),
        "non-HTML resource; observed 406 for our client",
    ),
)


def _heading_recall(text: str, expected: Sequence[str]) -> float | None:
    if not expected:
        return None
    lowered = str(text or "").lower()
    hits = sum(1 for item in expected if item.lower() in lowered)
    return round(hits / len(expected), 3)


def _wigolo_adequacy(artifact: Mapping[str, Any], *, url: str) -> str:
    return classify_read(
        production_chars=len(str(artifact.get("content") or "")),
        html_chars=0,
        best_local_chars=0,
        text=str(artifact.get("content") or ""),
        final_url=str(artifact.get("url") or url),
        requested_url=url,
    )


def run_pass(
    *,
    pass_kind: str,
    output: Path,
    corpus: Sequence[CorpusEntry],
    cache_bust: bool = False,
) -> dict[str, Any]:
    production_reader, html_fetcher, extractors = _live_components()
    backend = WigoloShadowReadBackend()
    bust = time.strftime("%Y%m%d%H%M%S") if cache_bust else ""

    rows: list[dict[str, Any]] = []
    for entry in corpus:
        # A cache-busting query forces a true cold fetch without clearing the
        # daemon's cache; the measured page is otherwise identical.
        request_url = (
            f"{entry.url}{'&' if '?' in entry.url else '?'}shadowcb={bust}"
            if cache_bust
            else entry.url
        )
        row: dict[str, Any] = {
            "url": entry.url,
            "request_url": request_url,
            "class": entry.klass,
            "pass": pass_kind,
            "cache_busted": cache_bust,
        }
        # ---- current reader (production path, unchanged) ----
        started = time.monotonic()
        try:
            current = probe_url(
                entry.url,
                production_reader=production_reader,
                html_fetcher=html_fetcher,
                extractors=extractors,
            )
            row["current"] = {
                "latency_ms": round((time.monotonic() - started) * 1000.0, 1),
                "ok": bool(current.get("production_ok")),
                "chars": int(current.get("production_chars") or 0),
                "html_chars": int(current.get("html_chars") or 0),
                "classification": str(current.get("classification") or ""),
                "method": str(current.get("production_method") or ""),
                "error": str(current.get("production_error") or "")[:120],
                "heading_recall": _heading_recall(
                    str(current.get("production_text") or ""), entry.expected_headings
                ),
            }
        except Exception as exc:  # noqa: BLE001 - shadow must not fail the run
            row["current"] = {
                "latency_ms": round((time.monotonic() - started) * 1000.0, 1),
                "ok": False,
                "chars": 0,
                "classification": "probe_error",
                "error": f"{type(exc).__name__}: {exc}"[:120],
            }

        # ---- wigolo fetch (shadow) ----
        artifact: dict[str, Any]
        try:
            result = backend.fetch(ReadRequest(url=request_url, max_chars=20000))
            artifact = {
                "content": result.content,
                "url": result.url,
                "retrieval_mode": result.retrieval_mode,
                "rendered": result.rendered,
                "cache_hit": result.cache_hit,
                "latency_ms": result.latency_ms,
                "bytes": result.bytes,
                "external_metadata": dict(result.external_metadata),
            }
        except Exception as exc:  # noqa: BLE001 - defence in depth
            artifact = {
                "content": "",
                "url": entry.url,
                "retrieval_mode": "unknown",
                "rendered": None,
                "cache_hit": None,
                "latency_ms": 0.0,
                "bytes": 0,
                "external_metadata": {
                    "state": "transport_error",
                    "detail": f"{type(exc).__name__}: {exc}"[:160],
                },
            }
        classification = _wigolo_adequacy(artifact, url=entry.url)
        row["wigolo"] = {
            "latency_ms": artifact["latency_ms"],
            "chars": len(str(artifact["content"] or "")),
            "bytes": artifact["bytes"],
            "retrieval_mode": artifact["retrieval_mode"],
            "rendered": artifact["rendered"],
            "cache_hit": artifact["cache_hit"],
            "classification": classification,
            "heading_recall": _heading_recall(
                str(artifact["content"] or ""), entry.expected_headings
            ),
            "failure_state": str(
                (artifact.get("external_metadata") or {}).get("state") or ""
            ),
            "http_status": (artifact.get("external_metadata") or {}).get("http_status"),
        }

        current_class = str(row["current"].get("classification") or "")
        row["delta"] = {
            "adequacy_rescued": current_class != "ok" and classification == "ok",
            "current_failed": current_class != "ok",
            "wigolo_failed": classification != "ok",
            "useful_char_gain": max(
                0, row["wigolo"]["chars"] - int(row["current"].get("chars") or 0)
            ),
            "added_latency_ms": round(
                float(row["wigolo"]["latency_ms"])
                - float(row["current"].get("latency_ms") or 0.0),
                1,
            ),
        }
        rows.append(row)

    failing = [row for row in rows if row["delta"]["current_failed"]]
    passing = [row for row in rows if not row["delta"]["current_failed"]]
    rescued = [row for row in failing if row["delta"]["adequacy_rescued"]]
    meaningful_gain = [
        row
        for row in passing
        if row["delta"]["useful_char_gain"] >= SHORT_CHAR_THRESHOLD
        or (
            row["wigolo"]["heading_recall"] is not None
            and row["current"].get("heading_recall") is not None
            and row["wigolo"]["heading_recall"] > row["current"]["heading_recall"]
        )
    ]

    def _median(values: Sequence[float]) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        return round(ordered[len(ordered) // 2], 1)

    summary = {
        "pass": pass_kind,
        "urls": len(rows),
        "current_failed": len(failing),
        "rescued": len(rescued),
        "rescue_rate": round(len(rescued) / len(failing), 3) if failing else None,
        "already_adequate": len(passing),
        "false_escalation_value": len(meaningful_gain),
        "added_latency_ms_median_all": _median(
            [float(row["delta"]["added_latency_ms"]) for row in rows]
        ),
        "added_latency_ms_median_rescued": _median(
            [float(row["delta"]["added_latency_ms"]) for row in rescued]
        ),
        "wigolo_failure_states": sorted(
            {
                row["wigolo"]["failure_state"]
                for row in rows
                if row["wigolo"]["failure_state"]
            }
        ),
        "wigolo_cache_hits": sum(1 for row in rows if row["wigolo"]["cache_hit"] is True),
        "wigolo_modes": sorted({row["wigolo"]["retrieval_mode"] for row in rows}),
    }

    artifact = {
        "schema_version": "wigolo-shadow-bakeoff-v1",
        "diagnostic_only": True,
        "qualification_evidence": False,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "pass": pass_kind,
        "base_url": backend.base_url,
        "rows": rows,
        "summary": summary,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pass", dest="pass_kind", choices=["cold", "warm"], required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--urls", nargs="*", default=None)
    parser.add_argument(
        "--cache-bust",
        action="store_true",
        help="append a unique query to force true cold fetches",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    corpus = CORPUS
    if args.urls:
        wanted = set(args.urls)
        corpus = tuple(entry for entry in CORPUS if entry.url in wanted)
    summary = run_pass(
        pass_kind=args.pass_kind,
        output=args.output,
        corpus=corpus,
        cache_bust=bool(args.cache_bust),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
