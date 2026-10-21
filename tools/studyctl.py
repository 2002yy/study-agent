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
    test = children.add_parser("test", add_help=False)
    common(test)
    plans = test.add_subparsers(dest="test_command")
    plan = plans.add_parser("plan", add_help=False)
    common(plan)
    plan.add_argument("--base")
    plan.add_argument("--head", default="HEAD")
    plan.add_argument("--include-working-tree", action="store_true")
    run = plans.add_parser("run", add_help=False)
    common(run)
    run.add_argument("--level", choices=("L1", "L2", "L3"), default="L1")
    run.add_argument("--impact-set", default="")
    run.add_argument("--stage", default="")
    run.add_argument("--timeout", type=float)
    return parser


def run_tests(root: Path, options: argparse.Namespace) -> dict[str, Any]:
    if __package__ in (None, ""):
        sys.path.insert(0, str(ROOT))
    from tools.studyctl_execution import commands_for, execute

    if root.resolve() != ROOT.resolve():
        raise CLIError(
            3,
            "execution_repo_mismatch",
            "Run the CLI from the target checkout; arbitrary repository scripts cannot execute.",
        )
    if (
        options.level == "L1"
        and (not options.impact_set or options.stage)
        or options.level == "L2"
        and (not options.stage or options.impact_set)
        or options.level == "L3"
        and (options.impact_set or options.stage)
    ):
        raise CLIError(
            2, "invalid_selector", "Choose one matching level and gate selector."
        )
    if options.timeout is None:
        if options.level == "L3":
            raise CLIError(
                2,
                "l3_timeout_required",
                "L3 requires an explicit --timeout budget (up to 3600 seconds).",
            )
        options.timeout = 300
    if not 0 < options.timeout <= 3600:
        raise CLIError(
            2, "invalid_timeout", "Timeout must be between zero and 3600 seconds."
        )
    try:
        commands = commands_for(root, options.level, options.impact_set, options.stage)
    except (ValueError, OSError, TypeError, AttributeError, SystemExit):
        raise CLIError(
            3,
            "invalid_run_gate",
            "Select a valid nonempty registered gate and matching level.",
        ) from None
    if getattr(options, "dry_run", False):
        return {
            "status": "PASS",
            "exit_code": 0,
            "errors": [],
            "artifacts": [],
            "steps": [],
            "commands": commands,
            "execution": "not_started",
        }
    if any(
        (directory / ".env").exists() or (directory / ".env").is_symlink()
        for directory in (root, *root.parents)
    ):
        raise CLIError(
            3,
            "ambient_dotenv",
            "Execute tests in an isolated checkout without ambient .env files.",
        )
    source_state = read_status(root)
    outcome = execute(root, commands, options.timeout)
    outcome["source_state_before"] = source_state
    outcome["source_state_after"] = read_status(root)
    outcome["uncommitted_source"] = any(
        state["tracked_changes"] or state["untracked_entries"]
        for state in (source_state, outcome["source_state_after"])
    )
    outcome["execution"] = "attempted"
    return outcome


