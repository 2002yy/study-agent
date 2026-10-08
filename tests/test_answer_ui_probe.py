"""Probe reporting must not turn missing interactions/errors into latency wins."""

from tools.run_answer_ui_probe import bridge, percentile, summarize


def test_empty_latency_is_missing_not_zero():
    assert percentile([], 0.95) is None
    assert percentile([1, 3, 2], 0.5) == 2
    assert percentile([1, 3, 2], 0.95) == 2.9


def test_failed_and_missing_components_cannot_improve_latency():
    result = summarize(
        [
            {"arm": "ui_context", "first_token_seconds": 1.0, "complete_seconds": 4.0},
            {
                "arm": "ui_context",
                "first_token_seconds": 0.1,
                "complete_seconds": 0.2,
                "error": "RuntimeError",
            },
        ]
    )["ui_context"]
    assert result["samples"] == 2 and result["errors"] == 1
    assert result["first_token_seconds"] == {"n": 1, "p50": 1.0, "p95": 1.0}
    assert result["first_card_seconds"] == {"n": 0, "p50": None, "p95": None}


def test_live_chunk_replay_uses_real_parser_and_requires_closed_valid_block():
    result = bridge(
        {
            "chunks": [
                {
                    "text": '文字\n```study-ui\n{"type":"memory_lab","title":"引用",',
                    "seconds": 1,
                },
                {"text": '"initialName":"甲","updatedName":"乙"}\n', "seconds": 2},
                {"text": "```\n", "seconds": 3},
            ]
        }
    )
    assert result["first_card_seconds"] == 3
    assert result["card_types"] == ["memory_lab"]
    assert result["cards"][0]["initialName"] == "甲"
    assert result["rejected_fence"] is False
    invalid = bridge(
        {
            "chunks": [
                {
                    "text": '```study-ui\n{"type":"script","title":"x"}\n```',
                    "seconds": 1,
                }
            ]
        }
    )
    assert invalid["first_card_seconds"] is None
    assert invalid["card_types"] == []
    assert invalid["rejected_fence"] is True
