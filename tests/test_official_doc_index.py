"""No-network checks for safe official documentation directory fallback."""

from unittest.mock import patch

from src.web.research.official_doc_index import (
    discover_official_index,
    has_facet_document,
    parse_official_index_links,
)
from src.web.research_recovery import recover_public_research, recovery_summary
from src.web.tool_evidence import evidence_tool_calls


INDEX_HTML = """<html><body><nav>
<a href="wal.html">Write-Ahead Log (WAL) Mode</a>
<a href="backup.html">Backup API</a>
<a href="download.html">Download SQLite</a>
<a href="https://sqlite.org.evil.test/backup.html">Fake Backup API</a>
<a href="//attacker.test/backup.html">Other Backup API</a>
<a href="javascript:alert(1)">Backup API</a>
</nav></body></html>"""


def test_index_maps_actual_links_to_chinese_facets_without_guessing_urls():
    kwargs = {"html": INDEX_HTML, "index_url": "https://sqlite.org/docs.html", "domain": "sqlite.org"}
    backup = parse_official_index_links(**kwargs, facet_query="SQLite 在线备份与恢复")
    checkpoint = parse_official_index_links(**kwargs, facet_query="SQLite 长事务 checkpoint")
    nfs = parse_official_index_links(**kwargs, facet_query="SQLite 网络文件系统 NFS")
    assert [item["url"] for item in backup] == ["https://sqlite.org/backup.html"]
    assert [item["url"] for item in checkpoint] == ["https://sqlite.org/wal.html"]
    assert [item["url"] for item in nfs] == ["https://sqlite.org/wal.html"]
    assert parse_official_index_links(**kwargs, facet_query="SQLite 向量搜索") == []


def test_reading_only_verified_indexes_prevents_misleading_cross_host_redirect():
    with patch(
        "src.web.research.official_doc_index._fetch_html_payload",
        return_value=(INDEX_HTML, "https://bad.test/docs.html", "text/html", ""),
    ):
        actual = discover_official_index("sqlite.org", "SQLite backup")
    assert actual["status"] == "unavailable"
    assert actual["results"] == []
    assert discover_official_index("random-site.example", "backup")["status"] == "not_configured"


def test_index_discovery_only_for_missing_official_facet_and_preserves_provenance():
    import src.web.research_recovery as recovery_module

    class FakeGateway:
        def __init__(self):
            self.searches = iter([
                [{"title": "SQLite WAL concurrent writes", "url": "https://sqlite.org/wal.html"}],
                [],
                [{"title": "SQLite Documentation", "url": "https://sqlite.org/docs.html"}],
            ])
            self.reads: list[str] = []

        def search_exact(self, query, *, max_results):
            results = next(self.searches, [])
            return {"status": "ok" if results else "empty", "results": results}

        def read(self, url, *, max_chars, timeout):
            self.reads.append(url)
            bodies = {
                "wal.html": ("SQLite WAL permits one writer at a time. "
                             "Long read transactions prevent checkpoint. "
                             "WAL shared memory does not work on network filesystem NFS."),
                "backup.html": ("SQLite Backup API provides online backup "
                                "and a way to restore database snapshots."),
            }
            return {"ok": True, "url": url, "content": bodies[url.rsplit("/", 1)[-1]]}

    gateway = FakeGateway()
    index_calls = []

    class FreeSemanticStub:
        stages = {"research_candidate_relevance"}
        events = []
        episode = None

        def __init__(self):
            self.body_questions: set[str] = set()

        def relevance(self, _stage, items):
            return {item["id"]: ["rq-wal", "rq-backup"] for item in items}

    def fake_index(domain, facet_query):
        index_calls.append((domain, facet_query))
        return {"status": "ok", "index_url": "https://sqlite.org/docs.html", "html": INDEX_HTML}

    plan = [
        {"rq_id": "rq-wal", "query": "SQLite WAL concurrent writers"},
        {"rq_id": "rq-backup", "query": "SQLite online backup API"},
    ]
    with patch.object(recovery_module, "discover_official_index", side_effect=fake_index):
        calls = recover_public_research(
            gateway, "比较 SQLite WAL 与备份恢复", query_plan=plan,
            semantic_session=FreeSemanticStub(),
        )

    evidence = evidence_tool_calls(calls)
    assert gateway.reads == ["https://sqlite.org/wal.html", "https://sqlite.org/backup.html"], (gateway.reads, index_calls)
    assert len(index_calls) == 1
    assert [entry["arguments"]["url"] for entry in evidence] == gateway.reads
    assert len([call for call in calls if call.get("name") == "web_search"
                and call.get("arguments", {}).get("recovery_stage") == "official_document_index"]) == 1
    assert all("docs.html" not in str(entry["arguments"]["url"]) for entry in evidence)
    assert recovery_summary(calls)["reads"] == 2
    assert recovery_summary(calls)["searches"] == 3
    contents = "\n".join(str(entry["result"]["content"]) for entry in evidence).lower()
    assert all(word in contents for word in ("writer", "checkpoint", "nfs", "backup"))


def test_existing_topic_document_skips_index_and_missing_link_stays_missing():
    assert has_facet_document(
        [{"title": "SQLite Backup API", "url": "https://sqlite.org/backup.html"}],
        domain="sqlite.org", facet_query="SQLite backup",
    )
    assert not has_facet_document(
        [{"title": "SQLite Documentation", "url": "https://sqlite.org/docs.html"}],
        domain="sqlite.org", facet_query="SQLite backup",
    )
    assert parse_official_index_links(
        '<a href="wal.html">Write-Ahead Log (WAL) Mode</a>',
        index_url="https://sqlite.org/docs.html", domain="sqlite.org", facet_query="SQLite backup",
    ) == []


def test_index_html_fetched_once_and_reused_across_two_uncovered_questions():
    import src.web.research_recovery as recovery_module

    class Gateway:
        def __init__(self):
            self.read_urls = []
            self.search_count = 0

        def search_exact(self, query, *, max_results):
            self.search_count += 1
            if self.search_count == 1:
                raise ConnectionError("searxng_connection_refused")
            return {"status": "empty", "results": []}

        def read(self, url, *, max_chars, timeout):
            self.read_urls.append(url)
            return {"ok": True, "url": url, "content": "SQLite WAL backup evidence " + url}

    gateway = Gateway()
    called = []

    def fake_index(domain, facet_query):
        called.append(domain)
        return {"status": "ok", "index_url": "https://sqlite.org/docs.html", "html": INDEX_HTML}

    plan = [
        {"rq_id": "rq-wal", "query": "SQLite WAL checkpoint"},
        {"rq_id": "rq-backup", "query": "SQLite backup API"},
    ]
    with patch.object(recovery_module, "discover_official_index", side_effect=fake_index):
        calls = recover_public_research(gateway, "比较 SQLite WAL backup", query_plan=plan)
    assert called == ["sqlite.org"]
    assert "https://sqlite.org/wal.html" in gateway.read_urls
    assert "https://sqlite.org/backup.html" in gateway.read_urls, gateway.read_urls
    assert any(call.get("name") == "web_search" and call.get("result", {}).get("status") == "unavailable"
               and "searxng_connection_refused" in str(call.get("result", {}).get("reason")) for call in calls)
    assert recovery_summary(calls)["provider_failures"] >= 1
