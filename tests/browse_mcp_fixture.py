"""Small stdio fixtures shared by the Browse adapter and site-pool tests."""

import json


def execute_request(input_text: str) -> dict:
    initialize, initialized, request = map(json.loads, input_text.splitlines())
    assert initialize["method"] == "initialize"
    assert initialized["method"] == "notifications/initialized"
    assert request["method"] == "tools/call"
    assert request["params"]["name"] == "execute"
    return request["params"]["arguments"]


def execute_response(value: dict, *, suffix: str = "") -> str:
    return json.dumps({
        "jsonrpc": "2.0",
        "id": 2,
        "result": {"content": [{"type": "text", "text": json.dumps(value) + suffix}]},
    })
