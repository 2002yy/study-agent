"""Local, text-only skills. Importing a skill never executes its contents."""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any

import yaml

SKILL_STORE_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "local_skills.json"
)
MAX_CONTENT_LENGTH = 20_000
MAX_INSTALLED = 32
MAX_SELECTED = 3
MAX_SELECTED_LENGTH = 24_000
_STORE_LOCK = threading.RLock()
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")


class SkillNotFoundError(KeyError):
    """The requested installed skill does not exist."""


def _metadata(content: object) -> tuple[str, str]:
    if not isinstance(content, str) or not content or len(content) > MAX_CONTENT_LENGTH:
        raise ValueError("SKILL.md must contain 1–20000 characters")
    lines = content.removeprefix("\ufeff").splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("SKILL.md requires YAML frontmatter with name and description")
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        raise ValueError("SKILL.md frontmatter is not closed")
    try:
        metadata = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError as exc:
        raise ValueError("Invalid SKILL.md YAML frontmatter") from exc
    if not isinstance(metadata, dict):
        raise ValueError("SKILL.md frontmatter must be a mapping")
    name = metadata.get("name")
    description = metadata.get("description")
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ValueError(
            "Skill name must be 1–64 ASCII letters, digits, underscores or hyphens"
        )
    if not isinstance(description, str) or not 1 <= len(description.strip()) <= 1000:
        raise ValueError("Skill description must contain 1–1000 characters")
    if not "\n".join(lines[end + 1 :]).strip():
        raise ValueError("SKILL.md instructions are required after the frontmatter")
    return name, description.strip()


class SkillStore:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path is not None else SKILL_STORE_PATH

    def _read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise ValueError(
                "Local skill store is invalid; existing file was preserved"
            ) from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("skills"), list):
            raise ValueError("Local skill store is invalid")
        rows = payload["skills"]
        if len(rows) > MAX_INSTALLED:
            raise ValueError("Local skill store exceeds the installation limit")
        ids: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("Local skill store contains an invalid record")
            skill_id = row.get("id")
            if not isinstance(skill_id, str) or not skill_id or skill_id in ids:
                raise ValueError("Local skill store contains an invalid ID")
            ids.add(skill_id)
            name, description = _metadata(row.get("content"))
            if (
                row.get("name") != name
                or row.get("description") != description
                or type(row.get("enabled")) is not bool
            ):
                raise ValueError("Local skill store contains inconsistent metadata")
        return rows

    def _write(self, rows: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = stream.name
                json.dump({"skills": rows}, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                Path(temporary).unlink(missing_ok=True)

    def list_skills(self) -> list[dict[str, Any]]:
        with _STORE_LOCK:
            return self._read()

    def import_skill(self, content: str) -> dict[str, Any]:
        name, description = _metadata(content)
        with _STORE_LOCK:
            rows = self._read()
            if len(rows) >= MAX_INSTALLED:
                raise ValueError("At most 32 local skills may be installed")
            row = {
                "id": "skill_" + uuid.uuid4().hex,
                "name": name,
                "description": description,
                "content": content,
                "enabled": False,
            }
            self._write([*rows, row])
            return row

    def set_enabled(self, skill_id: str, enabled: bool) -> dict[str, Any]:
        if type(enabled) is not bool:
            raise ValueError("enabled must be a boolean")
        with _STORE_LOCK:
            rows = self._read()
            row = next((row for row in rows if row["id"] == skill_id), None)
            if row is None:
                raise SkillNotFoundError(skill_id)
            row["enabled"] = enabled
            self._write(rows)
            return row

    def delete(self, skill_id: str) -> None:
        with _STORE_LOCK:
            rows = self._read()
            if not any(row["id"] == skill_id for row in rows):
                raise SkillNotFoundError(skill_id)
            self._write([row for row in rows if row["id"] != skill_id])

    def get_enabled(self, ids: list[str]) -> list[dict[str, Any]]:
        if not isinstance(ids, list) or any(
            not isinstance(value, str) for value in ids
        ):
            raise ValueError("Selected skill IDs must be a list of strings")
        if len(ids) > MAX_SELECTED or len(ids) != len(set(ids)):
            raise ValueError("Select at most 3 distinct skills")
        if not ids:
            return []
        with _STORE_LOCK:
            indexed = {row["id"]: row for row in self._read()}
            selected = []
            for skill_id in ids:
                row = indexed.get(skill_id)
                if row is None:
                    raise SkillNotFoundError(skill_id)
                if not row["enabled"]:
                    raise ValueError(f"Skill is disabled: {skill_id}")
                selected.append(row)
            if sum(len(row["content"]) for row in selected) > MAX_SELECTED_LENGTH:
                raise ValueError("Selected skill contents exceed 24000 characters")
            return selected
