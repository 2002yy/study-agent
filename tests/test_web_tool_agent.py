from __future__ import annotations

from types import SimpleNamespace
from urllib.request import ProxyHandler

import pytest

from src.llm_client import run_tool_loop
from src.tools.web_agent import WebToolAgent
from src.web.tool_gateway import GeneralWebGateway, _DuckDuckGoResultsParser


def test_tool_loop_executes_function_calls_and_returns_evidence(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("MODEL_FLASH_NAME", "test-flash")
    monkeypatch.setenv("MODEL_PRO_NAME", "test-pro")

    tool_call = SimpleNamespace(
        id="call_1",
        function=SimpleNamespace(name="web_search", arguments='{"query":"FastAPI release"}'),
    )
    responses = iter(
        [
            SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[tool_call]))]),
            SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="TOOL_RESEARCH_COMPLETE", tool_calls=[]))]),
        ]
    )
    requests: list[dict] = []

    class FakeCompletions:
        def create(self, **kwargs):
            requests.append(kwargs)
            return next(responses)

    monkeypatch.setattr(
        "src.llm_client.get_client",
        lambda **kwargs: SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions())),
    )

    evidence = run_tool_loop(
        [{"role": "user", "content": "latest FastAPI release"}],
        tools=[{"type": "function", "function": {"name": "web_search"}}],
        execute_tool=lambda name, arguments: {"name": name, "query": arguments["query"]},
        max_rounds=2,
        timeout=12.0,
    )

    assert evidence == [
        {
            "name": "web_search",
            "arguments": {"query": "FastAPI release"},
            "result": {"name": "web_search", "query": "FastAPI release"},
        }
    ]
    assert requests[0]["tool_choice"] == "auto"
    assert requests[0]["timeout"] == 12.0
    assert requests[1]["messages"][-2]["role"] == "assistant"
    assert requests[1]["messages"][-1]["role"] == "tool"


def test_tool_loop_stops_before_provider_request_when_cancelled(monkeypatch):
    monkeypatch.setattr(
        "src.llm_client.get_client",
        lambda **kwargs: pytest.fail("provider must not be called after cancellation"),
    )

    with pytest.raises(RuntimeError, match="tool_loop_cancelled"):
        run_tool_loop(
            [{"role": "user", "content": "cancel me"}],
            tools=[{"type": "function", "function": {"name": "web_search"}}],
            execute_tool=lambda _name, _arguments: {},
            should_cancel=lambda: True,
        )


def test_web_agent_formats_model_selected_results_as_context():
    class FakeGateway:
        def search(self, query, *, max_results):
            return [{"title": query, "url": "https://example.com", "source": "test"}]

        def read(self, url, *, max_chars):
            return {"ok": "true", "url": url, "content": "page text"}

    def run_loop(messages, *, execute_tool, **kwargs):
        return [
            {
                "name": "web_search",
                "arguments": {"query": "official docs"},
                "result": execute_tool("web_search", {"query": "official docs"}),
            },
            {
                "name": "web_read",
                "arguments": {"url": "https://example.com"},
                "result": execute_tool("web_read", {"url": "https://example.com"}),
            },
        ]

    trace = WebToolAgent(gateway=FakeGateway(), run_loop=run_loop).resolve("what changed?")

    assert trace.used is True
    assert "模型联网工具结果" in trace.context_block()
    assert "https://example.com" in trace.context_block()


