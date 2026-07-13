"""Lightweight hybrid index over a persisted GitHub repository snapshot.

This is intentionally parser-light. It combines file-path relevance, extracted
symbols, exact phrases, and BM25-style lexical scoring. Tree-sitter/LSP can later
replace symbol extraction without changing the result contract.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from pathlib import PurePosixPath
import re
from typing import Any


_RAW_TOKEN_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]+|[\u3400-\u9fff]+")
_CAMEL_PART_PATTERN = re.compile(
    r"[A-Z]+(?=[A-Z][a-z]|\b)|[A-Z]?[a-z]+|[0-9]+"
)
_SYMBOL_PATTERNS = (
    re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE),
    re.compile(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE),
    re.compile(
        r"^\s*(?:export\s+)?(?:async\s+)?function\s+"
        r"([A-Za-z_$][A-Za-z0-9_$]*)",
        re.MULTILINE,
    ),
    re.compile(
        r"^\s*(?:export\s+)?(?:class|interface|type|enum)\s+"
        r"([A-Za-z_$][A-Za-z0-9_$]*)",
        re.MULTILINE,
    ),
    re.compile(
        r"^\s*(?:export\s+)?(?:const|let|var)\s+"
        r"([A-Za-z_$][A-Za-z0-9_$]*)",
        re.MULTILINE,
    ),
    re.compile(
        r"^\s*(?:public|private|protected|static|final|async|suspend|override|"
        r"virtual|internal|open|abstract|\s)+\s*[A-Za-z0-9_<>,?\[\].:]+\s+"
        r"([A-Za-z_][A-Za-z0-9_]*)\s*\(",
        re.MULTILINE,
    ),
)
_LANGUAGE_BY_SUFFIX = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".go": "go",
    ".rs": "rust",
    ".cs": "csharp",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".c": "c",
    ".h": "c",
    ".hpp": "cpp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".vue": "vue",
    ".sql": "sql",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".toml": "toml",
    ".md": "markdown",
}


def _identifier_tokens(value: str) -> list[str]:
    normalized = value.replace("$", "_")
    parts: list[str] = []
    for segment in normalized.split("_"):
        if not segment:
            continue
        camel_parts = _CAMEL_PART_PATTERN.findall(segment)
        parts.extend(camel_parts or [segment])
    return [part.casefold() for part in parts if part]


def _tokens(value: str) -> list[str]:
    result: list[str] = []
    for raw in _RAW_TOKEN_PATTERN.findall(value or ""):
        if raw and "\u3400" <= raw[0] <= "\u9fff":
            result.append(raw.casefold())
            continue
        folded = raw.casefold()
        result.append(folded)
        result.extend(token for token in _identifier_tokens(raw) if token != folded)
    return result


def _language(path: str) -> str:
    return _LANGUAGE_BY_SUFFIX.get(PurePosixPath(path.casefold()).suffix, "text")


def _symbols(text: str) -> tuple[str, ...]:
    values: list[str] = []
    for pattern in _SYMBOL_PATTERNS:
        values.extend(match.group(1) for match in pattern.finditer(text))
    return tuple(dict.fromkeys(values))


@dataclass(frozen=True)
class CodeChunk:
    chunk_id: str
    path: str
    sha: str
    url: str
    language: str
    start_line: int
    end_line: int
    symbols: tuple[str, ...]
    text: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_code_chunks(
    files: list[dict[str, Any]],
    *,
    max_chars: int = 2400,
    overlap_lines: int = 8,
) -> list[CodeChunk]:
    chunks: list[CodeChunk] = []
    safe_chars = max(500, min(int(max_chars), 10000))
    safe_overlap = max(0, min(int(overlap_lines), 40))
    for file_index, raw in enumerate(files):
        if not isinstance(raw, dict):
            continue
        path = str(raw.get("path") or "")
        content = str(raw.get("content") or "")
        if not path or not content.strip():
            continue
        lines = content.splitlines()
        start = 0
        chunk_index = 0
        while start < len(lines):
            size = 0
            end = start
            while end < len(lines):
                next_size = len(lines[end]) + 1
                if end > start and size + next_size > safe_chars:
                    break
                size += next_size
                end += 1
            excerpt = "\n".join(lines[start:end])
            chunks.append(
                CodeChunk(
                    chunk_id=f"github:{file_index}:{chunk_index}",
                    path=path,
                    sha=str(raw.get("sha") or ""),
                    url=str(raw.get("url") or ""),
                    language=_language(path),
                    start_line=start + 1,
                    end_line=max(start + 1, end),
                    symbols=_symbols(excerpt),
                    text=excerpt,
                )
            )
            if end >= len(lines):
                break
            start = max(start + 1, end - safe_overlap)
            chunk_index += 1
    return chunks


class GitHubCodeIndex:
    def __init__(self, chunks: list[CodeChunk]) -> None:
        self.chunks = list(chunks)
        self._tokens = [_tokens(chunk.text) for chunk in self.chunks]
        self._doc_freq: dict[str, int] = {}
        for tokens in self._tokens:
            for token in set(tokens):
                self._doc_freq[token] = self._doc_freq.get(token, 0) + 1
        self._average_length = (
            sum(len(tokens) for tokens in self._tokens) / len(self._tokens)
            if self._tokens
            else 1.0
        )

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, Any]) -> "GitHubCodeIndex":
        return cls(build_code_chunks(list(snapshot.get("files") or [])))

    def search(self, query: str, *, top_k: int = 12) -> dict[str, Any]:
        focused = " ".join(str(query or "").split())
        query_tokens = list(dict.fromkeys(_tokens(focused)))
        if not query_tokens:
            return {
                "query": focused,
                "result_count": 0,
                "results": [],
                "index": self.stats(),
            }
        ranked: list[tuple[float, CodeChunk, dict[str, float]]] = []
        for chunk, document_tokens in zip(self.chunks, self._tokens):
            lexical = self._bm25(query_tokens, document_tokens)
            path_tokens = set(_tokens(chunk.path))
            path_folded = chunk.path.casefold()
            path_score = sum(
                3.0 if token in path_tokens else 1.0 if token in path_folded else 0.0
                for token in query_tokens
            )
            symbol_tokens = {
                token
                for symbol in chunk.symbols
                for token in _tokens(symbol)
            }
            symbols_folded = {symbol.casefold() for symbol in chunk.symbols}
            symbol_score = sum(
                8.0
                if token in symbols_folded
                else 4.0
                if token in symbol_tokens
                else 2.0
                if any(token in symbol for symbol in symbols_folded)
                else 0.0
                for token in query_tokens
            )
            exact_score = 5.0 if focused.casefold() in chunk.text.casefold() else 0.0
            score = lexical + path_score + symbol_score + exact_score
            if score <= 0:
                continue
            ranked.append(
                (
                    score,
                    chunk,
                    {
                        "bm25": round(lexical, 6),
                        "path": path_score,
                        "symbol": symbol_score,
                        "exact": exact_score,
                    },
                )
            )
        ranked.sort(key=lambda row: (-row[0], row[1].path, row[1].start_line))
        limit = max(1, min(int(top_k), 50))
        results = [
            {
                **chunk.to_dict(),
                "rank": index + 1,
                "score": round(score, 6),
                "score_breakdown": breakdown,
                "line_range": f"L{chunk.start_line}-L{chunk.end_line}",
            }
            for index, (score, chunk, breakdown) in enumerate(ranked[:limit])
        ]
        return {
            "query": focused,
            "result_count": len(results),
            "results": results,
            "index": self.stats(),
        }

    def stats(self) -> dict[str, Any]:
        return {
            "chunk_count": len(self.chunks),
            "file_count": len({chunk.path for chunk in self.chunks}),
            "languages": sorted({chunk.language for chunk in self.chunks}),
            "symbol_count": sum(len(chunk.symbols) for chunk in self.chunks),
            "retrieval": "path+symbol+bm25+exact",
        }

    def _bm25(self, query_tokens: list[str], document_tokens: list[str]) -> float:
        if not document_tokens:
            return 0.0
        frequencies: dict[str, int] = {}
        for token in document_tokens:
            frequencies[token] = frequencies.get(token, 0) + 1
        score = 0.0
        document_count = max(1, len(self.chunks))
        length = len(document_tokens)
        k1 = 1.5
        b = 0.75
        for token in query_tokens:
            frequency = frequencies.get(token, 0)
            if frequency <= 0:
                continue
            document_frequency = self._doc_freq.get(token, 0)
            inverse_document_frequency = math.log(
                1
                + (document_count - document_frequency + 0.5)
                / (document_frequency + 0.5)
            )
            denominator = frequency + k1 * (
                1 - b + b * length / max(1.0, self._average_length)
            )
            score += (
                inverse_document_frequency
                * frequency
                * (k1 + 1)
                / denominator
            )
        return score
