from __future__ import annotations

from collections import Counter

import pytest

from tools.check_mypy_baseline import (
    error_signature,
    evaluate_mypy_result,
    new_error_counts,
    parse_error_counts,
)


def test_error_signature_ignores_line_and_column_numbers():
    first = 'src/example.py:10: error: Bad assignment  [assignment]'
    second = 'src/example.py:99:4: error: Bad assignment  [assignment]'

    assert error_signature(first) == error_signature(second)


def test_known_mypy_errors_pass_the_incremental_gate():
    baseline = Counter(
        {'src/example.py|assignment|Bad assignment': 2}
    )
    log = '\n'.join(
        [
            'src/example.py:10: error: Bad assignment  [assignment]',
            'src/example.py:20: error: Bad assignment  [assignment]',
        ]
    )

    passed, current, excess = evaluate_mypy_result(
        log_text=log,
        outcome='failure',
        baseline=baseline,
    )

    assert passed is True
    assert sum(current.values()) == 2
    assert not excess


def test_resolved_mypy_errors_do_not_require_baseline_growth():
    baseline = Counter(
        {'src/example.py|assignment|Bad assignment': 2}
    )
    current = parse_error_counts(
        'src/example.py:30: error: Bad assignment  [assignment]'
    )

    assert not new_error_counts(current, baseline)


def test_new_mypy_error_fails_the_incremental_gate():
    baseline = Counter(
        {'src/example.py|assignment|Bad assignment': 1}
    )
    log = '\n'.join(
        [
            'src/example.py:10: error: Bad assignment  [assignment]',
            'src/new.py:2: error: Missing attribute  [attr-defined]',
        ]
    )

    passed, _, excess = evaluate_mypy_result(
        log_text=log,
        outcome='failure',
        baseline=baseline,
    )

    assert passed is False
    assert excess == Counter(
        {'src/new.py|attr-defined|Missing attribute': 1}
    )


def test_non_error_mypy_failure_is_not_accepted_as_known_debt():
    with pytest.raises(ValueError, match='timeout or execution failure'):
        evaluate_mypy_result(
            log_text='mypy process timed out',
            outcome='failure',
            baseline=Counter(),
        )
