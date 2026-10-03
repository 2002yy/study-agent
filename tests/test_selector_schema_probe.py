"""§43A schema probe: raw response classification contracts."""

from __future__ import annotations

from tools.run_selector_schema_probe import classify_raw_response


def test_contract_shape() -> None:
    result = classify_raw_response('{"urls": ["https://a", "https://b"], "reason": "x"}')
    assert result["shape"] == "contract_shape"
    assert result["picks"] == 2


def test_empty_urls_is_contract_shape() -> None:
    assert classify_raw_response('{"urls": []}')["shape"] == "contract_shape"


def test_url_array_is_recognized() -> None:
    result = classify_raw_response('["https://a", "https://b"]')
    assert result["shape"] == "url_array"
    assert result["picks"] == 2


def test_fenced_json_is_reported_separately() -> None:
    raw = '```json\n{"urls": ["https://a"]}\n```'
    assert classify_raw_response(raw)["shape"] == "contract_shape"


def test_fenced_url_array_is_reported_as_fenced() -> None:
    raw = '```\n["https://a"]\n```'
    assert classify_raw_response(raw)["shape"] == "fenced_json"


def test_wrong_field_and_wrong_shape() -> None:
    assert classify_raw_response('{"query": "x"}')["shape"] == "valid_json_wrong_field"
    assert classify_raw_response('{"urls": [1, 2]}')["shape"] == "valid_json_wrong_field"
    assert classify_raw_response('{"urls": "https://a"}')["shape"] == "valid_json_wrong_field"
    assert classify_raw_response('["https://a", 5]')["shape"] == "valid_json_wrong_shape"
    assert classify_raw_response('"just a string"')["shape"] == "valid_json_wrong_shape"


def test_truncated_json_and_free_text_and_empty() -> None:
    assert classify_raw_response('{"urls": ["https://a"')["shape"] == "truncated_json"
    assert classify_raw_response("Here are the best pages for you.")["shape"] == "non_json_text"
    assert classify_raw_response("")["shape"] == "empty_content"
    assert classify_raw_response("   ")["shape"] == "empty_content"
