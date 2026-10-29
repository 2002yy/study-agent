"""Provider Relevance Routing-1: capture and replay.

Two phases:

- ``--capture`` performs rate-limited real searches for the frozen query set and
  stores, per case and provider, the bounded result metadata (titles, URLs,
  source labels, latency, status, error codes). No model is called.
- ``--replay`` (the default) reads that capture and simulates four routing
  strategies offline: E0 first non-empty provider, E1 merge + dedupe, E2 merge +
  relevance ranking, E3 try another provider only when E0's top-3 has no
  relevant result.

Relevance here is a transparent keyword rule over multi-character anchors and
task-focus tokens. It measures retrieval relevance only; it is not evidence
support, not version correctness, and it is not the repository's
``source_assessment`` score (that score is not used as a routing gate because its
Chinese single-character overlap would call a dictionary page relevant).
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import statistics
import sys
import time
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

DEFAULT_QUERIES = (
    REPO_ROOT / "tests" / "fixtures" / "provider_routing" / "qp1c_queries_v1.json"
)
DEFAULT_CAPTURE = REPO_ROOT / "docs" / "research_quality" / "PROVIDER_ROUTING_CAPTURE.json"
DEFAULT_REPLAY = REPO_ROOT / "docs" / "research_quality" / "PROVIDER_ROUTING_REPLAY.json"

PROVIDERS = ("bing", "ddg")
CAPTURE_MODES = ("fallback", "bing", "ddg")
PROVIDER_ENV: dict[str, dict[str, str]] = {
    "bing": {
        "WEB_ENABLE_SEARXNG": "false",
        "WEB_ENABLE_BING_RSS": "true",
        "WEB_ENABLE_DUCKDUCKGO": "false",
    },
    "ddg": {
        "WEB_ENABLE_SEARXNG": "false",
        "WEB_ENABLE_BING_RSS": "false",
        "WEB_ENABLE_DUCKDUCKGO": "true",
    },
}
ENV_KEYS = ("WEB_ENABLE_SEARXNG", "WEB_ENABLE_BING_RSS", "WEB_ENABLE_DUCKDUCKGO")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def _apply(mode: str) -> None:
    for key, value in PROVIDER_ENV[mode].items():
        os.environ[key] = value


def _anchor_tokens(case: dict[str, Any]) -> list[str]:
    # Single-character anchors are what made a dictionary entry look relevant.
    return [token for token in case["anchors"] if len(token.strip()) > 1]


def verdict(item: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    surface = " ".join(
        str(item.get(key) or "") for key in ("title", "url", "snippet")
    ).casefold()
    anchors = [token.casefold() for token in _anchor_tokens(case)]
    focus = [token.casefold() for token in case["focus"]]
    anchor_hits = [token for token in anchors if token in surface]
    focus_hits = [token for token in focus if token in surface]
    relevant = len(anchor_hits) >= 2 or (len(anchor_hits) >= 1 and bool(focus_hits))
    return {
        "relevant": relevant,
        "anchor_hits": anchor_hits,
        "focus_hits": focus_hits,
    }


def _dedupe(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for item in results:
        url = str(item.get("url") or "")
        if not url or url in seen:
            continue
        seen.add(url)
        rows.append(item)
    return rows


def _query_fingerprint(cases: list[dict[str, Any]]) -> str:
    """Content identity of the query set: ids, text and evaluation anchors."""

    canonical = [
        {
            "id": case["id"],
            "question": case["question"],
            "query": case["query"],
            "anchors": list(case["anchors"]),
            "focus": list(case["focus"]),
        }
        for case in cases
    ]
    payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def capture(
    *, queries: Path, output: Path, limit: int, pace_ddg: float, pace_other: float
) -> dict[str, Any]:
    load_dotenv(REPO_ROOT / ".env")
    from src.web.tool_gateway import GeneralWebGateway

    document = json.loads(queries.read_text(encoding="utf-8"))
    original = {key: os.environ.get(key) for key in ENV_KEYS}
    production = {key: os.environ.get(key) for key in ENV_KEYS}
    artifact: dict[str, Any] = {
        "schema_version": "provider-routing-capture-v1",
        "started_at": _utc_now(),
        "queries_fixture": _display_path(queries),
        "query_set_version": document.get("schema_version"),
        "query_set_fingerprint": _query_fingerprint(document["cases"]),
        "case_ids": [case["id"] for case in document["cases"]],
        "limit": limit,
        "cases": [],
        "scope": {"stores_page_bodies": False, "uses_model": False},
        "production_flags": {
            key: os.environ.get(key)
            for key in (
                "WEB_ENABLE_SEARXNG",
                "WEB_ENABLE_BING_RSS",
                "WEB_ENABLE_DUCKDUCKGO",
                "SEARXNG_BASE_URL",
                "SEARXNG_ALLOW_LOOPBACK",
                "WEB_DUCKDUCKGO_PROXY",
            )
        },
        "provider_env": PROVIDER_ENV,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        gateway = GeneralWebGateway()
        for case in document["cases"]:
            record: dict[str, Any] = {
                "id": case["id"],
                "query": case["query"],
                "providers": {},
            }
            for mode in CAPTURE_MODES:
                if mode == "fallback":
                    _restore_production(production)
                else:
                    _apply(mode)
                started = time.monotonic()
                payload = _search_once(gateway, case["query"], limit=limit)
                elapsed = round(time.monotonic() - started, 2)
                results = [item for item in payload.get("results", []) if item.get("url")]
                record["providers"][mode] = {
                    "status": payload.get("status"),
                    "elapsed": elapsed,
                    "provider_errors": list(payload.get("provider_errors", [])),
                    "providers_attempted": list(payload.get("providers_attempted", [])),
                    "results": [
                        {
                            "title": str(item.get("title") or "")[:200],
                            "url": str(item.get("url") or "")[:300],
                            "source": str(item.get("source") or "")[:60],
                            "snippet": str(item.get("snippet") or "")[:240],
                            "snippet_chars": len(str(item.get("snippet") or "")),
                        }
                        for item in results
                    ],
                }
                time.sleep(pace_ddg if mode == "ddg" else pace_other)
            artifact["cases"].append(record)
            output.write_text(
                json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"[capture] {record['id']}: " + ", ".join(
                f"{mode}={len(record['providers'][mode]['results'])}"
                for mode in CAPTURE_MODES
            ), flush=True)
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    artifact["completed_at"] = _utc_now()
    output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return artifact


def _search_once(
    gateway: Any, query: str, *, limit: int
) -> dict[str, Any]:
    """Call the production search path once and keep its failure report.

    A live experiment must not die because one provider throws: the gateway
    already turns its own provider errors into codes, and anything left
    (an unexpected crash inside the gateway) is recorded and reported the
    same way instead of losing the whole case.
    """

    try:
        payload = gateway.search_exact(query, max_results=limit)
    except Exception as exc:  # noqa: BLE001 - experiment resilience
        return {
            "status": "unavailable",
            "reason": "gateway_exception",
            "results": [],
            "provider_errors": [f"{type(exc).__name__}:{exc}"],
            "providers_attempted": [],
        }
    return payload


def _fallback_results(providers: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """E0 semantics: the first engine with a non-empty pool, in provider order."""

    first_mode = next((mode for mode in PROVIDERS if providers.get(mode, {}).get("results")), None)
    if first_mode:
        return providers[first_mode]["results"]
    return []


def _restore_production(production: dict[str, str | None]) -> None:
    """Restore the provider flags the real ``.env``/process had.

    Popping them instead would silently disable a provider that production has
    enabled, and the fallback arm would no longer be production.
    """

    for key, value in production.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _rank(results: list[dict[str, Any]], case: dict[str, Any]) -> list[dict[str, Any]]:
    """E2: rank a merged pool with the production source scorer, not the eval.

    Using `verdict()` here would rank by the very signal the metrics measure, so
    E2 would always score perfectly. `assess_sources` is the repository's own
    relevance scorer; its Chinese single-character overlap is a known weakness,
    which is exactly why it is reported rather than hidden.
    """

    from src.web.source_assessment import assess_sources

    assessed, _rejected = assess_sources(results, canonical_query=case["question"])
    scored: list[tuple[float, int, dict[str, Any]]] = []
    for index, record in enumerate(assessed):
        item = record.get("item") if isinstance(record, dict) else None
        if not isinstance(item, dict) or not item.get("url"):
            continue
        assessment = record.get("assessment") if isinstance(record, dict) else {}
        score = float((assessment or {}).get("relevance") or 0.0)
        scored.append((score, index, item))
    ranked = [item for _score, _index, item in sorted(scored, key=lambda row: (-row[0], row[1]))]
    # Anything the assessor dropped keeps its original relative order at the end.
    known = {str(item.get("url") or "") for item in ranked}
    ranked.extend(item for item in results if str(item.get("url") or "") not in known)
    return ranked


def _rank_production(results: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    """The reranker production actually uses for the merge strategy."""

    from src.web.tool_gateway import _rank_merged

    return _rank_merged(results, query)


def _interleave(first: list[dict[str, Any]], second: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Round-robin two engine orders, deduped by URL.

    Keeps each engine's native ranking as a prior (position 1 of the better
    engine stays position 1) while still granting the second engine's rows a
    place in the delivered window.
    """

    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index in range(max(len(first), len(second))):
        for pool in (first, second):
            if index >= len(pool):
                continue
            item = pool[index]
            url = str(item.get("url") or "")
            if not url or url in seen:
                continue
            seen.add(url)
            merged.append(item)
    return merged


