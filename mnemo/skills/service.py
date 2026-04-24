from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from ..storage import StateStore
from .filesystem import SkillFile, load_skill_metadata, scan_skill_files


class SkillService:
    def __init__(self, store: StateStore, roots: list[str | Path] | None = None):
        self.store = store
        self.roots = [Path(root).expanduser() for root in roots or []]

    def scan(self) -> list[dict[str, Any]]:
        scanned = scan_skill_files(self.roots)
        for skill in scanned:
            self.store.upsert_skill(
                skill.name,
                skill.description,
                skill.body,
                source=f"file:{skill.path}",
                status="active",
                path=str(skill.path),
            )
        return [_skill_file_as_dict(skill) for skill in scanned]

    def list(self) -> list[dict[str, Any]]:
        return self.store.list_skills()

    def context_cards(self, limit: int = 12) -> list[dict[str, Any]]:
        return [_skill_context_card(skill) for skill in self.store.list_skills()[:limit]]

    def view(self, name: str) -> dict[str, Any] | None:
        return self.store.get_skill(name)

    def promote(self, name: str) -> dict[str, Any]:
        skill = self.store.get_skill(name)
        if not skill:
            raise ValueError(f"Skill not found: {name}")

        target_dir = self.store.state_dir / "skills" / "_generated" / _slug(name)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / "SKILL.md"
        target_path.write_text(_skill_markdown(skill), encoding="utf-8")
        self.store.update_skill_status(name, "active", source="generated", path=str(target_path))
        promoted = self.store.get_skill(name) or skill
        return {
            "name": name,
            "path": str(target_path),
            "skill": promoted,
        }


def default_skill_roots(state_dir: str | Path, workspace: str | Path | None = None) -> list[Path]:
    workspace_path = Path(workspace or Path.cwd()).expanduser()
    state_path = Path(state_dir).expanduser()
    return [
        state_path / "skills",
        workspace_path / ".mnemo" / "skills",
        workspace_path / ".agents" / "skills",
    ]


def _skill_file_as_dict(skill: SkillFile) -> dict[str, Any]:
    return {
        "name": skill.name,
        "description": skill.description,
        "body": skill.body,
        "path": str(skill.path),
        "source_root": str(skill.source_root),
        "metadata": skill.metadata,
    }


def _skill_context_card(skill: dict[str, Any]) -> dict[str, Any]:
    metadata = _skill_metadata(skill)
    card = {
        "name": skill["name"],
        "description": skill.get("description", ""),
        "status": skill.get("status", "unknown"),
        "source": skill.get("source", ""),
        "path": skill.get("path"),
    }

    allowed_tools = _metadata_allowed_tools(metadata)
    if allowed_tools:
        card["allowed_tools"] = allowed_tools

    for key in ("arguments", "scope"):
        if key in metadata:
            card[key] = metadata[key]

    if not card.get("source") and "source" in metadata:
        card["source"] = metadata["source"]
    if not card.get("path") and "path" in metadata:
        card["path"] = metadata["path"]

    return card


def _skill_metadata(skill: dict[str, Any]) -> dict[str, Any]:
    metadata = skill.get("metadata")
    if isinstance(metadata, dict):
        return metadata

    path = skill.get("path")
    if not path:
        return {}
    return load_skill_metadata(path)


def _metadata_allowed_tools(metadata: dict[str, Any]) -> list[str]:
    value = metadata.get("allowed_tools", metadata.get("allowed-tools", []))
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item]
    if isinstance(value, str) and value:
        return [value]
    return []


def _skill_markdown(skill: dict[str, Any]) -> str:
    return "\n".join(
        [
            "---",
            f"name: {skill['name']}",
            f"description: {skill.get('description', '')}",
            "---",
            "",
            skill.get("body", "").strip(),
            "",
        ]
    )


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-").lower()
    return slug or "skill"