def test_search_snippets_remain_candidates_until_a_page_is_read():
    search_call = {
        "name": "web_search",
        "arguments": {"query": "Opus 5"},
        "result": {
            "status": "ok",
            "results": [
                {
                    "title": "Candidate report",
                    "url": "https://example.com/report",
                    "snippet": "unverified search snippet",
                }
            ],
        },
    }
    candidate_only = WebToolAgent(
        gateway=object(),  # type: ignore[arg-type]
        run_loop=lambda *_args, **_kwargs: [search_call],
    ).resolve("research Opus 5", research_intent=True)

    assert candidate_only.used is False
    assert candidate_only.context_block() == ""
    assert candidate_only.to_dict()["evidence_status"] == "candidate_only"
    assert candidate_only.to_dict()["candidate_count"] == 1
    assert candidate_only.to_dict()["calls"] == [search_call]
    assert "尚未读取正文" in candidate_only.to_dict()["error"]

    read_backed = WebToolAgent(
        gateway=object(),  # type: ignore[arg-type]
        run_loop=lambda *_args, **_kwargs: [
            search_call,
            {
                "name": "web_read",
                "arguments": {"url": "https://example.com/report"},
                "result": {
                    "ok": True,
                    "url": "https://example.com/report",
                    "content": "verified full page body",
                },
            },
        ],
    ).resolve("research Opus 5", research_intent=True)

    assert read_backed.used is True
    assert "verified full page body" in read_backed.context_block()
    assert "unverified search snippet" not in read_backed.context_block()
    assert read_backed.to_dict()["evidence_status"] == "read_backed"
    assert read_backed.to_dict()["read_count"] == 1


def test_duckduckgo_parser_keeps_only_public_result_links():
    parser = _DuckDuckGoResultsParser()
    parser.feed(
        '<a class="result__a" href="https://example.com/a">Example result</a>'
        '<a class="result__a" href="/l/?uddg=https%3A%2F%2Fexample.org%2Fb">Second</a>'
    )
    assert parser.results == [
        {"title": "Example result", "url": "https://example.com/a"},
        {"title": "Second", "url": "https://example.org/b"},
    ]


def test_web_trace_does_not_disclose_empty_or_failed_calls():
    trace = WebToolAgent(
        gateway=object(),  # type: ignore[arg-type]
        run_loop=lambda *_args, **_kwargs: [
            {
                "name": "web_search",
                "arguments": {"query": "blocked"},
                "result": {
                    "status": "unavailable",
                    "reason": "providers_failed",
                    "results": [],
                    "provider_errors": ["duckduckgo_html:challenge"],
                },
            }
        ],
    ).resolve("search blocked")

    assert trace.used is False
    assert trace.context_block() == ""
    assert trace.to_dict()["calls"] == []
    assert "未使用联网来源" in trace.to_dict()["error"]
    assert trace.to_dict()["provider_errors"]


def test_web_trace_rejects_successful_read_for_url_not_discovered_by_search():
    trace = WebToolAgent(
        gateway=object(),  # type: ignore[arg-type]
        run_loop=lambda *_args, **_kwargs: [
            {
                "name": "web_read",
                "arguments": {"url": "https://untrusted.example/page"},
                "result": {
                    "ok": True,
                    "url": "https://untrusted.example/page",
                    "content": "Untrusted page body",
                },
            }
        ],
    ).resolve("read a guessed page")

    assert trace.used is False
    assert trace.context_block() == ""
    assert trace.to_dict()["calls"] == []


def test_web_trace_rejects_loopback_search_results():
    trace = WebToolAgent(
        gateway=object(),  # type: ignore[arg-type]
        run_loop=lambda *_args, **_kwargs: [
            {
                "name": "web_search",
                "arguments": {"query": "internal"},
                "result": {
                    "status": "ok",
                    "results": [
                        {
                            "title": "Internal service",
                            "url": "http://127.0.0.1:8080/private",
                        }
                    ],
                },
            }
        ],
    ).resolve("search internal")

    assert trace.used is False
    assert trace.context_block() == ""


def _ddg_response(payload: bytes, status: int = 200):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _limit):
            return payload

    Response.status = status
    return Response()


