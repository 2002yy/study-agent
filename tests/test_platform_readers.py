from __future__ import annotations

import time

from src.web import platform_readers
from src.web.tool_gateway import GeneralWebGateway


def test_hosts_are_detected():
    assert platform_readers.detect("https://news.ycombinator.com/item?id=1") == "hn"
    assert platform_readers.detect(
        "https://stackoverflow.com/questions/1/x"
    ) == "stackexchange"
    assert platform_readers.detect(
        "https://forum.godotengine.org/t/foo/123"
    ) == "discourse"
    assert platform_readers.detect(
        "https://openreview.net/forum?id=abc"
    ) == "openreview"
    assert platform_readers.detect("https://example.com/") == ""


def test_hacker_news_returns_the_story_and_nested_comments(monkeypatch):
    item = {
        "title": "SQLite WAL", "text": "<p>story body</p>",
        "children": [
            {"author": "a", "created_at": "2026-01-01", "text": "top comment",
             "children": [
                 {"author": "b", "created_at": "2026-01-02", "text": "nested", "children": []},
             ]},
        ],
    }
    monkeypatch.setattr(platform_readers, "_get_json", lambda url, timeout: item)
    result = platform_readers.read("https://news.ycombinator.com/item?id=42", timeout=5)
    assert result["ok"] is True
    assert result["method"] == "hn_api"
    assert result["comments"] == 2
    assert "story body" in result["content"]
    assert "nested" in result["content"]


def test_stackexchange_returns_question_and_answers(monkeypatch):
    def fake(url, timeout):
        if "/answers" in url:
            return {"items": [{"score": 9, "owner": {"display_name": "bob"},
                               "body": "<p>answer body</p>"}]}
        return {"items": [{"title": "How to WAL?", "body": "<p>question body</p>"}]}

    monkeypatch.setattr(platform_readers, "_get_json", fake)
    result = platform_readers.read(
        "https://stackoverflow.com/questions/123/how", timeout=5
    )
    assert result["ok"] is True
    assert result["answers"] == 1
    assert "question body" in result["content"] and "answer body" in result["content"]


def test_discourse_returns_posts_and_next_page(monkeypatch):
    data = {
        "title": "Physics conveyor",
        "post_stream": {
            "posts": [
                {"username": "a", "created_at": "2026-01-01", "cooked": "<p>first</p>"},
                {"username": "b", "created_at": "2026-01-02", "cooked": "<p>second</p>"},
            ],
            "stream": [1, 2, 3, 4],
        },
    }
    monkeypatch.setattr(platform_readers, "_get_json", lambda url, timeout: data)
    result = platform_readers.read(
        "https://forum.godotengine.org/t/physics/123", timeout=5
    )
    assert result["ok"] is True
    assert result["replies"] == 2
    assert result["next_url"].endswith("?page=2")
    assert "first" in result["content"]


def test_openreview_returns_abstract_and_reviews(monkeypatch):
    notes = [
        {"invitations": ["/papers/-/Submission"], "content": {
            "title": {"value": "A Paper"}, "abstract": {"value": "abstract text"}}},
        {"invitations": ["/papers/-/Official_Review"], "content": {
            "summary": {"value": "review summary"},
            "weaknesses": {"value": "weak point"}}},
    ]
    monkeypatch.setattr(platform_readers, "_get_json",
                        lambda url, timeout: {"notes": notes})
    result = platform_readers.read(
        "https://openreview.net/forum?id=abc", timeout=5
    )
    assert result["ok"] is True
    assert result["title"] == "A Paper"
    assert result["reviews"] == 1
    assert "review summary" in result["content"]


def test_the_gateway_uses_the_platform_reader(monkeypatch):
    monkeypatch.setattr(
        platform_readers, "read",
        lambda url, timeout: {"ok": True, "kind": "web_page", "url": url,
                              "method": "hn_api", "title": "T", "content": "body"},
    )
    result = GeneralWebGateway().read(
        "https://news.ycombinator.com/item?id=42", timeout=5
    )
    assert result["method"] == "hn_api"


def test_academic_hosts_are_detected():
    assert platform_readers.detect("https://doi.org/10.1038/nature12373") == "doi"
    assert platform_readers.detect("https://openalex.org/works/W2741809807") == "openalex"
    assert platform_readers.detect("https://arxiv.org/abs/1706.03762") == "arxiv"
    assert platform_readers.detect("https://zenodo.org/records/12345") == "zenodo"