def _rank_bigram(results: list[dict[str, Any]], case: dict[str, Any]) -> list[dict[str, Any]]:
    """Candidate rerank: score pool rows by runtime query n-gram coverage.

    Uses only query/question text available at runtime (never the evaluation
    anchors), and replaces the CJK single-character token overlap in
    ``assess_sources`` with CJK bigrams + whole CJK runs + ascii words:
    a row that merely contains one of the query's characters no longer scores
    as relevant. The original pool order is the stable tie-break, so this is a
    local, explainable reordering of the same rows.
    """

    grams = _query_grams(case["query"]) | _query_grams(case.get("question", ""))
    stop = {"www", "com", "org", "net", "http", "https", "htm", "html"}
    scored: list[tuple[float, int, dict[str, Any]]] = []
    for index, item in enumerate(results):
        surface = " ".join(
            str(item.get(key) or "") for key in ("title", "url", "snippet")
        ).casefold()
        surface_tokens = set(
            token for token in re.findall(r"[a-z0-9]+", surface) if token not in stop
        )
        covered = sum(
            1 for gram in grams if (gram in surface if len(gram) >= 2 else gram in surface_tokens)
        )
        score = covered / len(grams) if grams else 0.0
        scored.append((score, index, item))
    return [item for _score, _index, item in sorted(scored, key=lambda row: (-row[0], row[1]))]


