"""B-Search-2B9-G: bounded in-page link discovery - parsing, classification, ranking.

Pure logic: no network, no site allowlists. Extraction is fed HTML for ONE page
and never follows a link itself.
"""

from __future__ import annotations

from src.web.link_discovery import (
    classify_page,
    extract_candidates,
    question_terms,
    rank_candidates,
)

_PAGE = """<html><body>
<h1>Example Wiki</h1>
<ul>
  <li><a href="/cs">Cesky</a></li>
  <li><a href="/de">Deutsch</a></li>
  <li><a href="/zh-cn">中文</a></li>
  <li><a href="/Login">Log in</a></li>
</ul>
<h2>Gameplay</h2>
<ul>
  <li><a href="/wiki/Train_interrupts">Train interrupts</a></li>
  <li><a href="/wiki/Train_interrupts">Train interrupts</a></li>
  <li><a href="/wiki/Schedule">Schedule</a></li>
  <li><a href="https://other.example/x">External</a></li>
  <li><a href="#top">Skip</a></li>
</ul>
<h2>Navigation</h2>
<ul>
  <li><a href="/wiki/Home">Home</a></li>
  <li><a href="/wiki/Home">Home</a></li>
  <li><a href="/wiki/Home">Home</a></li>
  <li><a href="/wiki/Home">Home</a></li>
</ul>
</body></html>"""

_BASE = "https://wiki.example/Main_Page"


def test_extract_is_same_origin_deduped_and_contextual():
    links = extract_candidates(_PAGE, _BASE)
    urls = [link.url for link in links]
    assert "https://wiki.example/wiki/Train_interrupts" in urls
    assert all("other.example" not in url for url in urls)   # cross-origin dropped
    assert all("#" not in url for url in urls)               # fragments dropped
    assert len(urls) == len(set(urls))                       # duplicates collapsed
    train = next(link for link in links if link.url.endswith("Train_interrupts"))
    assert train.anchor == "Train interrupts"
    assert train.context == "Gameplay"                       # nearest preceding heading


def test_classify_separates_home_category_and_article():
    assert classify_page("https://wiki.example/") == "home"
    assert classify_page("https://wiki.example/zh-cn") == "home"
    assert classify_page("https://wiki.example/wiki/Category:Gameplay") == "category"
    assert classify_page("https://wiki.example/wiki/Train_interrupts") == "article"


def test_rank_prefers_question_match_and_penalises_noise():
    links = extract_candidates(_PAGE, _BASE)
    ranked = rank_candidates(links, question_terms("Factorio train interrupts schedule"))
    assert ranked[0].url.endswith("Train_interrupts")
    assert "matches" in ranked[0].why
    scores = {link.url: link.score for link in ranked}
    assert scores["https://wiki.example/wiki/Train_interrupts"] > scores["https://wiki.example/cs"]
    assert scores["https://wiki.example/wiki/Train_interrupts"] > scores["https://wiki.example/Login"]
    # a link repeated as template navigation must not outrank a real target
    assert scores["https://wiki.example/wiki/Train_interrupts"] > scores["https://wiki.example/wiki/Home"]


def test_rank_is_deterministic_and_bounded():
    links = extract_candidates(_PAGE, _BASE)
    first = [link.url for link in rank_candidates(links, question_terms("train interrupts"), limit=3)]
    second = [link.url for link in rank_candidates(links, question_terms("train interrupts"), limit=3)]
    assert first == second
    assert len(first) == 3
    assert all(link.why for link in rank_candidates(links, question_terms("train interrupts"), limit=10))


def test_link_cap_is_enforced():
    many = "<html><body>" + "".join(
        f'<a href="/wiki/page-{i}">page {i}</a>' for i in range(50)
    ) + "</body></html>"
    assert len(extract_candidates(many, _BASE, max_links=5)) == 5


def test_article_bonus_requires_a_topical_match():
    """A structurally-article page with no question overlap must not outrank a real target."""
    html = ("<html><body><h2>X</h2>"
            '<a href="/wiki/Game_modes_and_options">Game modes and options</a>'
            '<a href="/wiki/Trains">Trains</a>'
            '<a href="/wiki/Train_interrupts">Train interrupts</a>'
            "</body></html>")
    links = extract_candidates(html, "https://wiki.example/Main_Page")
    ranked = rank_candidates(links, question_terms("train interrupts"), limit=10)
    scores = {link.url: link.score for link in ranked}
    generic = scores["https://wiki.example/wiki/Game_modes_and_options"]
    partial = scores["https://wiki.example/wiki/Trains"]
    exact = scores["https://wiki.example/wiki/Train_interrupts"]
    assert generic < partial < exact
    assert ranked[0].url.endswith("Train_interrupts")
    assert "coverage" in ranked[0].why


def test_specific_target_outranks_the_broader_domain_page():
    """'Same domain' must not beat 'this is the question': 中继器 over 红石电路."""
    html = ("<html><body><h2>X</h2>"
            '<a href="/w/红石电路">红石电路</a>'
            '<a href="/w/红石中继器">红石中继器</a>'
            "</body></html>")
    links = extract_candidates(html, "https://wiki.example/")
    ranked = rank_candidates(links, question_terms("红石中继器 延迟 锁定"), limit=10)
    assert ranked[0].url.endswith("红石中继器")
    broad = next(link for link in ranked if link.url.endswith("红石电路"))
    assert "broader" in broad.why
    assert broad.score < ranked[0].score


def test_malformed_or_empty_html_never_raises():
    assert extract_candidates("", _BASE) == []
    assert extract_candidates("<<< not really html", _BASE) == []
