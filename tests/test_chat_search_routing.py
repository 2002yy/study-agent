"""CL-M3-S2-C1 (first half): the router's static-vs-research decision.

The chat path starts with this classification and passes `research_intent` to
the web tool agent. Both directions are checked on the real router and the real
task contract:

* a static language question is a `quick_answer`, not `research`;
* a question about today's news is `research` with a web source policy;
* an explicit research request is `research` as well.

The remaining C1 question - whether a `quick_answer` is *forbidden* from using
the web - is a product decision about the source policy, not a test. Today
`quick_answer` carries `local_and_web`, and the web agent is additionally told
`research_intent=False`; that combination is what the next slice has to tighten
or justify.
"""

from __future__ import annotations

from src.mode_manager import RuntimeModes
from src.task_contract import route_request_with_task_contract


def _route(user_input: str) -> dict:
    return route_request_with_task_contract(
        user_input=user_input,
        selected_role="auto",
        selected_mode="auto",
        selected_model="auto",
        runtime_modes=RuntimeModes(performance_mode="fast"),
    )


def test_a_static_language_question_is_not_research():
    contract = _route("Java 的 JVM 是什么？它和 JRE 有什么区别？")["task_contract"]

    assert contract["task_intent"] == "quick_answer"
    assert contract["reason"] == "safe_default_quick_answer"


def test_a_question_about_today_is_research():
    contract = _route("今天的 DeepSeek 新闻有哪些？帮我查一下最新消息")["task_contract"]

    assert contract["task_intent"] == "research"
    assert contract["source_policy"] == "web_only"


def test_an_explicit_research_request_is_research():
    contract = _route(
        "帮我研究一下 Rust 和 Go 在并发模型上的差异，并核对官方文档"
    )["task_contract"]

    assert contract["task_intent"] == "research"
    assert contract["source_policy"] == "web_only"