def plan_tests(root: Path, options: argparse.Namespace) -> dict[str, Any]:
    # Load only this CLI checkout's trusted implementations, never Python from
    # an arbitrary --repo directory. The policy source is explicit in the result.
    if __package__ in (None, ""):
        sys.path.insert(0, str(ROOT))
    from tools.ci_scope import classify
    from tools.run_stage_gate import load_manifest, resolve

    if options.test_command != "plan" or not options.base:
        raise CLIError(
            2, "missing_plan_range", "test plan requires --base and a valid subcommand."
        )
    try:
        base = git(
            root,
            "rev-parse",
            "--verify",
            "--end-of-options",
            options.base + "^{commit}",
        )
        head = git(
            root,
            "rev-parse",
            "--verify",
            "--end-of-options",
            options.head + "^{commit}",
        )
        git(root, "merge-base", "--is-ancestor", base, head)
    except CLIError as error:
        if error.code == 5:
            raise
        raise CLIError(
            2, "invalid_plan_range", "Expected existing ancestor base and commit head."
        ) from None
    if head != git(root, "rev-parse", "HEAD"):
        raise CLIError(
            2,
            "plan_head_mismatch",
            "Runnable plans require the target checkout's current HEAD.",
        )
    paths = git(
        root, "diff", "--name-only", "--no-renames", "-z", base, head, "--"
    ).split("\0")
    policy_changes = git(
        root,
        "diff",
        "--name-only",
        "HEAD",
        "--",
        "tools/ci_scope.py",
        "tools/run_stage_gate.py",
        "tests/stage_gates.json",
    )
    if policy_changes and not options.include_working_tree:
        raise CLIError(
            3,
            "policy_modified",
            "Uncommitted gate changes require --include-working-tree.",
        )
    dirty = bool(git(root, "status", "--porcelain=v1", "--untracked-files=normal"))
    if options.include_working_tree:
        if head != git(root, "rev-parse", "HEAD"):
            raise CLIError(
                2,
                "working_tree_head",
                "Working changes can only be included at current HEAD.",
            )
        paths += git(
            root, "diff", "--name-only", "--no-renames", "-z", "HEAD", "--"
        ).split("\0")
        paths += git(root, "ls-files", "--others", "--exclude-standard", "-z").split(
            "\0"
        )
    changed = sorted(set(filter(None, paths)))
    if any(
        path != path.strip() or "\n" in path or "\r" in path or "\\" in path
        for path in changed
    ):
        raise CLIError(
            3, "unsupported_path", "Change paths require explicit manual scope review."
        )
    scope = classify(changed)
    selected = scope["impact_set"]
    tests: list[str] = []
    commands: list[list[str]] = []
    if selected:
        try:
            tests = resolve(
                load_manifest(root / "tests/stage_gates.json"),
                impact_set=selected,
                root=root,
            )
        except (SystemExit, OSError, ValueError, TypeError, AttributeError):
            raise CLIError(
                3, "invalid_gate", "Registered impact set is unavailable or invalid."
            ) from None
        if not tests:
            raise CLIError(
                3, "empty_gate", "An empty impact set cannot authorize test execution."
            )
        if any(not (root / path).is_file() for path in tests):
            raise CLIError(
                3,
                "missing_test",
                "Registered tests are missing in the target checkout.",
            )
        commands = [
            [
                sys.executable,
                str(root / "tools/run_stage_gate.py"),
                "--impact-set",
                selected,
            ]
        ]
    neutral = (
        all(name == "docs" for name in scope["categories"])
        and not scope["unknown_paths"]
    )
    return {
        "base_sha": base,
        "head_sha": head,
        "policy_root": str(ROOT),
        "changed_paths": changed,
        "scope": scope,
        "tests": tests,
        "commands": commands,
        "quick_checks": [
            [
                "ruff",
                "check",
                str(root / "src"),
                str(root / "tests"),
                str(root / "tools"),
            ],
            ["git", "-C", str(root), "diff", "--check", base, head, "--"],
            *(
                [["git", "-C", str(root), "diff", "--check", "HEAD", "--"]]
                if options.include_working_tree
                else []
            ),
            ["git", "-C", str(root), "status", "--short", "--untracked-files=no"],
        ],
        "quick_checks_require_empty_stdout": [
            "git status --short --untracked-files=no"
        ],
        "recommendation": "L1_named"
        if selected
        else "L0_only"
        if neutral or not changed
        else "scope_review",
        "execution": "not_started",
        "working_tree_included": options.include_working_tree,
        "working_tree_excluded": dirty and not options.include_working_tree,
        "requires_scope_review": bool(changed) and not selected and not neutral,
        "l3_automatic": False,
        "l3_rule": "Eligibility is not an instruction to run L3; explicit project gate and preflight required.",
    }


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
    return result.stdout.rstrip("\r\n")


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
        output = getattr(options, "output", None)
        if output is not None and not getattr(options, "dry_run", False):
            if output.exists() or output.is_symlink():
                raise CLIError(
                    3,
                    "output_exists",
                    "Output already exists; refusing execution or overwrite.",
                )
            if not output.parent.is_dir():
                raise CLIError(
                    3, "output_unavailable", "Output parent directory is unavailable."
                )
        help_requested = getattr(options, "help", False) or options.command == "help"
        if help_requested:
            if not getattr(options, "json", False):
                parser.print_help()
                return 0
            result["command"] = "help"
            result["data"] = {
                "commands": ["status", "doctor", "test plan", "test run", "help"],
                "side_effects": "test run executes the selected gate and writes isolated logs; other commands are read-only unless --output is explicit",
            }
        else:
            if not options.command:
                raise CLIError(2, "missing_command", "Select a command; see --help.")
            result["command"] = options.command
            root, result["head_sha"] = repository(getattr(options, "repo", ROOT))
            if options.command == "test":
                running = options.test_command == "run"
                result["command"] = "test run" if running else "test plan"
                result["data"] = (
                    run_tests(root, options) if running else plan_tests(root, options)
                )
                if running:
                    for key in ("status", "exit_code", "errors", "artifacts"):
                        result[key] = result["data"][key]
                else:
                    result["head_sha"] = result["data"]["head_sha"]
                if not running and result["data"]["requires_scope_review"]:
                    result.update(status="PARTIAL", exit_code=3)
                    result["errors"] = [
                        {
                            "code": "scope_review_required",
                            "message": "No single registered impact set covers these changes.",
                        }
                    ]
            elif options.command == "status":
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
            result["artifacts"] = [*result["artifacts"], str(output.absolute())]
            save_new(output, json.dumps(result, ensure_ascii=True))
    except KeyboardInterrupt:
        result.update(exit_code=5, status="BLOCKED")
        result["artifacts"] = []
        result["errors"] = [{"code": "cancelled", "message": "Operation cancelled."}]
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