def test_doi_returns_crossref_metadata_not_full_text(monkeypatch):
    monkeypatch.delenv("UNPAYWALL_EMAIL", raising=False)

    def fake(url, timeout):
        if "crossref.org" in url:
            return {"message": {
                "title": ["A study"], "DOI": "10.1/x",
                "author": [{"given": "Ada", "family": "Lovelace"}],
                "published-print": {"date-parts": [[2024, 5, 1]]},
                "container-title": ["Journal"], "type": "journal-article",
                "license": [{"URL": "https://creativecommons.org/licenses/by/4.0/"}],
                "resource": {"primary": {"URL": "https://publisher.example/x"}},
                "abstract": "<jats:p>short abstract</jats:p>",
            }}
        raise AssertionError(url)

    monkeypatch.setattr(platform_readers, "_get_json", fake)
    result = platform_readers.read("https://doi.org/10.1/x", timeout=5)

    assert result["ok"] is True
    assert result["method"] == "crossref_api"
    assert "doi=10.1/x" in result["content"]
    assert "Ada Lovelace" in result["content"]
    assert "short abstract" in result["content"]
    assert "abstract only" in result["content"]
    assert "[full text] not read" in result["content"]
    assert "not checked (UNPAYWALL_EMAIL is unset)" in result["content"]


def test_unknown_doi_falls_back_to_datacite(monkeypatch):
    monkeypatch.delenv("UNPAYWALL_EMAIL", raising=False)

    def fake(url, timeout):
        if "crossref.org" in url:
            raise platform_readers.urllib.error.HTTPError(url, 404, "Not Found", None, None)
        if "datacite.org" in url:
            return {"data": {"attributes": {
                "titles": [{"title": "A dataset"}],
                "creators": [{"name": "Data Team"}],
                "publicationYear": 2024,
                "publisher": "Zenodo",
                "types": {"resourceTypeGeneral": "Dataset"},
                "descriptions": [{"descriptionType": "Abstract",
                                  "description": "dataset abstract"}],
                "url": "https://zenodo.org/records/1",
            }}}
        raise AssertionError(url)

    monkeypatch.setattr(platform_readers, "_get_json", fake)
    result = platform_readers.read("https://doi.org/10.1/data", timeout=5)

    assert result["ok"] is True
    assert result["method"] == "datacite_api"
    assert "A dataset" in result["content"]
    assert "dataset abstract" in result["content"]


def test_openalex_rebuilds_the_abstract_and_references(monkeypatch):
    def fake(url, timeout):
        return {
            "id": "https://openalex.org/W1", "doi": "https://doi.org/10.1/x",
            "title": "Work", "publication_date": "2024-01-01", "type": "article",
            "authorships": [{"author": {"display_name": "Ada"}}],
            "primary_location": {"source": {"display_name": "Journal"}},
            "cited_by_count": 7,
            "referenced_works": ["https://openalex.org/W2", "https://openalex.org/W3"],
            "abstract_inverted_index": {"hello": [0], "world": [1]},
            "open_access": {"is_oa": True, "oa_url": "https://oa.example/x"},
        }

    monkeypatch.setattr(platform_readers, "_get_json", fake)
    result = platform_readers.read("https://openalex.org/works/W1", timeout=5)

    assert result["ok"] is True
    assert result["method"] == "openalex_api"
    assert "hello world" in result["content"]
    assert "cited_by=7" in result["content"]
    assert "2 works" in result["content"]
    assert "W2" in result["content"]


def test_arxiv_parses_the_atom_entry(monkeypatch):
    atom = """<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>Attention Is All You Need</title>
        <summary> transformer abstract </summary>
        <author><name>Vaswani</name></author>
        <published>2017-06-12T00:00:00Z</published>
        <updated>2023-01-01T00:00:00Z</updated>
        <link title="pdf" href="https://arxiv.org/pdf/1706.03762"/>
      </entry>
    </feed>
    """
    monkeypatch.setattr(platform_readers, "_get_text", lambda url, timeout: atom)
    result = platform_readers.read("https://arxiv.org/abs/1706.03762", timeout=5)

    assert result["ok"] is True
    assert result["method"] == "arxiv_api"
    assert "Attention Is All You Need" in result["content"]
    assert "transformer abstract" in result["content"]
    assert "pdf=https://arxiv.org/pdf/1706.03762" in result["content"]
    assert "PDF was not parsed" in result["content"]


