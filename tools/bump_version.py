import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

VERSION_FILES = [
    "config/runtime_state.yaml",
    "memory/internal_state.md",
    "memory/index.md",
    "src/mode_manager.py",
    "tests/test_packaging_guards.py",
    "tests/test_mode_manager_yaml.py",
]

README_FILE = "README.md"

VERSION_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def _parse(v: str) -> tuple[int, int, int]:
    m = VERSION_RE.match(v)
    if not m:
        raise ValueError(f"Invalid version: {v}")
    return int(m[1]), int(m[2]), int(m[3])


def _bump_patch(v: str) -> str:
    major, minor, patch = _parse(v)
    return f"v{major}.{minor}.{patch + 1}"


def _replace_versions(text: str, old_current: str, new_current: str, old_next: str, new_next: str) -> str:
    new_text = text.replace(old_next, new_next)
    new_text = new_text.replace(old_current, new_current)
    return new_text


def main():
    if len(sys.argv) != 2:
        print("Usage: python tools/bump_version.py <new_current_version>")
        print("Example: python tools/bump_version.py v0.7.4")
        sys.exit(1)

    new_current = sys.argv[1]
    _parse(new_current)

    yaml_path = ROOT / "config/runtime_state.yaml"
    if not yaml_path.is_file():
        print("ERROR: config/runtime_state.yaml not found")
        sys.exit(1)

    yaml_text = yaml_path.read_text(encoding="utf-8")

    m = re.search(r"^\s*current:\s+(v\d+\.\d+\.\d+)", yaml_text, re.MULTILINE)
    if not m:
        print("ERROR: Cannot find 'current:' in config/runtime_state.yaml")
        sys.exit(1)
    old_current = m.group(1)

    m = re.search(r"^\s*next:\s+(v\d+\.\d+\.\d+)", yaml_text, re.MULTILINE)
    old_next = m.group(1) if m else _bump_patch(old_current)

    if new_current == old_current:
        print(f"Already at {old_current}.")
        sys.exit(0)

    if _parse(new_current) <= _parse(old_current):
        print(f"ERROR: {new_current} must be greater than current {old_current}")
        sys.exit(1)

    expected_old_next = _bump_patch(old_current)
    if old_next != expected_old_next:
        print(f"WARNING: next ({old_next}) != expected patch bump ({expected_old_next})")
        print("State may be inconsistent; proceeding anyway.\n")

    new_next = _bump_patch(new_current)

    print(f"Bump:  {old_current}  ->  {new_current}")
    print(f"Next:  {old_next}  ->  {new_next}")
    print()

    for rel in VERSION_FILES:
        path = ROOT / rel
        if not path.is_file():
            print(f"  SKIP     {rel} (not found)")
            continue
        new_text = _replace_versions(
            path.read_text(encoding="utf-8"),
            old_current, new_current, old_next, new_next,
        )
        if new_text != path.read_text(encoding="utf-8"):
            path.write_text(new_text, encoding="utf-8")
            print(f"  UPDATED  {rel}")
        else:
            print(f"  OK       {rel}")

    readme_path = ROOT / README_FILE
    if readme_path.is_file():
        readme_text = readme_path.read_text(encoding="utf-8")
        new_text = readme_text.replace(old_next, new_next)
        if new_text != readme_text:
            readme_path.write_text(new_text, encoding="utf-8")
            print(f"  UPDATED  {README_FILE} (next version bumped)")
            print(f"  NOTE:    Review README version history — add new {new_current} entry manually.")
        else:
            print(f"  OK       {README_FILE}")

    print()
    print("Done. Run `pytest -q` to verify.")


if __name__ == "__main__":
    main()
