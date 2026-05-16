import pathlib
import re
import sys
import zipfile

EXCLUDE_DIRS = {
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".git",
    ".github",
    ".vscode",
    ".idea",
    "venv",
    ".venv",
    "env",
    "node_modules",
    "logs",
    "backups",
    "exports",
    "release",
    "dist",
    "build",
    "图片资料",
}
EXCLUDE_KEYWORDS = ["visual_assets_pack"]
SKIP_SECRET_SCAN_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
SECRET_PATTERNS = [
    # OpenAI / generic sk-* patterns
    re.compile(r"sk-proj-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"sk-[A-Za-z0-9_\-]{30,}"),
    # GitHub personal access token
    re.compile(r"ghp_[A-Za-z0-9_]{30,}"),
    # OpenRouter API key
    re.compile(r"sk-or-v1-[A-Za-z0-9_\-]{20,}"),
    # Generic key / token / secret assignment
    re.compile(r"(?i)(api[_-]?key|token|secret)\s*[:=]\s*['\"][^'\"]{16,}"),
]


def should_exclude(rel: pathlib.Path, include_tests: bool = True) -> bool:
    posix = rel.as_posix()
    posix_lower = posix.lower()
    parts = rel.parts
    parts_lower = tuple(part.lower() for part in parts)
    name_lower = rel.name.lower()
    suffix_lower = rel.suffix.lower()

    exclude_dirs_lower = {item.lower() for item in EXCLUDE_DIRS}

    if parts_lower and parts_lower[0] in exclude_dirs_lower:
        return True

    if parts_lower and parts_lower[0].startswith("article_text_replacement_files"):
        return True

    if posix_lower.startswith("chat/archive/"):
        return True

    for kw in EXCLUDE_KEYWORDS:
        if kw.lower() in posix_lower:
            return True

    if suffix_lower in (".pyc", ".pyo", ".bak", ".tmp"):
        return True

    if suffix_lower in (".docx",):
        return True

    if name_lower == ".env":
        return True

    if name_lower.startswith(".env.") and name_lower not in {".env.example"}:
        return True

    if name_lower.endswith(".zip"):
        return True

    if posix_lower.startswith("tools/package_project_v") and name_lower.endswith(".ps1"):
        return True

    if not include_tests and parts_lower and parts_lower[0] == "tests":
        return True

    for part in parts_lower:
        if part in exclude_dirs_lower:
            return True

    return False


def scan_secret(path: pathlib.Path, root: pathlib.Path) -> None:
    if path.suffix.lower() in SKIP_SECRET_SCAN_SUFFIXES:
        return
    rel = path.relative_to(root).as_posix()
    if rel in {".env.example"}:
        return
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return
    for pat in SECRET_PATTERNS:
        if pat.search(text):
            print("ERROR: possible API key in", rel, file=sys.stderr)
            sys.exit(1)


def main() -> None:
    root = pathlib.Path(sys.argv[1])
    dest = pathlib.Path(sys.argv[2])
    dest.parent.mkdir(parents=True, exist_ok=True)
    include_tests = sys.argv[3] == "1"

    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        count = 0
        for file_path in sorted(root.rglob("*")):
            if not file_path.is_file():
                continue
            rel = file_path.relative_to(root)
            if should_exclude(rel, include_tests=include_tests):
                continue
            scan_secret(file_path, root)
            entry = rel.as_posix()
            zf.write(file_path, entry)
            count += 1
        names = zf.namelist()

    for path in names:
        path_lower = path.lower()
        base_name = pathlib.Path(path).name.lower()

        if "\\" in path:
            print("ERROR: backslash path:", path, file=sys.stderr)
            sys.exit(1)

        if base_name == ".env" or (base_name.startswith(".env.") and base_name != ".env.example"):
            print("ERROR: env file in zip:", path, file=sys.stderr)
            sys.exit(1)

        if path_lower.startswith("chat/archive/"):
            print("ERROR: chat archive in zip:", path, file=sys.stderr)
            sys.exit(1)

        if path_lower.endswith(".tmp"):
            print("ERROR: tmp file in zip:", path, file=sys.stderr)
            sys.exit(1)

        if path_lower.startswith("logs/") or path_lower.startswith("backups/") or path_lower.startswith("exports/"):
            print("ERROR: runtime output in zip:", path, file=sys.stderr)
            sys.exit(1)

    required = [
        "app.py",
        "requirements.txt",
        ".env.example",
        "src/wechat.py",
        "src/ui/wechat_panel.py",
        "src/safe_writer.py",
        "src/mode_manager.py",
        "src/llm_client.py",
        "tools/package_project.ps1",
        "tools/package_project_helper.py",
    ]
    missing = [item for item in required if item not in names]
    if missing:
        print("ERROR: missing:", missing, file=sys.stderr)
        sys.exit(1)

    print("OK:", count, "files, forward-slash verified")


if __name__ == "__main__":
    main()