def test_zenodo_lists_files_without_downloading(monkeypatch):
    def fake(url, timeout):
        return {
            "metadata": {
                "title": "Dataset", "doi": "10.5281/zenodo.1",
                "creators": [{"name": "Team"}],
                "publication_date": "2024-02-02",
                "description": "<p>data description</p>",
                "resource_type": {"title": "Dataset"},
                "license": {"id": "cc-by-4.0"},
            },
            "files": [{"key": "data.csv", "size": 1234}],
        }

    monkeypatch.setattr(platform_readers, "_get_json", fake)
    result = platform_readers.read("https://zenodo.org/records/1", timeout=5)

    assert result["ok"] is True
    assert result["method"] == "zenodo_api"
    assert "data.csv" in result["content"]
    assert "not downloaded" in result["content"]


def test_mediawiki_hosts_are_detected():
    assert platform_readers.detect(
        "https://en.wikipedia.org/wiki/Jolt_Physics"
    ) == "mediawiki"
    assert platform_readers.detect(
        "https://zh.wikipedia.org/wiki/%E7%A0%B4%E5%9D%8F"
    ) == "mediawiki"
    assert platform_readers.detect(
        "https://wiki.archlinux.org/title/Arch_boot_process"
    ) == "mediawiki"
    assert platform_readers.detect("https://minecraft.wiki/w/Block") == "mediawiki"
    assert platform_readers.detect("https://example.com/wiki/Foo") == ""


def test_mediawiki_titles_are_taken_from_each_url_shape():
    assert platform_readers._mediawiki_title(
        "https://en.wikipedia.org/wiki/Jolt_Physics"
    ) == "Jolt Physics"
    assert platform_readers._mediawiki_title(
        "https://zh.wikipedia.org/wiki/%E7%A0%B4%E5%9D%8F"
    ) == "破坏"
    assert platform_readers._mediawiki_title(
        "https://minecraft.wiki/w/Block"
    ) == "Block"
    assert platform_readers._mediawiki_title(
        "https://wiki.archlinux.org/title/Arch_boot_process"
    ) == "Arch boot process"
    assert platform_readers._mediawiki_title(
        "https://en.wikipedia.org/w/index.php?title=Jolt_Physics"
    ) == "Jolt Physics"
    assert platform_readers._mediawiki_title("https://en.wikipedia.org/") == ""
    assert platform_readers._mediawiki_title(
        "https://zh.moegirl.org.cn/%E5%88%9D%E9%9F%B3%E6%9C%AA%E6%9D%A5"
    ) == "初音未来"


def test_mediawiki_subpath_wikis_use_the_first_segment_as_their_base():
    base, title = platform_readers._mediawiki_base(
        "https://wiki.biligame.com/sr/%E8%A7%92%E8%89%B2"
    )
    assert base == "https://wiki.biligame.com/sr"
    assert title == "角色"
    assert platform_readers._mediawiki_base("https://wiki.biligame.com/") == ("", "")


def test_mediawiki_reads_plain_extract(monkeypatch):
    monkeypatch.setattr(platform_readers, "_MEDIAWIKI_ENDPOINTS", {})

    def fake(url, timeout):
        if "meta=siteinfo" in url:
            return {"query": {"general": {"sitename": "Wikipedia"}}}
        return {"query": {"pages": [{
            "title": "Jolt Physics",
            "extract": "Jolt is a rigid body physics engine.",
        }]}}

    monkeypatch.setattr(platform_readers, "_get_json", fake)
    result = platform_readers.read(
        "https://en.wikipedia.org/wiki/Jolt_Physics", timeout=5
    )
    assert result["ok"] is True
    assert result["method"] == "mediawiki_api"
    assert result["title"] == "Jolt Physics"
    assert "rigid body" in result["content"]
    assert platform_readers._MEDIAWIKI_ENDPOINTS["https://en.wikipedia.org"] == (
        "https://en.wikipedia.org/w/api.php"
    )


def test_mediawiki_falls_back_to_parse_html(monkeypatch):
    monkeypatch.setattr(platform_readers, "_MEDIAWIKI_ENDPOINTS", {})

    def fake(url, timeout):
        if "meta=siteinfo" in url:
            return {"query": {"general": {"sitename": "ArchWiki"}}}
        if "action=parse" in url:
            return {"parse": {"title": "Arch boot process",
                              "text": "<p>Boot <b>sequence</b></p>"}}
        return {"query": {"pages": [{"title": "Arch boot process", "extract": ""}]}}

    monkeypatch.setattr(platform_readers, "_get_json", fake)
    result = platform_readers.read(
        "https://wiki.archlinux.org/title/Arch_boot_process", timeout=5
    )
    assert result["ok"] is True
    assert "Boot sequence" in result["content"]


