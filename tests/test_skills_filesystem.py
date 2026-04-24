from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mnemo.skills import load_skill_file, scan_skill_files


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


if __name__ == "__main__":
    unittest.main()
