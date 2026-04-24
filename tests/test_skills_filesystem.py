from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mnemo.skills import SkillService, load_skill_file, scan_skill_files
from mnemo.storage import StateStore


class SkillFilesystemTests(unittest.TestCase):
    def test_frontmatter_parse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill_dir = root / "writer"
            skill_dir.mkdir()
            skill_path = skill_dir / "SKILL.md"
            skill_path.write_text(
                "\n".join(
                    [
                        "---",
                        "name: writing-helper",
                        "description: Draft concise prose",
                        "allowed-tools:",
                        "  - Read",
                        "  - Write",
                        "mnemo-origin: generated",
                        "---",
                        "Use short sentences.",
                    ]
                ),
                encoding="utf-8",
            )

            skill = load_skill_file(skill_path, source_root=root)

            self.assertEqual(skill.name, "writing-helper")
            self.assertEqual(skill.description, "Draft concise prose")
            self.assertEqual(skill.body, "Use short sentences.")
            self.assertEqual(skill.path, skill_path)
            self.assertEqual(skill.source_root, root)
            self.assertEqual(skill.metadata["allowed-tools"], ["Read", "Write"])
            self.assertEqual(skill.metadata["mnemo-origin"], "generated")

    def test_mainstream_metadata_parse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill_dir = root / "researcher"
            skill_dir.mkdir()
            skill_path = skill_dir / "SKILL.md"
            skill_path.write_text(
                "\n".join(
                    [
                        "---",
                        "name: researcher",
                        "description: Find and summarize sources",
                        "allowed_tools: Read, WebSearch",
                        "arguments:",
                        "  query: required",
                        "  depth: optional",
                        "scope: project",
                        "path: docs/research",
                        "source: imported",
                        "---",
                        "Full instructions stay out of compact cards.",
                    ]
                ),
                encoding="utf-8",
            )

            skill = load_skill_file(skill_path, source_root=root)

            self.assertEqual(skill.metadata["allowed_tools"], ["Read", "WebSearch"])
            self.assertEqual(skill.metadata["arguments"], {"query": "required", "depth": "optional"})
            self.assertEqual(skill.metadata["scope"], "project")
            self.assertEqual(skill.metadata["path"], "docs/research")
            self.assertEqual(skill.metadata["source"], "imported")

    def test_fallback_parse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill_dir = root / "fallback-skill"
            skill_dir.mkdir()
            skill_path = skill_dir / "SKILL.md"
            skill_path.write_text("\n\nFirst non-empty body line.\nMore detail.\n", encoding="utf-8")

            skill = load_skill_file(skill_path, source_root=root)

            self.assertEqual(skill.name, "fallback-skill")
            self.assertEqual(skill.description, "First non-empty body line.")
            self.assertEqual(skill.body, "First non-empty body line.\nMore detail.")
            self.assertEqual(skill.metadata, {})

    def test_nested_scan_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            alpha = root / "nested" / "alpha"
            beta = root / "beta"
            alpha.mkdir(parents=True)
            beta.mkdir()
            (alpha / "SKILL.md").write_text("---\nname: alpha\n---\nAlpha body", encoding="utf-8")
            (beta / "SKILL.md").write_text("---\nname: beta\n---\nBeta body", encoding="utf-8")

            skills = scan_skill_files([root])

            self.assertEqual([skill.name for skill in skills], ["alpha", "beta"])
            self.assertEqual([skill.source_root for skill in skills], [root, root])

    def test_skill_context_cards_omit_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            store.upsert_skill("writer", "Draft concise notes", "Full skill body", status="active")

            cards = SkillService(store).context_cards()

            self.assertEqual(cards[0]["name"], "writer")
            self.assertEqual(cards[0]["description"], "Draft concise notes")
            self.assertNotIn("body", cards[0])

    def test_skill_context_cards_include_compact_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "skill-root"
            skill_dir = root / "researcher"
            skill_dir.mkdir(parents=True)
            skill_path = skill_dir / "SKILL.md"
            skill_path.write_text(
                "\n".join(
                    [
                        "---",
                        "name: researcher",
                        "description: Find and summarize sources",
                        "allowed-tools: [Read, WebSearch]",
                        "arguments:",
                        "  query: required",
                        "scope: workspace",
                        "---",
                        "Full body should only be loaded by skill_view.",
                    ]
                ),
                encoding="utf-8",
            )
            store = StateStore(tmp)
            store.initialize()
            service = SkillService(store, roots=[root])
            service.scan()

            cards = service.context_cards()
            viewed = service.view("researcher")

            self.assertEqual(cards[0]["allowed_tools"], ["Read", "WebSearch"])
            self.assertEqual(cards[0]["arguments"], {"query": "required"})
            self.assertEqual(cards[0]["scope"], "workspace")
            self.assertEqual(cards[0]["path"], str(skill_path))
            self.assertNotIn("body", cards[0])
            self.assertIn("Full body should only be loaded by skill_view.", viewed["body"])


if __name__ == "__main__":
    unittest.main()
