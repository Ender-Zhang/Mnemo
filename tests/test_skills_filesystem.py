from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mnemo.skills import SkillService, default_skill_roots, load_skill_file, scan_skill_files
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

    def test_default_skill_roots_include_mainstream_clients_and_dedupe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            state_dir = root / "state"

            roots = default_skill_roots(state_dir, workspace=workspace, home=workspace)

            self.assertEqual(
                roots,
                [
                    state_dir / "skills",
                    workspace / ".mnemo" / "skills",
                    workspace / ".agents" / "skills",
                    workspace / ".claude" / "skills",
                    workspace / ".hermes" / "skills",
                    workspace / ".openclaw" / "skills",
                ],
            )

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

    def test_install_local_skill_dir_copies_files_and_activates_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "external" / "writer"
            references = source / "references"
            references.mkdir(parents=True)
            (source / "SKILL.md").write_text(
                "---\nname: writer\ndescription: Write concise notes\n---\nUse short notes.",
                encoding="utf-8",
            )
            (references / "style.md").write_text("Keep it compact.", encoding="utf-8")
            store = StateStore(root / "state")
            store.initialize()

            result = SkillService(store).install(source)

            installed = result["skills"][0]
            installed_path = Path(installed["path"])
            stored = store.get_skill("writer")
            self.assertEqual(result["kind"], "skill_install_result")
            self.assertEqual(result["count"], 1)
            self.assertEqual(installed["status"], "active")
            self.assertEqual(stored["status"], "active")
            self.assertEqual(stored["source"], f"installed:{source}")
            self.assertEqual(Path(stored["path"]), installed_path)
            self.assertTrue(installed_path.exists())
            self.assertEqual((installed_path.parent / "references" / "style.md").read_text(encoding="utf-8"), "Keep it compact.")

    def test_install_multi_skill_root_and_duplicate_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "bundle"
            alpha = source / "alpha"
            beta = source / "nested" / "beta"
            alpha.mkdir(parents=True)
            beta.mkdir(parents=True)
            (alpha / "SKILL.md").write_text(
                "---\nname: alpha\ndescription: Alpha helper\n---\nUse alpha helper body.",
                encoding="utf-8",
            )
            (beta / "SKILL.md").write_text(
                "---\nname: beta\ndescription: Beta helper\n---\nUse beta helper body.",
                encoding="utf-8",
            )
            store = StateStore(root / "state")
            store.initialize()
            service = SkillService(store)

            result = service.install(source)

            self.assertEqual([skill["name"] for skill in result["skills"]], ["alpha", "beta"])
            self.assertEqual(store.get_skill("alpha")["status"], "active")
            self.assertEqual(store.get_skill("beta")["status"], "active")
            with self.assertRaisesRegex(ValueError, "Skill already exists: alpha"):
                service.install(source)

            forced = service.install(source, force=True)
            self.assertEqual(forced["count"], 2)

    def test_skill_context_cards_include_usage_stats_and_rank_by_score(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("skills")
            mission_id = store.create_mission(conversation_id, "skill ranking")
            run_id = store.create_run(conversation_id, mission_id, "rank skills")
            store.upsert_skill("alpha", "Lower scoring skill", "Alpha body", status="active")
            store.upsert_skill("zeta", "Higher scoring skill", "Zeta body", status="active")
            store.record_skill_usage(run_id, "alpha", "outcome", outcome="failure", score=-0.5)
            store.record_skill_usage(run_id, "zeta", "viewed")
            store.record_skill_usage(run_id, "zeta", "outcome", outcome="success", score=0.9)

            cards = SkillService(store).context_cards()

            self.assertEqual([card["name"] for card in cards], ["zeta", "alpha"])
            self.assertEqual(cards[0]["usage"]["uses"], 2)
            self.assertEqual(cards[0]["usage"]["views"], 1)
            self.assertEqual(cards[0]["usage"]["successes"], 1)
            self.assertEqual(cards[0]["usage"]["avg_score"], 0.9)
            self.assertNotIn("body", cards[0])

    def test_review_marks_valid_draft_ready_and_invalid_draft_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            store.upsert_skill(
                "writer",
                "Draft concise project notes",
                "Use short sentences and preserve concrete file references.",
                status="draft",
            )
            store.upsert_skill("bad", "", "tiny", status="draft")

            ready = SkillService(store).review("writer")
            blocked = SkillService(store).review("bad")

            self.assertEqual(ready["status"], "ready")
            self.assertEqual(store.get_skill("writer")["status"], "ready")
            self.assertTrue(blocked["status"].startswith("blocked:"))
            self.assertIn("missing_description", blocked["errors"])
            self.assertIn("body_too_short", blocked["errors"])

    def test_review_blocks_negative_usage_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("skills")
            mission_id = store.create_mission(conversation_id, "skill review")
            run_id = store.create_run(conversation_id, mission_id, "review")
            store.upsert_skill(
                "writer",
                "Draft concise project notes",
                "Use short sentences and preserve concrete file references.",
                status="draft",
            )
            store.record_skill_usage(run_id, "writer", "outcome", outcome="failure", score=-0.6)

            review = SkillService(store).review("writer")

            self.assertEqual(review["status"], "blocked:negative_usage")
            self.assertIn("negative_usage", review["errors"])
            self.assertEqual(review["usage"]["failures"], 1)

    def test_run_eval_case_records_passed_result_and_review_uses_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("skills")
            mission_id = store.create_mission(conversation_id, "skill eval")
            run_id = store.create_run(conversation_id, mission_id, "eval")
            store.upsert_skill(
                "writer",
                "Draft concise project notes",
                "Use short sentences and preserve concrete file references.",
                status="draft",
            )
            case_id = store.add_eval_case(
                run_id,
                "writer smoke",
                {
                    "skill_name": "writer",
                    "body_contains": ["short sentences"],
                    "description_contains": "concise",
                    "min_body_chars": 20,
                },
            )

            result = SkillService(store).run_eval_case(case_id)
            review = SkillService(store).review("writer")

            self.assertTrue(result["passed"])
            self.assertEqual(store.get_eval_case(case_id)["status"], "passed")
            self.assertEqual(review["status"], "ready")
            self.assertEqual(review["evals"]["passed_eval_case_ids"], [case_id])

    def test_review_blocks_linked_pending_or_failed_eval_cases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("skills")
            mission_id = store.create_mission(conversation_id, "skill eval")
            run_id = store.create_run(conversation_id, mission_id, "eval")
            store.upsert_skill(
                "writer",
                "Draft concise project notes",
                "Use short sentences and preserve concrete file references.",
                status="draft",
            )
            pending_id = store.add_eval_case(run_id, "writer pending", {"skill_name": "writer"})

            pending_review = SkillService(store).review("writer")
            store.update_eval_case_status(pending_id, "failed", result={"ok": False})
            failed_review = SkillService(store).review("writer")

            self.assertEqual(pending_review["status"], "blocked:missing_eval")
            self.assertIn("missing_eval", pending_review["errors"])
            self.assertEqual(failed_review["status"], "blocked:failed_eval")
            self.assertIn("failed_eval", failed_review["errors"])

    def test_run_eval_case_records_failed_result_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("skills")
            mission_id = store.create_mission(conversation_id, "skill eval")
            run_id = store.create_run(conversation_id, mission_id, "eval")
            store.upsert_skill(
                "writer",
                "Draft concise project notes",
                "Use short sentences and preserve concrete file references.",
                status="draft",
            )
            case_id = store.add_eval_case(
                run_id,
                "writer failing",
                {"skill_name": "writer", "body_contains": "never present"},
            )

            result = SkillService(store).run_eval_case(case_id)
            stored = store.get_eval_case(case_id)

            self.assertFalse(result["passed"])
            self.assertEqual(stored["status"], "failed")
            self.assertIn("body_missing_text", stored["result"]["errors"])

    def test_patch_candidate_creates_draft_without_mutating_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            store.upsert_skill(
                "writer",
                "Draft concise project notes",
                "Use short sentences and preserve concrete file references.",
                status="active",
            )

            result = SkillService(store).patch_candidate(
                "writer",
                "writer-more-specific",
                [{"old": "short sentences", "new": "short paragraphs"}],
                description="Draft concise project notes with paragraph guidance",
            )

            source = store.get_skill("writer")
            candidate = store.get_skill("writer-more-specific")
            self.assertEqual(result["status"], "draft")
            self.assertEqual(result["source_skill"], "writer")
            self.assertEqual(result["replacements"][0]["count"], 1)
            self.assertEqual(source["status"], "active")
            self.assertIn("short sentences", source["body"])
            self.assertEqual(candidate["status"], "draft")
            self.assertEqual(candidate["source"], "skill:writer:patch")
            self.assertIn("short paragraphs", candidate["body"])

    def test_patch_candidate_rejects_missing_skill_and_ambiguous_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            store.upsert_skill("writer", "Draft concise notes", "needle\nneedle\n", status="active")
            service = SkillService(store)

            with self.assertRaisesRegex(ValueError, "Skill not found"):
                service.patch_candidate("missing", "missing-patch", [{"old": "x", "new": "y"}])
            with self.assertRaisesRegex(ValueError, "ambiguous"):
                service.patch_candidate("writer", "writer-patch", [{"old": "needle", "new": "patched"}])

            accepted = service.patch_candidate(
                "writer",
                "writer-patch",
                [{"old": "needle", "new": "patched"}],
                replace_all=True,
            )

            self.assertEqual(accepted["replacements"][0]["count"], 2)
            self.assertIn("patched\npatched", store.get_skill("writer-patch")["body"])

    def test_crystallize_from_run_creates_draft_skill_from_compact_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("skills")
            mission_id = store.create_mission(conversation_id, "skill crystallization")
            run_id = store.create_run(conversation_id, mission_id, "draft release notes")
            store.append_event(
                run_id,
                "tool.result",
                {
                    "tool_name": "artifact_update",
                    "ok": True,
                    "summary": "Artifact updated.",
                    "result": {"body": "RAW SECRET PAYLOAD"},
                    "evidence": [{"kind": "artifact", "id": "artifact_1", "title": "Draft"}],
                },
            )
            store.append_event(run_id, "run.completed", {"status": "completed"})

            result = SkillService(store).crystallize_from_run(
                run_id,
                "artifact-sop",
                description="Capture artifact workflow",
                notes="Keep concise.",
            )
            skill = store.get_skill("artifact-sop")

            self.assertEqual(result["status"], "draft")
            self.assertEqual(result["tool_names"], ["artifact_update"])
            self.assertEqual(skill["status"], "draft")
            self.assertEqual(skill["source"], f"run:{run_id}:crystallized")
            self.assertIn("artifact_update", skill["body"])
            self.assertIn("Artifact updated.", skill["body"])
            self.assertNotIn("RAW SECRET PAYLOAD", skill["body"])

    def test_crystallize_from_run_rejects_incomplete_or_empty_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("skills")
            mission_id = store.create_mission(conversation_id, "skill crystallization")
            incomplete_run_id = store.create_run(conversation_id, mission_id, "draft release notes")
            empty_run_id = store.create_run(conversation_id, mission_id, "draft release notes")
            store.append_event(incomplete_run_id, "request.received", {"message": "draft release notes"})
            store.append_event(empty_run_id, "run.completed", {"status": "completed"})

            service = SkillService(store)

            with self.assertRaisesRegex(ValueError, "not completed"):
                service.crystallize_from_run(incomplete_run_id, "incomplete-sop")
            with self.assertRaisesRegex(ValueError, "no successful tool results"):
                service.crystallize_from_run(empty_run_id, "empty-sop")


if __name__ == "__main__":
    unittest.main()