def _first_relevant_rank(results: list[dict[str, Any]], case: dict[str, Any]) -> int | None:
    for index, item in enumerate(results, start=1):
        if verdict(item, case)["relevant"]:
            return index
    return None


EVALUATION_WINDOW = 6
GATE_THRESHOLD = 0.5
GATE_STRATEGIES = ("assessor", "ngram")


def _assessor_scores(results: list[dict[str, Any]], case: dict[str, Any]) -> dict[str, float]:
    from src.web.source_assessment import assess_sources

    assessed, _rejected = assess_sources(results, canonical_query=case["question"])
    scores: dict[str, float] = {}
    for record in assessed:
        item = record.get("item") if isinstance(record, dict) else None
        if not isinstance(item, dict):
            continue
        assessment = record.get("assessment") if isinstance(record, dict) else {}
        scores[str(item.get("url") or "")] = float((assessment or {}).get("relevance") or 0.0)
    return scores


def _query_grams(text: str) -> set[str]:
    """Segmentation-free query units: latin words and CJK bigrams.

    Only the query text is used, so this is available at runtime for a real
    question - unlike the curated anchors used by the evaluation rule.
    """

    stop = {"the", "and", "for", "with", "this", "that", "latest", "version"}
    grams: set[str] = set()
    for part in re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]+", text.casefold()):
        if part.isascii():
            if len(part) >= 3 and part not in stop:
                grams.add(part)
        else:
            grams.update(part[index : index + 2] for index in range(len(part) - 1))
    return grams


