from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedSymbol:
    name: str
    qualified_name: str
    kind: str
    signature: str
    parent: str
    start_line: int
    end_line: int


@dataclass(frozen=True)
class ParsedImport:
    module: str
    names: tuple[str, ...]
    kind: str
    start_line: int
    end_line: int


@dataclass(frozen=True)
class ParsedCall:
    callee: str
    caller: str
    kind: str
    start_line: int
    end_line: int


@dataclass(frozen=True)
class ParsedInheritance:
    child: str
    parent: str
    kind: str
    start_line: int
    end_line: int


@dataclass(frozen=True)
class ParsedStructure:
    language: str
    parser: str
    symbols: tuple[ParsedSymbol, ...]
    imports: tuple[ParsedImport, ...]
    calls: tuple[ParsedCall, ...]
    inheritance: tuple[ParsedInheritance, ...]
    parse_error: str = ""
