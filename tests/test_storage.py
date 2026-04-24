from __future__ import annotations

import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

from mnemo.core.jsonutil import dumps
from mnemo.storage import SCHEMA_VERSION, StateStore


class StateStoreTests(unittest.TestCase):
    def test_initialize_creates_schema_and_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()

            self.assertTrue((Path(tmp) / "state.db").exists())
            self.assertTrue((Path(tmp) / "wiki").is_dir())
            self.assertTrue((Path(tmp) / "skills").is_dir())
            self.assertTrue((Path(tmp) / "runs").is_dir())
            self.assertTrue((Path(tmp) / "artifacts").is_dir())
            self.assertEqual(store.schema_version(), SCHEMA_VERSION)
            self.assertEqual([item["version"] for item in store.applied_migrations()], [1, 2, 3, 4])
            self.assertIn("event_outbox", _tables(Path(tmp) / "state.db"))
            self.assertIn("run_queue", _tables(Path(tmp) / "state.db"))

    def test_initialize_is_idempotent_for_schema_migrations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            first = store.applied_migrations()

            store.initialize()
            second = store.applied_migrations()

            self.assertEqual(store.schema_version(), SCHEMA_VERSION)
            self.assertEqual([item["version"] for item in first], [1, 2, 3, 4])
            self.assertEqual([item["version"] for item in second], [1, 2, 3, 4])
            self.assertEqual(len(first), len(second))

    def test_initialize_upgrades_legacy_schema_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "state.db"
            conn = sqlite3.connect(db_path)
            try:
                conn.executescript(
                    """
                    CREATE TABLE schema_meta (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );
                    INSERT INTO schema_meta(key, value) VALUES('schema_version', '1');

                    CREATE TABLE skills (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL UNIQUE,
                        description TEXT NOT NULL,
                        body TEXT NOT NULL,
                        status TEXT NOT NULL,
                        source TEXT NOT NULL,
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL
                    );
                    INSERT INTO skills(
                        id, name, description, body, status, source, created_at, updated_at
                    ) VALUES(
                        'skill_legacy', 'legacy', 'Legacy skill', 'Legacy body',
                        'draft', 'generated', 1.0, 1.0
                    );

                    CREATE TABLE eval_cases (
                        id TEXT PRIMARY KEY,
                        run_id TEXT NOT NULL,
                        name TEXT NOT NULL,
                        case_json TEXT NOT NULL,
                        status TEXT NOT NULL,
                        created_at REAL NOT NULL
                    );
                    INSERT INTO eval_cases(
                        id, run_id, name, case_json, status, created_at
                    ) VALUES('eval_legacy', 'run_legacy', 'legacy eval', '{}', 'draft', 1.0);

                    CREATE TABLE working_notes (
                        id TEXT PRIMARY KEY,
                        mission_id TEXT NOT NULL,
                        run_id TEXT NOT NULL,
                        content TEXT NOT NULL,
                        created_at REAL NOT NULL
                    );
                    INSERT INTO working_notes(
                        id, mission_id, run_id, content, created_at
                    ) VALUES('note_legacy', 'mis_legacy', 'run_legacy', 'Legacy note', 1.0);
                    """
                )
            finally:
                conn.close()

            store = StateStore(tmp)
            store.initialize()

            self.assertEqual(store.schema_version(), SCHEMA_VERSION)
            self.assertEqual([item["version"] for item in store.applied_migrations()], [1, 2, 3, 4])
            self.assertIn("path", _columns(db_path, "skills"))
            self.assertIn("result_json", _columns(db_path, "eval_cases"))
            self.assertIn("metadata_json", _columns(db_path, "working_notes"))
            self.assertIn("event_outbox", _tables(db_path))
            self.assertIn("run_queue", _tables(db_path))
            self.assertIsNone(store.get_skill("legacy")["path"])
            self.assertEqual(store.get_eval_case("eval_legacy")["result"], {})
            legacy_note = store.list_working_notes(status=None)[0]
            self.assertEqual(legacy_note["metadata"], {})
            self.assertEqual(legacy_note["result"], {})
            self.assertEqual(legacy_note["status"], "open")

    def test_run_ledger_events_are_sequenced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("test")
            mission_id = store.create_mission(conversation_id, "test mission")
            run_id = store.create_run(conversation_id, mission_id, "hello")

            first = store.append_event(run_id, "request.received", {"message": "hello"})
            second = store.append_event(run_id, "run.completed", {"status": "completed"})

            events = store.get_run_events(run_id)
            self.assertEqual((first, second), (1, 2))
            self.assertEqual([event["seq"] for event in events], [1, 2])
            self.assertEqual(events[0]["payload"]["message"], "hello")
            outbox = store.list_outbox_events()
            self.assertEqual([event["topic"] for event in outbox], ["request.received", "run.completed"])
            self.assertEqual(outbox[0]["aggregate_id"], run_id)
            self.assertEqual(outbox[0]["payload"]["seq"], 1)
            self.assertEqual(outbox[0]["payload"]["event_type"], "request.received")
            self.assertEqual(outbox[0]["payload"]["payload"], {"message": "hello"})

    def test_outbox_enqueue_list_and_mark_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            future_id = store.enqueue_outbox_event(
                "manual.future",
                {"value": 1},
                aggregate_id="agg_1",
                available_at=9999999999.0,
            )
            ready_id = store.enqueue_outbox_event("manual.ready", {"value": 2}, aggregate_id="agg_2", available_at=0.0)

            pending = store.list_outbox_events()
            all_events = store.list_outbox_events(status=None)
            store.mark_outbox_event(ready_id, "failed", error="delivery failed")
            failed = store.list_outbox_events(status="failed")
            store.mark_outbox_event(ready_id, "sent")
            sent = store.list_outbox_events(status="sent")

            self.assertEqual([event["id"] for event in pending], [ready_id])
            self.assertEqual([event["id"] for event in all_events], [ready_id, future_id])
            self.assertEqual(failed[0]["attempts"], 1)
            self.assertEqual(failed[0]["last_error"], "delivery failed")
            self.assertEqual(sent[0]["id"], ready_id)
            self.assertIsNone(sent[0]["last_error"])

    def test_mark_outbox_event_rejects_invalid_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            event_id = store.enqueue_outbox_event("manual.ready", {})

            with self.assertRaisesRegex(ValueError, "invalid outbox status"):
                store.mark_outbox_event(event_id, "unknown")

    def test_run_queue_lifecycle_and_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            queue_id = store.enqueue_run_request(
                "remember: queued storage",
                metadata={"source": "test"},
            )

            pending = store.list_queue_items(status="pending")
            claimed = store.claim_next_queue_item("worker-1")
            store.heartbeat_queue_item(queue_id)
            store.complete_queue_item(queue_id, "completed", run_id="run_storage")
            completed = store.list_queue_items(status="completed")

            self.assertEqual(pending[0]["id"], queue_id)
            self.assertEqual(pending[0]["metadata"], {"source": "test"})
            self.assertEqual(claimed["status"], "running")
            self.assertEqual(claimed["attempts"], 1)
            self.assertEqual(completed[0]["run_id"], "run_storage")
            self.assertEqual(store.queue_stats()["counts"]["completed"], 1)

            stale_id = store.enqueue_run_request("remember: stale storage")
            store.claim_next_queue_item("worker-2")
            with store.connect() as conn:
                conn.execute(
                    "UPDATE run_queue SET claimed_at = 0, heartbeat_at = 0 WHERE id = ?",
                    (stale_id,),
                )
            recovered = store.recover_stale_queue_items(stale_after_s=1.0)

            self.assertEqual(recovered[0]["id"], stale_id)
            self.assertEqual(recovered[0]["status"], "pending")
            self.assertEqual(store.list_queue_items(status="pending")[0]["id"], stale_id)

    def test_run_queue_rejects_invalid_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            queue_id = store.enqueue_run_request("valid")

            with self.assertRaisesRegex(ValueError, "queue message is required"):
                store.enqueue_run_request("   ")
            with self.assertRaisesRegex(ValueError, "invalid queue status"):
                store.list_queue_items(status="unknown")
            with self.assertRaisesRegex(ValueError, "invalid queue completion status"):
                store.complete_queue_item(queue_id, "running")

    def test_memory_candidate_search_and_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("test")
            mission_id = store.create_mission(conversation_id, "test mission")
            run_id = store.create_run(conversation_id, mission_id, "remember")

            candidate_id = store.add_memory_candidate(
                run_id,
                "User prefers concise engineering updates",
                dimension="communication",
                confidence=0.8,
                evidence=[{"kind": "test"}],
            )

            matches = store.search_memory_candidates("concise")
            self.assertEqual(matches[0]["id"], candidate_id)
            self.assertEqual(store.get_memory_candidate(candidate_id)["claim"], matches[0]["claim"])

    def test_working_notes_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("test")
            mission_id = store.create_mission(conversation_id, "test mission")
            run_id = store.create_run(conversation_id, mission_id, "note")

            note_id = store.add_working_note(
                mission_id,
                run_id,
                "User wants terse implementation updates",
                metadata={"retention": "memory_candidate", "confidence": 0.8},
            )
            open_notes = store.list_working_notes()
            store.update_working_note_status(note_id, "candidate_created", result={"candidate_id": "mem_1"})
            processed = store.list_working_notes(status="candidate_created")

            self.assertEqual(open_notes[0]["id"], note_id)
            self.assertEqual(open_notes[0]["metadata"]["retention"], "memory_candidate")
            self.assertEqual(open_notes[0]["status"], "open")
            self.assertEqual(processed[0]["result"], {"candidate_id": "mem_1"})
            self.assertIsNotNone(processed[0]["processed_at"])

    def test_skill_usage_events_and_stats(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("test")
            mission_id = store.create_mission(conversation_id, "test mission")
            run_id = store.create_run(conversation_id, mission_id, "skill")
            store.upsert_skill("writer", "Draft concise notes", "Body", status="active")

            view_id = store.record_skill_usage(
                run_id,
                "writer",
                "viewed",
                evidence=[{"kind": "tool_call"}],
            )
            outcome_id = store.record_skill_usage(
                run_id,
                "writer",
                "outcome",
                outcome="success",
                score=0.8,
                evidence=[{"kind": "user_feedback"}],
            )

            usage = store.list_skill_usage("writer")
            stats = store.skill_usage_stats()["writer"]

            self.assertEqual({event["id"] for event in usage}, {view_id, outcome_id})
            self.assertEqual(usage[0]["evidence"], [{"kind": "user_feedback"}])
            self.assertEqual(stats["uses"], 2)
            self.assertEqual(stats["views"], 1)
            self.assertEqual(stats["outcomes"], 1)
            self.assertEqual(stats["successes"], 1)
            self.assertEqual(stats["avg_score"], 0.8)

    def test_tool_candidates_and_eval_cases_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("test")
            mission_id = store.create_mission(conversation_id, "test mission")
            run_id = store.create_run(conversation_id, mission_id, "tools")

            candidate_id = store.add_tool_candidate(
                run_id,
                "fetch_page",
                {"description": "Fetch pages", "risk": "read", "input_schema": {"type": "object"}},
            )
            case_id = store.add_eval_case(
                run_id,
                "fetch_page smoke",
                {"tool_candidate": "fetch_page", "assert": "returns text"},
            )
            store.update_tool_candidate_status(candidate_id, "ready")
            store.update_eval_case_status(case_id, "passed", result={"ok": True})

            candidate = store.get_tool_candidate(candidate_id)
            cases = store.list_eval_cases(status="passed", tool_name="fetch_page")
            listed = store.list_tool_candidates(status="ready")

            self.assertEqual(candidate["status"], "ready")
            self.assertEqual(candidate["spec"]["risk"], "read")
            self.assertEqual(listed[0]["id"], candidate_id)
            self.assertEqual(cases[0]["id"], case_id)
            self.assertEqual(cases[0]["case"]["tool_candidate"], "fetch_page")
            self.assertEqual(cases[0]["result"], {"ok": True})

    def test_eval_cases_can_filter_by_skill_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("test")
            mission_id = store.create_mission(conversation_id, "test mission")
            run_id = store.create_run(conversation_id, mission_id, "skills")

            writer_case = store.add_eval_case(run_id, "writer smoke", {"skill_name": "writer"})
            store.add_eval_case(run_id, "reader smoke", {"skill_candidate": "reader"})
            store.update_eval_case_status(writer_case, "passed", result={"ok": True})

            writer_cases = store.list_eval_cases(status="passed", skill_name="writer")
            reader_cases = store.list_eval_cases(skill_name="reader")

            self.assertEqual([case["id"] for case in writer_cases], [writer_case])
            self.assertEqual(reader_cases[0]["case"]["skill_candidate"], "reader")

    def test_export_and_import_state_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            target = root / "target"
            archive = root / "mnemo-backup.zip"
            store = StateStore(source)
            store.initialize()
            conversation_id = store.create_conversation("backup")
            mission_id = store.create_mission(conversation_id, "backup mission")
            run_id = store.create_run(conversation_id, mission_id, "backup")
            store.append_event(run_id, "backup.test", {"ok": True})
            candidate_id = store.add_memory_candidate(run_id, "Backup round trip preference", confidence=0.9)
            page_id = store.upsert_memory_page(
                "Backup Round Trip",
                "Backup round trip preference",
                source_candidate_id=candidate_id,
            )
            (source / "wiki" / "prefs.md").write_text("Backup round trip preference", encoding="utf-8")

            exported = store.export_state(archive)

            self.assertTrue(archive.exists())
            self.assertEqual(exported["schema_version"], SCHEMA_VERSION)
            with zipfile.ZipFile(archive, "r") as exported_archive:
                names = set(exported_archive.namelist())
            self.assertIn("manifest.json", names)
            self.assertIn("state.db", names)
            self.assertIn("wiki/prefs.md", names)

            restored = StateStore(target)
            imported = restored.import_state(archive)

            self.assertEqual(imported["schema_version"], SCHEMA_VERSION)
            self.assertEqual(restored.get_memory_page(page_id)["title"], "Backup Round Trip")
            self.assertEqual(restored.get_run_events(run_id)[0]["payload"], {"ok": True})
            outbox = restored.list_outbox_events()
            self.assertEqual(outbox[0]["topic"], "backup.test")
            self.assertEqual((target / "wiki" / "prefs.md").read_text(encoding="utf-8"), "Backup round trip preference")

    def test_import_state_rejects_non_empty_target_without_replace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            target = root / "target"
            archive = root / "mnemo-backup.zip"
            StateStore(source).export_state(archive)
            target_store = StateStore(target)
            target_store.initialize()

            with self.assertRaisesRegex(ValueError, "state directory is not empty"):
                target_store.import_state(archive)

            imported = target_store.import_state(archive, replace=True)
            self.assertEqual(imported["schema_version"], SCHEMA_VERSION)

    def test_import_state_rejects_unsafe_archive_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "malicious.zip"
            target = root / "target"
            with zipfile.ZipFile(archive, "w") as malicious:
                malicious.writestr(
                    "manifest.json",
                    dumps(
                        {
                            "kind": "mnemo_state_export",
                            "schema_version": SCHEMA_VERSION,
                            "exported_at": 1.0,
                            "files": ["../escape.txt"],
                        }
                    ),
                )
                malicious.writestr("../escape.txt", "bad")

            with self.assertRaisesRegex(ValueError, "unsupported path|unsafe path"):
                StateStore(target).import_state(archive, replace=True)

            self.assertFalse((root / "escape.txt").exists())

def _columns(db_path: Path, table: str) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    finally:
        conn.close()
    return {str(row[1]) for row in rows}


def _tables(db_path: Path) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    finally:
        conn.close()
    return {str(row[0]) for row in rows}


if __name__ == "__main__":
    unittest.main()