def _gate_sufficient(
    results: list[dict[str, Any]], case: dict[str, Any], *, strategy: str
) -> dict[str, Any]:
    """Decide whether the first provider is good enough, with runtime signals only.

    This must never call `verdict()`: that is the evaluation rule, and using it
    here would let E3 peek at the answer sheet. Two production-available signals
    are measured instead of one tuned threshold:

    - ``assessor``: the repository's own source relevance for the first three.
    - ``ngram``: query n-grams covered by at least one of the first three.
    """

    head = results[:3]
    if strategy == "assessor":
        scores = _assessor_scores(head, case)
        best = max(scores.values(), default=0.0)
        return {
            "strategy": "assessor",
            "threshold": GATE_THRESHOLD,
            "best_relevance": round(best, 3),
            "sufficient": best >= GATE_THRESHOLD,
        }
    if strategy == "ngram":
        grams = _query_grams(case["query"])
        best = 0
        for item in head:
            surface = " ".join(
                str(item.get(key) or "") for key in ("title", "url", "snippet")
            ).casefold()
            best = max(best, sum(1 for gram in grams if gram in surface))
        return {
            "strategy": "ngram",
            "threshold": 2,
            "best_overlap": best,
            "sufficient": best >= 2,
        }
    raise ValueError(f"unknown gate strategy: {strategy}")


def _metrics(
    results: list[dict[str, Any]], case: dict[str, Any], *, window: int = EVALUATION_WINDOW
) -> dict[str, Any]:
    # Metrics always use the first six results; a smaller display limit must not
    # silently redefine "hit@6".
    head = results[:window]
    rank = _first_relevant_rank(head, case)
    return {
        "window": window,
        "relevant_rank": rank,
        "hit_at_3": bool(rank and rank <= 3),
        "hit_at_6": bool(rank and rank <= min(6, window)),
        "mrr_at_6": round(1 / rank, 3) if rank and rank <= min(6, window) else 0.0,
        "relevant_count": sum(1 for item in head if verdict(item, case)["relevant"]),
    }


def _random_window_hit(
    results: list[dict[str, Any]], case: dict[str, Any], *, window: int = EVALUATION_WINDOW
) -> float:
    """Chance a random ``window`` of the same pool contains a relevant row.

    This is the control for "the pool got bigger": if the reranked arm cannot
    beat a random draw from the identical pool, the gain is coverage, not
    ranking. Hypergeometric, without replacement.
    """

    pool = results[:12]
    relevant = sum(1 for item in pool if verdict(item, case)["relevant"])
    total = len(pool)
    size = min(window, total)
    if relevant == 0 or total == 0:
        return 0.0
    if relevant >= total - size + 1:
        return 1.0
    return round(1 - math.comb(total - relevant, size) / math.comb(total, size), 4)


