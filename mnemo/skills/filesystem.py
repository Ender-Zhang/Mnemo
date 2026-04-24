from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SkillFile:
    name: str
    description: str
    body: str
    path: Path
    source_root: Path
    metadata: dict[str, Any] = field(default_factory=dict)


def scan_skill_files(source_roots: Iterable[str | Path]) -> list[SkillFile]:
    skills: list[SkillFile] = []
    for source_root in source_roots:
        root = Path(source_root)
        if not root.exists():
            continue
        for path in root.rglob("SKILL.md"):
            if path.is_file():
                skills.append(load_skill_file(path, source_root=root))
    return sorted(skills, key=lambda skill: (skill.name, str(skill.path)))


def load_skill_file(path: str | Path, *, source_root: str | Path | None = None) -> SkillFile:
    skill_path = Path(path)
    root = Path(source_root) if source_root is not None else skill_path.parent
    raw_content = skill_path.read_text(encoding="utf-8")
    metadata, body = _split_frontmatter(raw_content)

    body = body.strip()
    name = _metadata_string(metadata.get("name")) or skill_path.parent.name
    description = _metadata_string(metadata.get("description")) or _first_body_line(body)

    return SkillFile(
        name=name,
        description=description,
        body=body,
        path=skill_path,
        source_root=root,
        metadata=metadata,
    )


def _split_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, content

    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            frontmatter = "\n".join(lines[1:index])
            body = "\n".join(lines[index + 1 :])
            return _parse_frontmatter(frontmatter), body

    return {}, content


def _parse_frontmatter(frontmatter: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    current_list_key: str | None = None

    for raw_line in frontmatter.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if current_list_key and line.startswith("- "):
            list_value = line[2:].strip()
            if list_value:
                metadata[current_list_key].append(list_value)
            continue

        current_list_key = None
        if ":" not in line:
            continue

        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue

        if key == "allowed-tools":
            metadata[key] = [value] if value else []
            if not value:
                current_list_key = key
        else:
            metadata[key] = value

    return metadata


def _metadata_string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _first_body_line(body: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""
