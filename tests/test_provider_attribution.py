"""§44B provider attribution: drop-reason and branch contracts."""

from __future__ import annotations

from tools.run_provider_attribution import (
    AttributionRow,
    _has_cjk,
    _path_depth,
    _rank_of,
    decide_branch,
    drop_reason,
)


def test_drop_reason_chain() -> None:
    assert drop_reason(provider_hit=False, merged_hit=False, topk_hit=False) == "provider_miss"
    assert (
        drop_reason(provider_hit=True, merged_hit=False, topk_hit=False)
        == "merge_cap_or_dedupe"
    )
    assert (
        drop_reason(provider_hit=True, merged_hit=True, topk_hit=False)
        == "topk_boundary"
    )
    assert drop_reason(provider_hit=True, merged_hit=True, topk_hit=True) == "survived"


def test_decision_tree_branches() -> None:
    assert (
        decide_branch(any_raw=False, merged_wide=False, merged_top5=False, locale_hit=False)
        == "A_provider_capability_insufficiency"
    )
    assert (
        decide_branch(any_raw=True, merged_wide=False, merged_top5=False, locale_hit=False)
        == "B_aggregation_defect"
    )
    assert (
        decide_branch(any_raw=True, merged_wide=True, merged_top5=False, locale_hit=False)
        == "C_ranking_topk_defect"
    )
    assert (
        decide_branch(any_raw=False, merged_wide=False, merged_top5=False, locale_hit=True)
        == "D_regionalization_defect"
    )
    assert (
        decide_branch(any_raw=True, merged_wide=True, merged_top5=True, locale_hit=False)
        == "mechanism_ok"
    )


def test_row_to_dict_reports_attribution_fields() -> None:
    row = AttributionRow(
        case_id="case_x",
        target="https://docs.example/page/",
        query_class="exact_title",
        query="Page Title",
        provider_ranks={"searxng": 14, "bing_rss": None, "duckduckgo_html": None},
        merged_rank_wide=None,
        merged_rank_top5=None,
        official_deep_before=2,
        official_deep_after=0,
        searxng_en_hit=True,
        searxng_en_rank=3,
    )
    payload = row.to_dict()
    assert payload["drop_reason"] == "merge_cap_or_dedupe"
    assert payload["branch"] == "D_regionalization_defect"
    assert payload["searxng_en_rank"] == 3
    assert payload["official_deep_pages_before_merge"] == 2


def test_language_and_depth_helpers() -> None:
    assert _has_cjk("Node.js 模块系统") is True
    assert _has_cjk("Node.js module systems") is False
    assert _path_depth("https://example.com/") == 0
    assert _path_depth("https://example.com/a/b/") == 2
    assert _rank_of("https://example.com/x/", [{"url": "https://example.com/x"}]) == 1
