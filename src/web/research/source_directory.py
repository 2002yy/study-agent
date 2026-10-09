"""Deterministic Top-K source recall over the local Feed directory (B-Search-2B7-A).

Offline: never contacts a feed. Recall is a shortlist for the model to choose from,
not a qualification and not an evidence grant.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_LATIN = re.compile(r"[a-z0-9]{2,}")
_CJK = re.compile(r"[\u3400-\u9fff]{2,}")


def load_directory(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _terms(text: str) -> set[str]:
    lowered = (text or "").casefold()
    return set(_LATIN.findall(lowered)) | set(_CJK.findall(lowered))


def recall_sources(index: dict, question: str, k: int = 3) -> list[dict]:
    terms = _terms(question)
    is_cjk = bool(_CJK.search(question or ""))
    scored: list[dict] = []
    for source in index.get("sources", []):
        source_text = " ".join([source.get("title", "")] + list(source.get("categories", [])))
        matched = sorted(terms & _terms(source_text))
        if not matched:
            continue  # no token match => not recalled (language alone must not create one)
        score = float(len(matched))
        languages = source.get("languages", [])
        if is_cjk and "cn" in languages:
            score += 0.5
        elif not is_cjk and "en" in languages:
            score += 0.5
        scored.append({
            "source_id": source["source_id"],
            "title": source.get("title", ""),
            "xml_url": source["xml_url"],
            "categories": list(source.get("categories", [])),
            "languages": list(languages),
            "score": round(score, 3),
            "reason": "matched:" + ",".join(matched) if matched else "language_preference",
        })
    scored.sort(key=lambda r: (-r["score"], r["source_id"]))
    return scored[:k]