def test_duckduckgo_search_posts_the_site_form_with_browser_headers(monkeypatch):
    """A GET with a self-identifying agent is answered with the anti-bot page.

    Measured against the live endpoint: GET + self-identifying UA -> 202
    "anomaly", POST + browser headers -> 200 with result links. The adapter must
    therefore send the form the site sends, not a plain GET.
    """

    captured = {}

    def fake_urlopen(request, **_kwargs):
        captured["request"] = request
        return _ddg_response(
            b'<a class="result__a" href="/l/?uddg=https%3A%2F%2Fexample.org%2Fa">'
            b"Example result</a>"
        )

    monkeypatch.setattr("src.web.tool_gateway.urlopen", fake_urlopen)
    monkeypatch.delenv("WEB_DUCKDUCKGO_PROXY", raising=False)

    results, error = GeneralWebGateway._search_duckduckgo("python dataclass", 5, 4.0)

    assert error == ""
    assert results == [
        {
            "title": "Example result",
            "url": "https://example.org/a",
            "snippet": "",
            "source": "DuckDuckGo",
            "published_at": "",
        }
    ]
    request = captured["request"]
    assert request.get_method() == "POST"
    assert request.data.decode("utf-8").startswith("q=python+dataclass")
    assert request.get_header("Content-type") == "application/x-www-form-urlencoded"
    assert request.get_header("Accept-language") == "en-US,en;q=0.9"
    assert "Mozilla/5.0" in request.get_header("User-agent")
    assert "StudyAgent" not in request.get_header("User-agent")


def test_duckduckgo_proxy_is_scoped_to_this_provider(monkeypatch):
    """Egress is opt-in per provider, never a process-wide proxy.

    docs/CL_M1_REBIND_PREVIEW.md §7: a proxy in the process environment hijacked
    loopback requests and broke the browser gates, so the proxy must only wrap
    this one request.
    """

    sent = {}

    class Opener:
        def open(self, request, timeout=None):
            sent["request"] = request
            sent["timeout"] = timeout
            return _ddg_response(b'<a class="result__a" href="https://e.test/a">E</a>')

    def fake_build_opener(handler):
        sent["handler"] = handler
        return Opener()

    monkeypatch.setenv("WEB_DUCKDUCKGO_PROXY", "http://127.0.0.1:7890")
    monkeypatch.setattr("src.web.tool_gateway.build_opener", fake_build_opener)
    monkeypatch.setattr(
        "src.web.tool_gateway.urlopen",
        lambda *_args, **_kwargs: pytest.fail("proxy configured but urlopen used"),
    )

    results, error = GeneralWebGateway._search_duckduckgo("python", 5, 4.0)

    assert error == ""
    assert [item["url"] for item in results] == ["https://e.test/a"]
    assert isinstance(sent["handler"], ProxyHandler)
    assert sent["request"].get_method() == "POST"


def test_duckduckgo_http_error_is_a_provider_failure(monkeypatch):
    monkeypatch.setattr(
        "src.web.tool_gateway.urlopen",
        lambda *_args, **_kwargs: _ddg_response(b"<html></html>", status=403),
    )

    results, error = GeneralWebGateway._search_duckduckgo("python", 5, 1.0)

    assert results == []
    assert error == "duckduckgo_html:http_status:403"


def test_duckduckgo_page_without_results_reports_empty(monkeypatch):
    monkeypatch.setattr(
        "src.web.tool_gateway.urlopen",
        lambda *_args, **_kwargs: _ddg_response(b"<html><body>no hits</body></html>"),
    )

    results, error = GeneralWebGateway._search_duckduckgo("python", 5, 1.0)

    assert results == []
    assert error == "duckduckgo_html:empty_response"


def test_duckduckgo_challenge_is_structured_as_provider_failure(monkeypatch):
    class ChallengeResponse:
        status = 202

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _limit):
            return b"anomaly challenge bots use DuckDuckGo"

    monkeypatch.setattr("src.web.tool_gateway.urlopen", lambda *_args, **_kwargs: ChallengeResponse())

    results, error = GeneralWebGateway._search_duckduckgo("python", 5, 1.0)

    assert results == []
    assert error == "duckduckgo_html:challenge"
