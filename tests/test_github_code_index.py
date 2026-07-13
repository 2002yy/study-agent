from __future__ import annotations

from src.web.github_code_index import GitHubCodeIndex, build_code_chunks


SNAPSHOT = {
    "files": [
        {
            "path": "src/web/github_reader.py",
            "sha": "sha-reader",
            "url": "https://github.com/openai/example/blob/main/src/web/github_reader.py",
            "content": """class GitHubSourceReader:\n    def search_repository(self, query):\n        return query\n""",
        },
        {
            "path": "src/application/chat_service.py",
            "sha": "sha-chat",
            "url": "https://github.com/openai/example/blob/main/src/application/chat_service.py",
            "content": """def prepare_chat_turn(message):\n    return message\n""",
        },
        {
            "path": "tests/test_github_reader.py",
            "sha": "sha-test",
            "url": "https://github.com/openai/example/blob/main/tests/test_github_reader.py",
            "content": """def test_search_repository():\n    assert True\n""",
        },
    ]
}


def test_chunk_builder_records_symbols_language_and_line_ranges():
    chunks = build_code_chunks(SNAPSHOT["files"], max_chars=500)

    reader = next(chunk for chunk in chunks if chunk.path.endswith("github_reader.py"))

    assert reader.language == "python"
    assert reader.start_line == 1
    assert reader.end_line == 3
    assert "GitHubSourceReader" in reader.symbols
    assert "search_repository" in reader.symbols
    assert reader.sha == "sha-reader"


def test_symbol_and_path_match_rank_implementation_before_tests():
    index = GitHubCodeIndex.from_snapshot(SNAPSHOT)

    result = index.search("GitHubSourceReader search_repository", top_k=5)

    assert result["result_count"] >= 1
    first = result["results"][0]
    assert first["path"] == "src/web/github_reader.py"
    assert first["score_breakdown"]["symbol"] > 0
    assert first["line_range"] == "L1-L3"
    assert first["url"].endswith("src/web/github_reader.py")


def test_bm25_finds_content_when_filename_does_not_match():
    index = GitHubCodeIndex.from_snapshot(SNAPSHOT)

    result = index.search("prepare chat turn", top_k=3)

    assert result["results"][0]["path"] == "src/application/chat_service.py"
    assert result["results"][0]["score_breakdown"]["bm25"] > 0
    assert result["index"]["retrieval"] == "path+symbol+bm25+exact"


def test_empty_query_returns_no_results_without_false_matches():
    index = GitHubCodeIndex.from_snapshot(SNAPSHOT)

    result = index.search("   ")

    assert result["result_count"] == 0
    assert result["results"] == []