def test_mediawiki_reports_a_missing_page(monkeypatch):
    monkeypatch.setattr(platform_readers, "_MEDIAWIKI_ENDPOINTS", {})

    def fake(url, timeout):
        if "meta=siteinfo" in url:
            return {"query": {"general": {"sitename": "Wikipedia"}}}
        return {"query": {"pages": [{"title": "Nope", "missing": True}]}}

    monkeypatch.setattr(platform_readers, "_get_json", fake)
    result = platform_readers.read("https://en.wikipedia.org/wiki/Nope", timeout=5)
    assert result["ok"] is False
    assert result["error_code"] == "platform_empty"


def test_mediawiki_requires_a_page_title(monkeypatch):
    result = platform_readers.read("https://en.wikipedia.org/", timeout=5)
    assert result["ok"] is False
    assert result["error_code"] == "platform_unsupported"

def test_huggingface_model_returns_metadata_card_and_discussions(monkeypatch):
    assert platform_readers.detect(
        "https://huggingface.co/microsoft/phi-2"
    ) == "huggingface"

    def fake_json(url, timeout):
        if url.endswith("/discussions?p=0"):
            return {"count": 147, "discussions": [
                {"num": 12, "title": "Multilingual powerhouse", "numComments": 14},
            ]}
        return {
            "id": "microsoft/phi-2", "pipeline_tag": "text-generation",
            "library_name": "transformers", "downloads": 186898, "likes": 3540,
            "gated": False, "private": False, "lastModified": "2025-12-08",
            "cardData": {"license": "mit"}, "tags": ["transformers"],
            "siblings": [{"rfilename": "a"}, {"rfilename": "b"}],
        }

    monkeypatch.setattr(platform_readers, "_get_json", fake_json)
    monkeypatch.setattr(
        platform_readers, "_get_text",
        lambda url, timeout, max_bytes=30_000: "# Model card\nPhi-2 text",
    )
    result = platform_readers.read("https://huggingface.co/microsoft/phi-2", timeout=5)

    assert result["ok"] is True
    assert result["method"] == "huggingface_api"
    assert "license: mit" in result["content"]
    assert "text-generation" in result["content"]
    assert "147 total" in result["content"]
    assert "Model card" in result["content"]
    assert result["discussions"] == 147


def test_huggingface_dataset_uses_the_dataset_api(monkeypatch):
    seen: list[str] = []

    def fake_json(url, timeout):
        seen.append(url)
        if url.endswith("/discussions?p=0"):
            return {"count": 0, "discussions": []}
        return {"id": "rajpurkar/squad", "cardData": {"license": "cc-by-sa-4.0"},
                "tags": [], "siblings": []}

    monkeypatch.setattr(platform_readers, "_get_json", fake_json)
    monkeypatch.setattr(platform_readers, "_get_text", lambda *a, **k: "")
    result = platform_readers.read(
        "https://huggingface.co/datasets/rajpurkar/squad", timeout=5
    )

    assert result["ok"] is True
    assert any("/api/datasets/rajpurkar/squad" in url for url in seen)
    assert "license: cc-by-sa-4.0" in result["content"]


def test_huggingface_missing_repo_is_empty(monkeypatch):
    def missing(url, timeout):
        raise platform_readers.urllib.error.HTTPError(url, 404, "Not Found", None, None)

    monkeypatch.setattr(platform_readers, "_get_json", missing)
    result = platform_readers.read("https://huggingface.co/no/such-model", timeout=5)
    assert result["ok"] is False
    assert result["error_code"] == "platform_empty"


def test_huggingface_non_repo_urls_fall_back():
    result = platform_readers.read("https://huggingface.co/papers/1234", timeout=5)
    assert result["ok"] is False
    assert result["error_code"] == "platform_unsupported"


