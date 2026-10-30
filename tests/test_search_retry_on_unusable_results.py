"""Search-3A: a non-empty result batch is not a usable answer.

The Standard pipeline used to stop at the first query variant that returned any
result, then synthesise from whatever was readable. These controls pin the
bounded retry: one unused variant, inside the existing read budget, and only
when nothing readable actually matches the question.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from src.application.web_lookup_service import WebLookupService
from src.domain.runtime_entities import WebLookupRun
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.web_lookup_repository import WebLookupRepository

QUERY = "星铁 千冶·刃 遗器 推荐 黄泉队"
VARIANT_2 = "千冶·刃 遗器 配装 攻略"


class ScriptedGateway:
    """Serves one scripted batch per query and one scripted body per URL."""

    def __init__(
        self,
        batches: dict[str, list[dict[str, Any]]],
        reads: dict[str, dict[str, Any]],
    ) -> None:
        self.batches = batches
        self.reads = reads
        self.queries: list[str] = []
        self.read_urls: list[str] = []

    def search(self, query: str, *, max_items: int):
        self.queries.append(query)
        return [dict(item) for item in self.batches.get(query, [])][:max_items]

    def read(self, url: str, **_kwargs):
        self.read_urls.append(url)
        return dict(self.reads.get(url, {"ok": False, "error": "missing_fixture"}))

    def warnings(self):
        return []


def _item(title: str, url: str, snippet: str = "") -> dict[str, Any]:
    return {"title": title, "url": url, "snippet": snippet, "source": "scripted"}


def _body(text: str, url: str) -> dict[str, Any]:
    return {
        "ok": True,
        "url": url,
        "title": text[:40],
        "content": text,
        "content_sha256": hashlib.sha256(text.encode()).hexdigest(),
    }


def _run(
    tmp_path,
    *,
    variants: list[str],
    query: str = QUERY,
    backup_query=None,
) -> tuple[WebLookupService, WebLookupRepository, str]:
    repository = WebLookupRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    run = WebLookupRun(
        id="web_lookup_search3a",
        query=query,
        stage="planned",
        status="pending",
        max_items=5,
        research_context={
            "canonical_query": query,
            "raw_query": query,
            "query_variants": variants,
            "run_kind": "standalone",
            "research_mode": "standard",
        },
    )
    repository.create(run)
    return (
        WebLookupService(repository, backup_query=backup_query),
        repository,
        run.id,
    )


def test_an_unrelated_first_batch_is_retried_with_one_more_variant(tmp_path):
    gateway = ScriptedGateway(
        batches={
            QUERY: [
                _item("千（汉语汉字）_百度百科", "https://baike.example/qian", "千，数目")
            ],
            VARIANT_2: [
                _item(
                    "千冶·刃 培养攻略 遗器 配装",
                    "https://game.example/b01",
                    "千冶·刃 遗器 推荐 黄泉队 配装",
                )
            ],
        },
        reads={
            "https://baike.example/qian": _body(
                "千，数目，十百为千。古文千作人。", "https://baike.example/qian"
            ),
            "https://game.example/b01": _body(
                "千冶·刃 遗器 推荐：莳者四件套，配黄泉队。", "https://game.example/b01"
            ),
        },
    )
    repository = WebLookupRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    run = WebLookupRun(
        id="web_lookup_search3a",
        query=QUERY,
        stage="planned",
        status="pending",
        max_items=5,
        research_context={
            "canonical_query": QUERY,
            "raw_query": QUERY,
            "query_variants": [QUERY, VARIANT_2],
            "run_kind": "standalone",
            "research_mode": "standard",
        },
    )
    repository.create(run)
    service = WebLookupService(repository, gateway)

    executed = service.execute(run.id, raise_on_error=True)

    assert gateway.queries == [QUERY, VARIANT_2]
    assert "https://game.example/b01" in gateway.read_urls
    assert executed.research_context["search_retry"]["variant"] == VARIANT_2
    assert "千冶·刃" in executed.source_block



def test_retry_does_not_reread_first_batch_url_before_a_new_useful_page(tmp_path):
    """With 2/3 reads spent, the duplicated URL must not crowd out page 3."""
    first = "https://baike.example/qian"
    second = "https://baike.example/wan"
    useful = "https://game.example/relics"
    gateway = ScriptedGateway(
        batches={
            QUERY: [
                _item("千（汉字）", first, "千字释义"),
                _item("万（汉字）", second, "万字释义"),
            ],
            VARIANT_2: [
                _item("千（汉字）复现", first, "千字释义"),
                _item(
                    "千冶·刃 遗器 推荐 黄泉队",
                    useful,
                    "千冶·刃 遗器 推荐 黄泉队 配装",
                ),
            ],
        },
        reads={
            first: _body("千，数字单位。", first),
            second: _body("万，数字单位。", second),
            useful: _body("千冶·刃 遗器 推荐与黄泉队伍配装。", useful),
        },
    )
    service, _, run_id = _run(tmp_path, variants=[QUERY, VARIANT_2])
    service.gateway = gateway

    executed = service.execute(run_id, raise_on_error=True)

    assert gateway.queries == [QUERY, VARIANT_2]
    assert gateway.read_urls == [first, second, useful]
    assert useful in executed.source_block
    assert executed.research_context["read_summary"]["attempted"] == 3



def test_a_usable_first_batch_does_not_spend_a_second_query(tmp_path):
    gateway = ScriptedGateway(
        batches={
            QUERY: [
                _item(
                    "千冶·刃 遗器 推荐 黄泉队 配装",
                    "https://game.example/b01",
                    "千冶·刃 遗器 推荐 黄泉队 配装 攻略",
                )
            ],
            VARIANT_2: [_item("别的页面", "https://other.example/x")],
        },
        reads={
            "https://game.example/b01": _body(
                "千冶·刃 遗器 推荐：莳者四件套。", "https://game.example/b01"
            )
        },
    )
    service, repository, run_id = _run(tmp_path, variants=[QUERY, VARIANT_2])
    service.gateway = gateway

    executed = service.execute(run_id, raise_on_error=True)

    assert gateway.queries == [QUERY]
    assert "search_retry" not in executed.research_context


def test_only_one_retry_is_ever_spent(tmp_path):
    third = "千冶 刃 光锥 遗器"
    gateway = ScriptedGateway(
        batches={
            QUERY: [_item("千（汉字）", "https://baike.example/qian")],
            VARIANT_2: [_item("万（汉字）", "https://baike.example/wan")],
            third: [_item("千冶·刃 攻略", "https://game.example/b01")],
        },
        reads={
            "https://baike.example/qian": _body("千，数目。", "https://baike.example/qian"),
            "https://baike.example/wan": _body("万，数目。", "https://baike.example/wan"),
            "https://game.example/b01": _body(
                "千冶·刃 遗器 推荐。", "https://game.example/b01"
            ),
        },
    )
    service, repository, run_id = _run(tmp_path, variants=[QUERY, VARIANT_2, third])
    service.gateway = gateway

    executed = service.execute(run_id, raise_on_error=True)

    assert gateway.queries == [QUERY, VARIANT_2]
    assert third not in gateway.queries
    assert executed.research_context["search_retry"]["variant"] == VARIANT_2


def test_no_retry_when_the_read_budget_is_already_spent(tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_RESEARCH_MAX_READS", "1")
    gateway = ScriptedGateway(
        batches={
            QUERY: [_item("千（汉字）", "https://baike.example/qian")],
            VARIANT_2: [_item("千冶·刃 攻略", "https://game.example/b01")],
        },
        reads={
            "https://baike.example/qian": _body("千，数目。", "https://baike.example/qian"),
            "https://game.example/b01": _body(
                "千冶·刃 遗器 推荐。", "https://game.example/b01"
            ),
        },
    )
    service, repository, run_id = _run(tmp_path, variants=[QUERY, VARIANT_2])
    service.gateway = gateway

    executed = service.execute(run_id, raise_on_error=True)

    assert gateway.queries == [QUERY]
    assert "search_retry" not in executed.research_context


def test_a_cross_language_page_is_still_read(tmp_path):
    """Low Chinese-keyword overlap must not stop the read itself."""

    gateway = ScriptedGateway(
        batches={
            QUERY: [
                _item(
                    "Blade — Honkai: Star Rail Wiki",
                    "https://wiki.example/blade",
                    "Blade relics and teams",
                )
            ],
            VARIANT_2: [_item("千冶·刃 攻略", "https://game.example/b01")],
        },
        reads={
            "https://wiki.example/blade": _body(
                "Blade best relics: four-piece Longevous Disciple.", "https://wiki.example/blade"
            ),
            "https://game.example/b01": _body(
                "千冶·刃 遗器 推荐。", "https://game.example/b01"
            ),
        },
    )
    service, repository, run_id = _run(tmp_path, variants=[QUERY, VARIANT_2])
    service.gateway = gateway

    executed = service.execute(run_id, raise_on_error=True)

    assert "https://wiki.example/blade" in gateway.read_urls
    assert "Longevous" in executed.source_block


def test_without_a_spare_variant_the_run_still_finishes(tmp_path):
    gateway = ScriptedGateway(
        batches={QUERY: [_item("千（汉字）", "https://baike.example/qian")]},
        reads={
            "https://baike.example/qian": _body("千，数目。", "https://baike.example/qian")
        },
    )
    service, repository, run_id = _run(tmp_path, variants=[QUERY])
    service.gateway = gateway

    executed = service.execute(run_id, raise_on_error=True)

    assert gateway.queries == [QUERY]
    assert "search_retry" not in executed.research_context
    assert executed.status in {"completed", "partial"}


def test_one_variant_with_a_useful_failure_falls_back_to_the_planner(tmp_path):
    """A single normalized query must still be able to look elsewhere."""

    gateway = ScriptedGateway(
        batches={
            QUERY: [
                _item("千（汉语汉字）_百度百科", "https://baike.example/qian", "千，数目")
            ],
            "千冶·刃 遗器 攻略": [
                _item(
                    "千冶·刃 遗器 推荐 黄泉队",
                    "https://game.example/b01",
                    "千冶·刃 遗器 推荐 黄泉队",
                )
            ],
        },
        reads={
            "https://baike.example/qian": _body(
                "千，数目。", "https://baike.example/qian"
            ),
            "https://game.example/b01": _body(
                "千冶·刃 遗器 推荐：莳者四件套。", "https://game.example/b01"
            ),
        },
    )
    asked: list[str] = []

    def backup(query: str) -> str:
        asked.append(query)
        return "千冶·刃 遗器 攻略"

    service, repository, run_id = _run(tmp_path, variants=[QUERY], backup_query=backup)
    service.gateway = gateway

    executed = service.execute(run_id, raise_on_error=True)

    assert asked == [QUERY]
    assert gateway.queries == [QUERY, "千冶·刃 遗器 攻略"]
    retry = executed.research_context["search_retry"]
    assert retry["source"] == "backup_planner"
    assert retry["variant"] == "千冶·刃 遗器 攻略"
    assert "千冶·刃" in executed.source_block


def test_a_planner_failure_does_not_break_the_run(tmp_path):
    gateway = ScriptedGateway(
        batches={QUERY: [_item("千（汉字）", "https://baike.example/qian")]},
        reads={
            "https://baike.example/qian": _body("千，数目。", "https://baike.example/qian")
        },
    )

    def backup(_query: str) -> str:
        raise RuntimeError("planner unavailable")

    service, repository, run_id = _run(tmp_path, variants=[QUERY], backup_query=backup)
    service.gateway = gateway

    executed = service.execute(run_id, raise_on_error=True)

    assert gateway.queries == [QUERY]
    assert "search_retry" not in executed.research_context
    assert any(
        "backup query planning failed" in warning for warning in executed.warnings
    )


def test_a_planner_cannot_re_search_an_attempted_query(tmp_path):
    gateway = ScriptedGateway(
        batches={QUERY: [_item("千（汉字）", "https://baike.example/qian")]},
        reads={
            "https://baike.example/qian": _body("千，数目。", "https://baike.example/qian")
        },
    )
    service, repository, run_id = _run(
        tmp_path, variants=[QUERY], backup_query=lambda _query: QUERY
    )
    service.gateway = gateway

    executed = service.execute(run_id, raise_on_error=True)

    assert gateway.queries == [QUERY]
    assert "search_retry" not in executed.research_context


def test_the_planner_adapter_returns_a_different_query() -> None:
    from src.web.research.backup_query import plan_backup_query

    seen: list[str] = []

    def completion(*, messages, timeout, task_name):  # noqa: ANN001 - test stub
        seen.append(task_name)
        return json.dumps(
            {
                "task_id": "backup-query",
                "intent": "NEW_RESEARCH",
                "subject": "千冶·刃",
                "constraints_delta": {},
                "unresolved_questions": [{"id": "rq-question", "question": QUERY}],
                "suggested_next_action": "search",
                "proposed_queries": [
                    {"rq_id": "rq-question", "query": "千冶·刃 遗器 攻略"}
                ],
            },
            ensure_ascii=False,
        )

    planned = plan_backup_query(query=QUERY, completion=completion, timeout_seconds=5)

    assert planned == "千冶·刃 遗器 攻略"
    assert seen == ["research_turn_interpretation"]
