"""§47 fetch retry/backoff characterization (no runtime change).

Measures, per URL, the fetch layer's real failure/retry behaviour under a
bounded policy (up to K attempts, small backoff):

    first_attempt_failure_rate
    retry_success_rate          (success on attempt >= 2 after a first failure)
    attempts_to_success         (histogram)
    final_success_rate          (success within K attempts)
    latency_ms                  (success latency, total-with-retries)
    failure_signature_counts    (e.g. URLError 10054)

Subjects: the flaky docs.docker.com pages plus one control URL. Diagnostic
only; nothing about the production reader changes.
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

SCHEMA_VERSION = "fetch-retry-characterization-v1"
DEFAULT_URLS = (
    "https://docs.docker.com/docker-hub/usage/pulls/",
    "https://docs.docker.com/docker-hub/usage/",
    "https://docs.docker.com/desktop/setup/install/windows-install/",
)
CONTROL_URL = "https://www.postgresql.org/support/versioning/"
DEFAULT_TRIALS = 6
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BACKOFF_SECONDS = (1.0, 2.0)


def _signature(reason: str) -> str:
    text = str(reason or "")
    if not text:
        return "ok"
    win = re.search(r"WinError (\d+)", text)
    if win:
        return f"WinError{win.group(1)}"
    return re.sub(r"\s+", " ", text)[:60]


@dataclass
class Trial:
    attempts: int = 0
    success: bool = False
    final_reason: str = ""
    attempt_latencies_ms: list[int] = field(default_factory=list)
    signatures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempts": self.attempts,
            "success": self.success,
            "final_reason": self.final_reason,
            "attempt_latencies_ms": list(self.attempt_latencies_ms),
            "signatures": list(self.signatures),
            "total_latency_ms": sum(self.attempt_latencies_ms),
        }


def run_trial(
    url: str,
    *,
    fetch: Callable[[str], tuple[bool, str, int]],
    max_attempts: int,
    backoff_seconds: Sequence[float],
    sleep: Callable[[float], None] = time.sleep,
) -> Trial:
    """One bounded trial; ``fetch`` returns (ok, reason, latency_ms)."""

    trial = Trial()
    for attempt in range(1, max(1, int(max_attempts)) + 1):
        ok, reason, latency_ms = fetch(url)
        trial.attempts = attempt
        trial.attempt_latencies_ms.append(int(latency_ms))
        trial.signatures.append(_signature(reason))
        if ok:
            trial.success = True
            trial.final_reason = ""
            return trial
        trial.final_reason = str(reason or "")[:200]
        if attempt < max_attempts and backoff_seconds:
            sleep(backoff_seconds[min(attempt - 1, len(backoff_seconds) - 1)])
    return trial


def summarize_trials(trials: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    total = len(trials)
    if total == 0:
        return {"trials": 0}
    first_failures = [row for row in trials if not bool(row.get("signatures", ["ok"])[0] == "ok")]
    retry_successes = [
        row
        for row in first_failures
        if row.get("success") and int(row.get("attempts") or 0) >= 2
    ]
    final_successes = [row for row in trials if row.get("success")]
    histogram: dict[str, int] = {}
    for row in final_successes:
        key = str(int(row.get("attempts") or 0))
        histogram[key] = histogram.get(key, 0) + 1
    signatures: dict[str, int] = {}
    for row in trials:
        for signature in row.get("signatures") or []:
            if signature != "ok":
                signatures[signature] = signatures.get(signature, 0) + 1
    success_latencies = sorted(
        int(row.get("attempt_latencies_ms", [0])[-1]) for row in final_successes
    )
    total_latencies = sorted(int(row.get("total_latency_ms") or 0) for row in trials)
    return {
        "trials": total,
        "first_attempt_failures": len(first_failures),
        "first_attempt_failure_rate": round(len(first_failures) / total, 3),
        "retry_successes": len(retry_successes),
        "retry_success_rate_given_first_failure": (
            round(len(retry_successes) / len(first_failures), 3) if first_failures else None
        ),
        "attempts_to_success": dict(sorted(histogram.items())),
        "final_successes": len(final_successes),
        "final_success_rate": round(len(final_successes) / total, 3),
        "failure_signature_counts": dict(sorted(signatures.items())),
        "single_attempt_success_latency_ms_p50": (
            success_latencies[len(success_latencies) // 2] if success_latencies else None
        ),
        "trial_total_latency_ms_p50": total_latencies[len(total_latencies) // 2],
        "trial_total_latency_ms_max": total_latencies[-1],
    }


def _live_fetch() -> Callable[[str], tuple[bool, str, int]]:
    from src.news.article_fetcher import _fetch_html_payload

    def fetch(url: str) -> tuple[bool, str, int]:
        started = time.monotonic()
        try:
            html, _final_url, _content_type, reason = _fetch_html_payload(
                url, timeout=12, max_bytes=350_000
            )
        except Exception as exc:
            return False, f"exception:{type(exc).__name__}:{exc}", int(
                (time.monotonic() - started) * 1000
            )
        latency = int((time.monotonic() - started) * 1000)
        if reason or not html:
            return False, reason or "empty_response", latency
        return True, "", latency

    return fetch


def run_probe(
    *,
    output_path: Path,
    urls: Sequence[str] = DEFAULT_URLS,
    trials: int = DEFAULT_TRIALS,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    fetch: Callable[[str], tuple[bool, str, int]] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    include_control: bool = True,
) -> dict[str, Any]:
    load_dotenv(REPO_ROOT / ".env")
    fetcher = fetch or _live_fetch()
    subjects = list(urls)
    if include_control and CONTROL_URL not in subjects:
        subjects.append(CONTROL_URL)
    results: list[dict[str, Any]] = []
    for url in subjects:
        url_trials: list[Trial] = []
        for index in range(max(1, int(trials))):
            trial = run_trial(
                url,
                fetch=fetcher,
                max_attempts=max_attempts,
                backoff_seconds=DEFAULT_BACKOFF_SECONDS,
                sleep=sleep,
            )
            url_trials.append(trial)
            print(
                f"{url[:70]} trial{index + 1}: success={trial.success} "
                f"attempts={trial.attempts} signatures={trial.signatures}"
            )
        rows = [trial.to_dict() for trial in url_trials]
        results.append({"url": url, "trials": rows, "summary": summarize_trials(rows)})
    payload = {
        "schema_version": SCHEMA_VERSION,
        "diagnostic_only": True,
        "qualification_evidence": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "trials_per_url": max(1, int(trials)),
        "max_attempts": max(1, int(max_attempts)),
        "backoff_seconds": list(DEFAULT_BACKOFF_SECONDS),
        "results": results,
        "summary": {
            row["url"]: row["summary"]["final_success_rate"] for row in results
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--urls", nargs="*", default=list(DEFAULT_URLS))
    parser.add_argument("--trials", type=int, default=DEFAULT_TRIALS)
    parser.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS)
    parser.add_argument("--no-control", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    payload = run_probe(
        output_path=args.output.resolve(),
        urls=args.urls,
        trials=args.trials,
        max_attempts=args.max_attempts,
        include_control=not args.no_control,
    )
    print(json.dumps(payload["summary"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
