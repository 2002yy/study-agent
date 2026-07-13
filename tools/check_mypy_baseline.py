#!/usr/bin/env python3
"""Fail CI only when mypy debt grows beyond the checked-in baseline."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
from typing import Any

_ERROR = re.compile(
    r"^(?P<path>[^:]+):\d+(?::\d+)?: error: "
    r"(?P<message>.*?)(?:\s+\[(?P<code>[^\]]+)\])?$"
)


def error_signature(line: str) -> str | None:
    """Normalize one mypy error without unstable line and column numbers."""

    match = _ERROR.match(line.strip())
    if match is None:
        return None
    path = match.group("path").replace("\\", "/")
    code = match.group("code") or ""
    message = match.group("message")
    return f"{path}|{code}|{message}"


def parse_error_counts(text: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    for line in text.splitlines():
        signature = error_signature(line)
        if signature is not None:
            counts[signature] += 1
    return counts


def load_baseline(path: Path) -> tuple[Counter[str], dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") != 1:
        raise ValueError("Unsupported mypy baseline version")
    raw_signatures = payload.get("signatures")
    if not isinstance(raw_signatures, dict):
        raise ValueError("Mypy baseline signatures must be an object")
    counts = Counter({str(key): int(value) for key, value in raw_signatures.items()})
    expected = int(payload.get("known_error_count", -1))
    if expected != sum(counts.values()):
        raise ValueError(
            f"Mypy baseline count mismatch: metadata={expected}, signatures={sum(counts.values())}"
        )
    return counts, payload


def new_error_counts(
    current: Counter[str], baseline: Counter[str]
) -> Counter[str]:
    return Counter(
        {
            signature: count - baseline.get(signature, 0)
            for signature, count in current.items()
            if count > baseline.get(signature, 0)
        }
    )


def evaluate_mypy_result(
    *, log_text: str, outcome: str, baseline: Counter[str]
) -> tuple[bool, Counter[str], Counter[str]]:
    """Return pass/fail, current errors and errors exceeding the baseline."""

    normalized_outcome = outcome.strip().lower()
    if normalized_outcome not in {"success", "failure"}:
        raise ValueError(f"Unsupported mypy outcome: {outcome!r}")
    current = parse_error_counts(log_text)
    if normalized_outcome == "success":
        if current:
            raise ValueError("Mypy reported success but the log contains errors")
        return True, current, Counter()
    if not current:
        raise ValueError(
            "Mypy failed without parseable errors; this may be a timeout or execution failure"
        )
    excess = new_error_counts(current, baseline)
    return not excess, current, excess


def _print_counts(title: str, counts: Counter[str]) -> None:
    if not counts:
        return
    print(title)
    for signature, count in sorted(counts.items()):
        print(f"  {count}x {signature}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--outcome", required=True)
    args = parser.parse_args()

    try:
        baseline, metadata = load_baseline(args.baseline)
        passed, current, excess = evaluate_mypy_result(
            log_text=args.log.read_text(encoding="utf-8"),
            outcome=args.outcome,
            baseline=baseline,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: unable to validate mypy baseline: {exc}")
        return 1

    known_count = int(metadata["known_error_count"])
    current_count = sum(current.values())
    if not passed:
        print(
            f"ERROR: mypy debt increased: current={current_count}, "
            f"baseline={known_count}, new={sum(excess.values())}"
        )
        _print_counts("New or increased mypy errors:", excess)
        return 1

    resolved = baseline - current
    print(
        f"mypy baseline gate passed: current={current_count}, "
        f"baseline={known_count}, resolved={sum(resolved.values())}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