def replay_with_pools(
    *,
    capture_path: Path,
    output: Path,
    limit: int,
    queries_path: Path | None = None,
    read_check_cases: int = 0,
) -> dict[str, Any]:
    capture_doc = json.loads(capture_path.read_text(encoding="utf-8"))
    cases = {row["id"]: row for row in capture_doc["cases"]}
    queries_path = queries_path or DEFAULT_QUERIES
    queries = json.loads(queries_path.read_text(encoding="utf-8"))

    # Fail closed when the capture and the query set are not the same experiment.
    if capture_doc.get("query_set_version") != queries.get("schema_version"):
        raise ValueError("capture_query_set_version_mismatch")
    expected_ids = [case["id"] for case in queries["cases"]]
    if capture_doc.get("case_ids") != expected_ids:
        raise ValueError("capture_case_ids_mismatch")
    if capture_doc.get("query_set_fingerprint") != _query_fingerprint(queries["cases"]):
        raise ValueError("capture_query_set_fingerprint_mismatch")
    if limit < EVALUATION_WINDOW:
        raise ValueError("limit_below_evaluation_window")

    artifact: dict[str, Any] = {
        "schema_version": "provider-routing-replay-v2",
        "started_at": _utc_now(),
        "capture": _display_path(capture_path),
        "limit": limit,
        "evaluation_window": EVALUATION_WINDOW,
        "latency_definition": (
            "sum of measured provider request durations; excludes pacing sleeps and "
            "client-side processing"
        ),
        "gate": {
            "signal": "source_assessment relevance of the first three results",
            "threshold": GATE_THRESHOLD,
            "uses_evaluation_rule": False,
        },
        "strategies": {},
        "cases": [],
        "relevance_rule": {
            "anchors": "multi-character only; single-character anchors are ignored",
            "relevant": ">=2 anchors, or >=1 anchor plus a focus token",
            "not_measured": ["evidence_support", "version_correctness", "answer_quality"],
        },
        "arms": {
            "A_fallback": (
                "production path as captured: whatever the configured providers "
                "delivered in their real order (this run: Bing only, because the "
                "SearXNG instance was not configured and DuckDuckGo was "
                "unreachable from this network)"
            ),
            "B_merge": "Bing pool followed by DuckDuckGo pool, deduped, no rerank",
            "D_ddg_first": "DuckDuckGo pool followed by Bing pool, deduped, no rerank",
            "C_rerank": "B plus the production _rank_merged scorer (assess_sources on the planned query)",
            "C_bigram": "B plus the candidate query-ngram coverage ranking",
        },
    }
    for case in queries["cases"]:
        recorded = cases.get(case["id"])
        if recorded is None:
            continue
        recorded_providers = recorded.get("providers", {})
        providers = {mode: recorded_providers[mode] for mode in PROVIDERS if mode in recorded_providers}
        row: dict[str, Any] = {"id": case["id"], "query": case["query"], "providers": recorded_providers, "strategies": {}}

        # E0: first provider with any result.
        e0_mode = next((mode for mode in PROVIDERS if providers[mode]["results"]), None)
        e0_results = providers[e0_mode]["results"] if e0_mode else []
        e0_calls = PROVIDERS.index(e0_mode) + 1 if e0_mode else len(PROVIDERS)
        e0_latency = sum(
            providers[mode]["elapsed"] for mode in PROVIDERS[:e0_calls]
        )
        row["strategies"]["E0"] = {
            "providers": PROVIDERS[:e0_calls],
            "results": len(e0_results),
            "provider_calls": e0_calls,
            "latency": round(e0_latency, 2),
            "top_url": str(e0_results[0].get("url") or "") if e0_results else "",
            **_metrics(e0_results, case),
        }

        # E1: all providers, merge + dedupe, keep provider order.
        merged = _dedupe([*providers["bing"]["results"], *providers["ddg"]["results"]])
        row["strategies"]["E1"] = {
            "providers": list(PROVIDERS),
            "results": len(merged),
            "provider_calls": len(PROVIDERS),
            "latency": round(sum(providers[mode]["elapsed"] for mode in PROVIDERS), 2),
            "top_url": str(merged[0].get("url") or "") if merged else "",
            **_metrics(merged, case),
        }

        # E2: merge + relevance ranking.
        ranked = _rank(merged, case)
        row["strategies"]["E2"] = {
            "providers": list(PROVIDERS),
            "results": len(ranked),
            "provider_calls": len(PROVIDERS),
            "latency": round(sum(providers[mode]["elapsed"] for mode in PROVIDERS), 2),
            "top_url": str(ranked[0].get("url") or "") if ranked else "",
            **_metrics(ranked, case),
        }

        # E3: E0, then the next provider only when a gate says the first one is
        # not good enough. Two production-available gates are reported; the
        # evaluation rule is never consulted here.
        for strategy in GATE_STRATEGIES:
            gate = _gate_sufficient(e0_results, case, strategy=strategy)
            if e0_mode and e0_mode != PROVIDERS[-1] and not gate["sufficient"]:
                extra_mode = PROVIDERS[PROVIDERS.index(e0_mode) + 1]
                extra = providers[extra_mode]["results"]
                e3_results = _rank(_dedupe([*e0_results, *extra]), case)
                e3_calls = e0_calls + 1
                e3_latency = e0_latency + providers[extra_mode]["elapsed"]
                e3_triggered = True
            else:
                e3_results = e0_results
                e3_calls = e0_calls
                e3_latency = e0_latency
                e3_triggered = False
            row["strategies"][f"E3_{strategy}"] = {
                "providers": list(PROVIDERS[:e3_calls]),
                "results": len(e3_results),
                "provider_calls": e3_calls,
                "latency": round(e3_latency, 2),
                "triggered_extra_provider": e3_triggered,
                "gate": gate,
                "top_url": str(e3_results[0].get("url") or "") if e3_results else "",
                **_metrics(e3_results, case),
            }

        # Search-1 arms: A = production fallback snapshot; B = merge only; C =
        # reranked. B and C consume the same raw pool, so any coverage gain is
        # attributable to the merge, and any extra gain to the rerank alone.
        fallback_provided = "fallback" in recorded_providers
        if fallback_provided:
            fallback = recorded_providers["fallback"]
            a_results = list(fallback["results"])
            a_latency = float(fallback.get("elapsed") or 0.0)
            a_providers = list(fallback.get("providers_attempted", []))
            a_calls = len(a_providers)
        else:
            a_results = list(e0_results)
            a_latency = e0_latency
            a_providers = list(PROVIDERS[:e0_calls])
            a_calls = e0_calls
        row["strategies"]["A_fallback"] = {
            "providers": a_providers,
            "results": len(a_results),
            "provider_calls": a_calls,
            "latency": round(a_latency, 2),
            "top_url": str(a_results[0].get("url") or "") if a_results else "",
            **_metrics(a_results, case),
        }

        b_results = [item for item in merged if item.get("url")]
        row["strategies"]["B_merge"] = {
            "providers": list(PROVIDERS),
            "results": len(b_results),
            "provider_calls": len(PROVIDERS),
            "latency": round(sum(providers[mode]["elapsed"] for mode in PROVIDERS), 2),
            "top_url": str(b_results[0].get("url") or "") if b_results else "",
            "pool_relevant": sum(1 for item in b_results if verdict(item, case)["relevant"]),
            "random_window_hit": _random_window_hit(b_results, case),
            **_metrics(b_results, case),
        }

        # D: the second engine's own order, deduped, no rerank. This isolates
        # "the engine already ranks well" from "the reranker improved it": if D
        # alone matches C, the merge does not need the reranker at all.
        d_results = _dedupe([*providers["ddg"]["results"], *providers["bing"]["results"]])
        row["strategies"]["D_ddg_first"] = {
            "providers": list(PROVIDERS),
            "results": len(d_results),
            "provider_calls": len(PROVIDERS),
            "latency": round(sum(providers[mode]["elapsed"] for mode in PROVIDERS), 2),
            "top_url": str(d_results[0].get("url") or "") if d_results else "",
            **_metrics(d_results, case),
        }

        c_ranked = _rank_production(merged, case["query"])
        row["strategies"]["C_rerank"] = {
            "providers": list(PROVIDERS),
            "results": len(c_ranked),
            "provider_calls": len(PROVIDERS),
            "latency": round(sum(providers[mode]["elapsed"] for mode in PROVIDERS), 2),
            "top_url": str(c_ranked[0].get("url") or "") if c_ranked else "",
            **_metrics(c_ranked, case),
        }
        c_bigram = _rank_bigram(merged, case)
        row["strategies"]["C_bigram"] = {
            "providers": list(PROVIDERS),
            "results": len(c_bigram),
            "provider_calls": len(PROVIDERS),
            "latency": round(sum(providers[mode]["elapsed"] for mode in PROVIDERS), 2),
            "top_url": str(c_bigram[0].get("url") or "") if c_bigram else "",
            **_metrics(c_bigram, case),
        }
        f_results = _interleave(providers["ddg"]["results"], providers["bing"]["results"])
        row["strategies"]["F_interleave"] = {
            "providers": list(PROVIDERS),
            "results": len(f_results),
            "provider_calls": len(PROVIDERS),
            "latency": round(sum(providers[mode]["elapsed"] for mode in PROVIDERS), 2),
            "top_url": str(f_results[0].get("url") or "") if f_results else "",
            **_metrics(f_results, case),
        }

        artifact["cases"].append(row)

    artifact["completed_at"] = _utc_now()
    artifact["summary"] = _summarise(artifact["cases"], queries["cases"])
    if read_check_cases > 0:
        artifact["read_check"] = _read_check(artifact["cases"][:read_check_cases])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return artifact


