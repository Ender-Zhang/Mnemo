from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from ..storage import StateStore
from .filesystem import SkillFile, scan_skill_files


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
