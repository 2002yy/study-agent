"""The model tool entry must expose the same platform map the planners see."""

from __future__ import annotations

from src.tools.web_agent import WEB_TOOLS, WebToolAgent
from src.web.site_pool import platform_map_instruction


def test_web_search_schema_can_name_a_platform():
    tool = next(item for item in WEB_TOOLS if item["function"]["name"] == "web_search")
    properties = tool["function"]["parameters"]["properties"]

    assert "site_key" in properties
    assert "site_key" in tool["function"]["description"]


def test_a_named_site_uses_the_scoped_search_route():
    class Gateway:
        def __init__(self):
            self.seen = None

        def search_site(self, query, *, site_key, max_results):
            self.seen = (query, site_key, max_results)
            return {
                "status": "ok",
                "results": [],
                "site_route": {"target": site_key},
            }

    gateway = Gateway()
    agent = WebToolAgent(gateway=gateway)  # type: ignore[arg-type]
    result = agent._execute(
        "web_search", {"query": "WAL mode", "site_key": "hn", "max_results": 5}
    )

    assert gateway.seen == ("WAL mode", "hn", 5)
    assert result["site_route"]["target"] == "hn"


def test_platform_map_names_the_reader_modes():
    prompt = platform_map_instruction()

    assert "audio read mode" in prompt
    assert "PDFs and subtitle files are detected automatically" in prompt