def replay(
    *,
    capture_path: Path,
    output: Path,
    limit: int,
    queries_path: Path | None = None,
    read_check_cases: int = 0,
) -> dict[str, Any]:
    """Replay with the raw provider pools kept on every row.

    Keeping the pools on the row lets offline assertions prove B/C share one
    raw pool; the artifact stays self-describing because each row carries the
    two pools it was computed from.
    """

    return replay_with_pools(
        capture_path=capture_path,
        output=output,
        limit=limit,
        queries_path=queries_path,
        read_check_cases=read_check_cases,
    )


def _read_check(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Attempt a real page read of each case's top result (``--read-check``).

    A found source is only useful if it can actually be read: this measures the
    read-success rate, on the top-1 URL of ``A_fallback`` and ``C_bigram``.
    """

    load_dotenv(REPO_ROOT / ".env")
    from src.web.tool_gateway import GeneralWebGateway

    gateway = GeneralWebGateway()
    rows: list[dict[str, Any]] = []
    for case in cases:
        strategies = case.get("strategies", {})
        for arm_name in ("A_fallback", "C_bigram"):
            row = strategies.get(arm_name)
            if not row:
                continue
            url = str(row.get("top_url") or "").strip()
            entry: dict[str, Any] = {"id": case["id"], "arm": arm_name, "url": url, "ok": False, "error": ""}
            if url:
                started = time.monotonic()
                try:
                    result = gateway.read(url, timeout=6.0)
                    entry["ok"] = bool(result.get("ok"))
                    entry["error"] = str(result.get("error") or "")
                    entry["chars"] = len(str(result.get("content") or ""))
                except Exception as exc:
                    entry["error"] = f"{type(exc).__name__}:{exc}"
                entry["elapsed"] = round(time.monotonic() - started, 2)
            rows.append(entry)
    ok = sum(1 for row in rows if row["ok"])
    return {
        "attempts": len(rows),
        "succeeded": ok,
        "success_rate": round(ok / len(rows), 3) if rows else 0.0,
        "rows": rows,
    }


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1)))))
    return round(ordered[index], 2)


def _summarise(
    cases: list[dict[str, Any]], query_cases: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    summary: dict[str, Any] = {"cases": len(cases), "strategies": {}}
    names = ("E0", "E1", "E2", "A_fallback", "B_merge", "D_ddg_first", "C_rerank", "C_bigram", "F_interleave") + tuple(
        f"E3_{strategy}" for strategy in GATE_STRATEGIES
    )
    for name in names:
        rows = [case["strategies"][name] for case in cases if name in case.get("strategies", {})]
        if not rows:
            continue
        latencies = [row["latency"] for row in rows]
        summary["strategies"][name] = {
            "cases": len(rows),
            "hit_at_3": sum(1 for row in rows if row["hit_at_3"]),
            "hit_at_6": sum(1 for row in rows if row["hit_at_6"]),
            "mean_mrr_at_6": round(
                sum(row["mrr_at_6"] for row in rows) / len(rows), 3
            ),
            "total_relevant": sum(row["relevant_count"] for row in rows),
            "provider_calls": sum(row["provider_calls"] for row in rows),
            "latency_p50": _percentile(latencies, 0.5),
            "latency_p95": _percentile(latencies, 0.95),
            "latency_mean": round(statistics.fmean(latencies), 2) if latencies else None,
        }

    categories: dict[str, dict[str, Any]] = {}
    if query_cases:
        category_by_id = {case["id"]: case.get("category", "uncategorized") for case in query_cases}
        for case in cases:
            category = category_by_id.get(case["id"], "uncategorized")
            entry = categories.setdefault(category, {})
            for name in ("A_fallback", "B_merge", "C_rerank", "C_bigram"):
                row = case.get("strategies", {}).get(name)
                if row is None:
                    continue
                stats = entry.setdefault(
                    name, {"cases": 0, "hit_at_3": 0, "hit_at_6": 0, "mrr_at_6": 0.0}
                )
                stats["cases"] += 1
                stats["hit_at_3"] += int(row["hit_at_3"])
                stats["hit_at_6"] += int(row["hit_at_6"])
                stats["mrr_at_6"] += row["mrr_at_6"]
        for entry in categories.values():
            for stats in entry.values():
                if stats["cases"]:
                    stats["mean_mrr_at_6"] = round(stats["mrr_at_6"] / stats["cases"], 3)
                    del stats["mrr_at_6"]
        summary["categories"] = categories

    # A_fallback → C_* movement: which cases gained or lost a Hit@6.
    moved: dict[str, dict[str, list[str]]] = {}
    for target in ("C_rerank", "C_bigram"):
        improved: list[str] = []
        regressed: list[str] = []
        for case in cases:
            strategies = case.get("strategies", {})
            if target not in strategies or "A_fallback" not in strategies:
                continue
            before = strategies["A_fallback"]["hit_at_6"]
            after = strategies[target]["hit_at_6"]
            if after and not before:
                improved.append(case["id"])
            elif before and not after:
                regressed.append(case["id"])
        moved[target] = {"improved": improved, "regressed": regressed}
    if moved:
        summary["improved_regressed_vs_A"] = moved
    pool_rows = [
        case["strategies"]["B_merge"]
        for case in cases
        if "B_merge" in case.get("strategies", {})
    ]
    if pool_rows:
        summary["coverage"] = {
            "definition": (
                "pool_relevant counts rows matching the evaluation rule anywhere in "
                "the merged pool (up to 12); coverage_cases counts cases where the "
                "answer exists somewhere in the pool regardless of rank"
            ),
            "coverage_cases": sum(1 for row in pool_rows if row["pool_relevant"] > 0),
            "pool_rows": sum(row["results"] for row in pool_rows),
            "random_window_hit_rate": round(
                sum(row["random_window_hit"] for row in pool_rows) / len(pool_rows), 3
            ),
        }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", action="store_true", help="run the real, rate-limited searches")
    parser.add_argument("--input", type=Path, default=DEFAULT_CAPTURE)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--queries", type=Path, default=DEFAULT_QUERIES)
    parser.add_argument("--limit", type=int, default=6)
    parser.add_argument("--pace-ddg", type=float, default=6.0)
    parser.add_argument("--pace-other", type=float, default=1.0)
    parser.add_argument(
        "--read-check", type=int, default=0, metavar="N",
        help="also attempt a real page read of the top result for the first N cases",
    )
    args = parser.parse_args()

    if args.capture:
        artifact = capture(
            queries=args.queries.resolve(),
            output=(args.output or DEFAULT_CAPTURE).resolve(),
            limit=max(1, min(args.limit, 12)),
            pace_ddg=max(0.0, args.pace_ddg),
            pace_other=max(0.0, args.pace_other),
        )
        print(json.dumps({"cases": len(artifact["cases"])}, sort_keys=True))
        return 0

    artifact = replay(
        capture_path=(args.input).resolve(),
        output=(args.output or DEFAULT_REPLAY).resolve(),
        limit=max(1, min(args.limit, 12)),
        queries_path=args.queries.resolve(),
        read_check_cases=max(0, args.read_check),
    )
    summary = artifact["summary"]
    compact: dict[str, Any] = {name: stats for name, stats in summary["strategies"].items()}
    if "categories" in summary:
        compact["categories"] = summary["categories"]
    if "improved_regressed_vs_A" in summary:
        compact["improved_regressed_vs_A"] = summary["improved_regressed_vs_A"]
    if "coverage" in summary:
        compact["coverage"] = summary["coverage"]
    if "read_check" in artifact:
        check = artifact["read_check"]
        compact["read_check"] = {
            "attempts": check["attempts"],
            "succeeded": check["succeeded"],
            "success_rate": check["success_rate"],
        }
    print(json.dumps(compact, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