def test_mediawiki_revision_urls_are_not_read_as_the_latest_page(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("revision URLs must not hit the API")

    monkeypatch.setattr(platform_readers, "_get_json", forbidden)

    for url in (
        "https://en.wikipedia.org/w/index.php?title=Foo&oldid=12345",
        "https://en.wikipedia.org/w/index.php?title=Foo&diff=12345&oldid=12344",
        "https://en.wikipedia.org/w/index.php?title=Foo&action=history",
    ):
        result = platform_readers.read(url, timeout=5)
        assert result["ok"] is False
        assert result["error_code"] == "platform_unsupported"


def test_mediawiki_requests_share_one_deadline(monkeypatch):
    monkeypatch.setattr(platform_readers, "_MEDIAWIKI_ENDPOINTS", {})
    seen: list[float] = []

    def fake(url, timeout):
        seen.append(timeout)
        if "meta=siteinfo" in url:
            time.sleep(1.2)
            return {"query": {"general": {"sitename": "Wikipedia"}}}
        return {"query": {"pages": [{"title": "X", "extract": "body"}]}}

    monkeypatch.setattr(platform_readers, "_get_json", fake)
    result = platform_readers.read("https://en.wikipedia.org/wiki/X", timeout=3)

    assert result["ok"] is True
    assert 2.9 <= seen[0] <= 3.0
    assert seen[1] <= 2.0

def test_depsdev_reads_version_and_dependencies(monkeypatch):
    assert platform_readers.detect(
        "https://deps.dev/pypi/requests/2.31.0"
    ) == "depsdev"

    def fake(url, timeout):
        if url.endswith(":dependencies"):
            return {"nodes": [
                {"versionKey": {"system": "PYPI", "name": "requests", "version": "2.31.0"},
                 "relation": "SELF"},
                {"versionKey": {"system": "PYPI", "name": "urllib3", "version": "1.26.18"},
                 "relation": "DIRECT"},
            ]}
        return {
            "publishedAt": "2023-05-22T15:12:42Z",
            "isDefault": False, "isDeprecated": False,
            "licenses": ["Apache-2.0"],
            "advisoryKeys": [{"id": "GHSA-1"}],
            "links": [{"label": "SOURCE_REPO", "url": "https://github.com/psf/requests"}],
        }

    monkeypatch.setattr(platform_readers, "_get_json", fake)
    result = platform_readers.read("https://deps.dev/pypi/requests/2.31.0", timeout=5)

    assert result["ok"] is True
    assert result["method"] == "depsdev_api"
    assert "Apache-2.0" in result["content"]
    assert "GHSA-1" in result["content"]
    assert "urllib3 1.26.18" in result["content"]
    assert "- requests " not in result["content"]


def test_depsdev_maven_packages_keep_the_group_path(monkeypatch):
    seen: list[str] = []

    def fake(url, timeout):
        seen.append(url)
        if url.endswith(":dependencies"):
            return {"nodes": []}
        return {"licenses": ["Apache-2.0"], "advisoryKeys": []}

    monkeypatch.setattr(platform_readers, "_get_json", fake)
    result = platform_readers.read(
        "https://deps.dev/maven/org.apache.commons/commons-lang3/3.14.0", timeout=5
    )

    assert result["ok"] is True
    assert any("org.apache.commons%3Acommons-lang3" in url for url in seen)


def test_depsdev_missing_version_is_empty(monkeypatch):
    def missing(url, timeout):
        raise platform_readers.urllib.error.HTTPError(url, 404, "Not Found", None, None)

    monkeypatch.setattr(platform_readers, "_get_json", missing)
    result = platform_readers.read("https://deps.dev/pypi/nope/0.0.0", timeout=5)
    assert result["ok"] is False
    assert result["error_code"] == "platform_empty"


def test_depsdev_unknown_shape_falls_back():
    result = platform_readers.read("https://deps.dev/", timeout=5)
    assert result["ok"] is False
    assert result["error_code"] == "platform_unsupported"

def test_lobsters_returns_the_story_and_threaded_comments(monkeypatch):
    assert platform_readers.detect(
        "https://lobste.rs/s/srb0dp/title"
    ) == "lobsters"
    story = {
        "title": "Marginalia Search",
        "url": "https://example.com/post",
        "score": 42,
        "comment_count": 3,
        "tags": ["search", "ai"],
        "submitter_user": {"username": "alice"},
        "created_at": "2026-11-01T10:00:00.000-05:00",
        "description_plain": "<p>story body</p>",
        "comments": [
            {"depth": 0, "comment_plain": "<p>first</p>",
             "commenting_user": {"username": "bob"}, "created_at": "2026-11-01T11:00:00Z"},
            {"depth": 1, "comment_plain": "nested reply",
             "commenting_user": {"username": "carol"}, "created_at": "2026-11-01T12:00:00Z"},
            {"depth": 0, "comment_plain": "deleted", "is_deleted": True},
            {"depth": 9, "comment_plain": "too deep"},
        ],
    }
    monkeypatch.setattr(platform_readers, "_get_json", lambda url, timeout: story)
    result = platform_readers.read(
        "https://lobste.rs/s/srb0dp/marginalia", timeout=5
    )

    assert result["ok"] is True
    assert result["method"] == "lobsters_api"
    assert result["comments"] == 2
    assert "story body" in result["content"]
    assert "[d1] carol" in result["content"]
    assert "deleted" not in result["content"]
    assert "too deep" not in result["content"]


def test_lobsters_requires_a_story_id():
    result = platform_readers.read("https://lobste.rs/", timeout=5)
    assert result["ok"] is False
    assert result["error_code"] == "platform_unsupported"
