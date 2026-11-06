"""Blinding and composition controls for the frozen annotation set."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from tools.build_annotation_set import (
    BLIND_CSV,
    BLIND_JSON,
    KEYS_JSON,
    PER_STRATUM,
    SEED,
    STRATA,
    _blind_rows,
    _pool,
    _sample,
)

ROOT = Path("docs/research_quality/answer_ab")
ALLOWED_KEYS = {
    "id",
    "claim",
    "passage",
    "source_title",
    "source_url",
    "read_id",
    "span_start",
    "span_end",
}


def _built():
    pool, misses = _pool(ROOT)
    chosen, shortfall = _sample(pool)
    return pool, misses, chosen, shortfall


def test_the_set_is_thirty_real_cases_with_every_shape_represented():
    pool, misses, chosen, shortfall = _built()

    assert len(chosen) == 30
    assert misses >= 0
    assert pool
    strata = {item.stratum for item in chosen}
    assert strata == set(STRATA)
    assert all(count <= PER_STRATUM for count in shortfall.values())


def test_the_blind_rows_carry_no_hint_about_the_expected_answer():
    rows = _blind_rows(_built()[2])

    for row in rows:
        assert set(row) == ALLOWED_KEYS
    payload = json.dumps(rows, ensure_ascii=False)
    for forbidden in ("verdict", "supports", "literal", "a3", "stratum", "correct"):
        assert forbidden not in payload


def test_no_claim_and_passage_pair_appears_twice():
    rows = _blind_rows(_built()[2])

    pairs = [(row["claim"], row["passage"]) for row in rows]
    assert len(pairs) == len(set(pairs))


def test_the_frozen_files_match_the_sampler():
    rows = json.loads(BLIND_JSON.read_text(encoding="utf-8"))
    keys = json.loads(KEYS_JSON.read_text(encoding="utf-8"))

    assert len(rows) == 30
    assert set(keys["stratum_of"]) == {row["id"] for row in rows}
    assert set(keys["literal_bound_of"]) == set(keys["stratum_of"])
    assert set(keys["usable_of"]) == set(keys["stratum_of"])
    assert keys["seed"] == SEED
    assert keys["a2_misses"] >= 0


def test_the_csv_exposes_blank_annotation_columns_only():
    text = BLIND_CSV.read_text(encoding="utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))

    header = rows[0]
    assert header[-4:] == ["annotation_S_C_I_U", "reason", "disputed", "annotator"]
    body = rows[1:]
    assert len(body) == 30
    for row in body:
        assert row[-4:] == ["", "", "", ""]
