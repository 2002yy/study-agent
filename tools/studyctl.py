"""Repository-local, offline Study Agent operations. No global install required."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Any, NoReturn

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "agent-cli-result-v1"
OWNERS = ("AGENTS.md", "docs/PROJECT_STATUS.md", "tests/stage_gates.json")


class CLIError(Exception):
    def __init__(self, code: int, kind: str, message: str) -> None:
        self.code, self.kind, self.message = code, kind, message


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        # argparse messages can contain arbitrary client arguments or secrets.
        raise CLIError(2, "invalid_arguments", "Invalid arguments; see --help.")


def common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", type=Path, default=argparse.SUPPRESS)
    parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    parser.add_argument("--help", action="store_true", default=argparse.SUPPRESS)
    parser.add_argument("--dry-run", action="store_true", default=argparse.SUPPRESS)
    parser.add_argument("--output", type=Path, default=argparse.SUPPRESS)


def parser_for_cli() -> Parser:
    parser = Parser(description=__doc__, add_help=False)
    common(parser)
    children = parser.add_subparsers(dest="command")
    for name in ("status", "doctor", "help"):
        common(children.add_parser(name, add_help=False))
    return parser


def git(root: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            [
                "git",
                "--no-optional-locks",
                "-c",
                "core.fsmonitor=false",
                "-C",
                str(root),
                *arguments,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        raise CLIError(3, "missing_git", "Git is unavailable.") from None
    except subprocess.TimeoutExpired:
        raise CLIError(5, "git_timeout", "Git exceeded the read deadline.") from None
    if result.returncode:
        raise CLIError(
            3, "git_unavailable", "Cannot read the requested Git repository."
        )
    return result.stdout.strip()


def repository(root: Path) -> tuple[Path, str]:
    if not root.is_dir():
        raise CLIError(3, "missing_repository", "Repository directory is unavailable.")
    actual = Path(git(root, "rev-parse", "--show-toplevel")).resolve()
    head = git(actual, "rev-parse", "--verify", "HEAD")
    if len(head) != 40 or any(char not in "0123456789abcdef" for char in head):
        raise CLIError(3, "invalid_head", "An exact committed HEAD is required.")
    return actual, head


def read_status(root: Path) -> dict[str, Any]:
    rows = git(
        root, "status", "--porcelain=v1", "--untracked-files=normal"
    ).splitlines()
    return {
        "root": str(root),
        "branch": git(root, "branch", "--show-current") or None,
        "tracked_changes": sum(not row.startswith("??") for row in rows),
        "untracked_entries": sum(row.startswith("??") for row in rows),
        "untracked_count_semantics": "Git normal mode entries; directories are not expanded",
        "authority_files": {name: (root / name).is_file() for name in OWNERS},
    }


def doctor(root: Path) -> dict[str, Any]:
    checks = {"python_3_11_or_newer": sys.version_info >= (3, 11)}
    checks.update({name: (root / name).is_file() for name in OWNERS})
    checks.update(
        {
            name: (root / name).is_file()
            for name in (
                "tools/ci_scope.py",
                "tools/run_stage_gate.py",
                "tools/l3_preflight.py",
            )
        }
    )
    try:
        manifest = json.loads(
            (root / "tests/stage_gates.json").read_text(encoding="utf-8")
        )
        checks["gate_schema"] = (
            manifest.get("schema_version") == "staged-regression-policy-v1"
        )
    except (OSError, ValueError, AttributeError):
        checks["gate_schema"] = False
    return {
        "checks": checks,
        "python": sys.version.split()[0],
        "network": "not_requested",
    }


def save_new(path: Path, text: str) -> None:
    """Publish one new report using a same-directory hard link, never overwrite."""
    temporary: Path | None = None
    try:
        if path.exists() or path.is_symlink():
            raise CLIError(
                3, "output_exists", "Output already exists; refusing overwrite."
            )
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as file:
            temporary = Path(file.name)
            file.write(text + "\n")
            file.flush()
            os.fsync(file.fileno())
        os.link(temporary, path)
    except OSError:
        raise CLIError(
            3, "output_unavailable", "Cannot publish a new output file."
        ) from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    started = time.monotonic()
    result: dict[str, Any] = {
        "schema_version": SCHEMA,
        "command": "",
        "status": "PASS",
        "repo": "study-agent",
        "head_sha": None,
        "exit_code": 0,
        "duration_ms": 0,
        "artifacts": [],
        "errors": [],
        "data": {},
    }
    options: argparse.Namespace | None = None
    try:
        parser = parser_for_cli()
        options = parser.parse_args(argv)
        help_requested = getattr(options, "help", False) or options.command == "help"
        if help_requested:
            if not getattr(options, "json", False):
                parser.print_help()
                return 0
            result["command"] = "help"
            result["data"] = {
                "commands": ["status", "doctor", "help"],
                "side_effects": "read-only unless --output is explicit",
            }
        else:
            if not options.command:
                raise CLIError(2, "missing_command", "Select a command; see --help.")
            result["command"] = options.command
            root, result["head_sha"] = repository(getattr(options, "repo", ROOT))
            if options.command == "status":
                result["data"] = read_status(root)
            else:
                result["data"] = doctor(root)
                if not all(result["data"]["checks"].values()):
                    raise CLIError(
                        3, "doctor_blocked", "Required local prerequisites are missing."
                    )
        result["data"]["dry_run"] = getattr(options, "dry_run", False)
        result["duration_ms"] = round((time.monotonic() - started) * 1000)
        output = getattr(options, "output", None)
        if output is not None and not getattr(options, "dry_run", False):
            result["artifacts"] = [str(output.absolute())]
            save_new(output, json.dumps(result, ensure_ascii=True))
    except CLIError as error:
        result.update(
            exit_code=error.code, status="FAIL" if error.code in (2, 4) else "BLOCKED"
        )
        result["artifacts"] = []
        result["errors"] = [{"code": error.kind, "message": error.message}]
    except (OSError, ValueError):
        result.update(exit_code=3, status="BLOCKED")
        result["errors"] = [
            {"code": "local_read_failed", "message": "Local metadata is unavailable."}
        ]
    result["duration_ms"] = round((time.monotonic() - started) * 1000)
    print(json.dumps(result, ensure_ascii=True))
    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
