from __future__ import annotations

from src.news.domain_policy import (
    annotate_domain_policy,
    article_priority_adjustment,
    evaluate_domain_policy,
    infer_query_intent,
    should_fetch_article,
)


class TestDomainPolicy:
    def test_infers_tech_intent_from_programming_query(self):
        assert infer_query_intent("python urllib.parse redirect bug") == "tech"
        assert infer_query_intent("Godot 4 export error") == "tech"

    def test_general_unknown_domain_is_not_blocked_in_soft_policy(self):
        item = {
            "title": "Some article",
            "resolved_link": "https://example.com/story",
            "domain": "example.com",
        }

        decision = evaluate_domain_policy(item, "general topic")

        assert decision.blocked is False
        assert decision.score == 0

    def test_tech_query_prefers_official_and_github_domains(self):
        github_item = {
            "title": "Study Agent repo",
            "resolved_link": "https://github.com/2002yy/study-agent",
            "domain": "github.com",
        }
        unknown_item = {
            "title": "Study Agent blog",
            "resolved_link": "https://random-blog.example/post",
            "domain": "random-blog.example",
        }

        github = evaluate_domain_policy(github_item, "python agent github bug")
        unknown = evaluate_domain_policy(unknown_item, "python agent github bug")

        assert github.blocked is False
        assert github.score > unknown.score
        assert "prefer-tech-domain" in github.reasons

    def test_login_pages_are_hard_blocked(self):
        item = {
            "title": "Login",
            "resolved_link": "https://accounts.example.com/login?next=/story",
            "domain": "accounts.example.com",
        }

        decision = evaluate_domain_policy(item, "python docs")

        assert decision.blocked is True
        assert decision.score < 0
        assert not should_fetch_article(item, "python docs")

    def test_article_priority_adjustment_prefers_good_domains(self):
        docs_item = {
            "title": "urllib.parse docs",
            "resolved_link": "https://docs.python.org/3/library/urllib.parse.html",
            "domain": "docs.python.org",
        }
        unknown_item = {
            "title": "urllib.parse note",
            "resolved_link": "https://example.com/urllib-parse-note",
            "domain": "example.com",
        }

        assert article_priority_adjustment(docs_item, "python urllib.parse") < article_priority_adjustment(
            unknown_item,
            "python urllib.parse",
        )

    def test_annotate_domain_policy_adds_metadata(self):
        item = {
            "title": "Godot docs",
            "resolved_link": "https://docs.godotengine.org/en/stable/",
        }

        annotated = annotate_domain_policy(item, "godot docs")

        assert annotated["domain"] == "docs.godotengine.org"
        assert annotated["domain_policy"]["intent"] == "tech"
        assert annotated["domain_policy"]["blocked"] is False
        assert "prefer-tech-domain" in annotated["domain_policy"]["reasons"]
