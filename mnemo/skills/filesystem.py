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


_LIST_METADATA_KEYS = {"allowed-tools", "allowed_tools"}


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


def load_skill_metadata(path: str | Path) -> dict[str, Any]:
    skill_path = Path(path)
    try:
        with skill_path.open(encoding="utf-8") as handle:
            first_line = handle.readline()
            if first_line.strip() != "---":
                return {}

            frontmatter_lines: list[str] = []
            for line in handle:
                if line.strip() == "---":
                    return _parse_frontmatter("".join(frontmatter_lines))
                frontmatter_lines.append(line)
    except OSError:
        return {}

    return {}


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
    current_mapping_key: str | None = None

    for raw_line in frontmatter.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if current_list_key and raw_line[:1].isspace() and line.startswith("- "):
            list_value = _parse_scalar(line[2:].strip())
            metadata[current_list_key].append(list_value)
            continue

        if current_mapping_key and raw_line[:1].isspace():
            if line.startswith("- "):
                existing = metadata[current_mapping_key]
                if not isinstance(existing, list):
                    existing = []
                    metadata[current_mapping_key] = existing
                existing.append(_parse_scalar(line[2:].strip()))
                continue
            if ":" in line:
                key, value = line.split(":", 1)
                key = key.strip()
                if key:
                    existing = metadata[current_mapping_key]
                    if not isinstance(existing, dict):
                        existing = {}
                        metadata[current_mapping_key] = existing
                    existing[key] = _parse_scalar(value.strip())
            continue

        current_list_key = None
        current_mapping_key = None
        if ":" not in line:
            continue

        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue

        if key in _LIST_METADATA_KEYS:
            metadata[key] = _parse_list_value(value)
            if not value:
                current_list_key = key
        elif key == "arguments":
            metadata[key] = _parse_inline_collection(value)
            if not value:
                current_mapping_key = key
        else:
            metadata[key] = _parse_scalar(value)

    return metadata


def _parse_inline_collection(value: str) -> Any:
    if not value:
        return {}
    if value.startswith("[") and value.endswith("]"):
        return _parse_bracket_list(value)
    return _parse_scalar(value)


def _parse_list_value(value: str) -> list[Any]:
    if not value:
        return []
    if value.startswith("[") and value.endswith("]"):
        return _parse_bracket_list(value)
    if "," in value:
        return [_parse_scalar(part.strip()) for part in value.split(",") if part.strip()]
    return [_parse_scalar(value)]


def _parse_bracket_list(value: str) -> list[Any]:
    inner = value[1:-1].strip()
    if not inner:
        return []
    return [_parse_scalar(part.strip()) for part in inner.split(",") if part.strip()]


def _parse_scalar(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _metadata_string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _first_body_line(body: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""
