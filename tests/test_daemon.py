from __future__ import annotations

import tempfile
import unittest

from mnemo.core.errors import DaemonLockError
from mnemo.core.models import RunRequest
from mnemo.runtime import DaemonLock, DaemonRunner, run_local
from mnemo.storage import StateStore


class DaemonRunnerTests(unittest.TestCase):
    def test_drain_processes_queued_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runner = DaemonRunner(tmp)
            queue_id = runner.enqueue("remember: daemon queue")

            result = runner.drain(run_local, limit=5)

            processed = result["processed"][0]
            self.assertEqual(processed["id"], queue_id)
            self.assertEqual(processed["status"], "completed")
            self.assertTrue(processed["run_id"].startswith("run_"))
            store = StateStore(tmp)
            completed = store.list_queue_items(status="completed")
            self.assertEqual(completed[0]["id"], queue_id)
            self.assertEqual(completed[0]["run_id"], processed["run_id"])
            self.assertEqual(store.search_memory_candidates("daemon queue")[0]["claim"], "daemon queue")

    def test_drain_marks_failed_executor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runner = DaemonRunner(tmp)
            queue_id = runner.enqueue("fail me")

            def fail(_: RunRequest):
                raise RuntimeError("boom")

            result = runner.drain(fail)
            failed = StateStore(tmp).list_queue_items(status="failed")

            self.assertEqual(result["processed"], [{"id": queue_id, "status": "failed", "error": "boom"}])
            self.assertEqual(failed[0]["last_error"], "boom")

    def test_cancelled_queue_item_is_not_drained(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runner = DaemonRunner(tmp)
            queue_id = runner.enqueue("remember: cancelled daemon")

            cancelled = runner.cancel(queue_id, reason="user requested")
            result = runner.drain(run_local, limit=5)

            self.assertTrue(cancelled["changed"])
            self.assertEqual(cancelled["status"], "cancelled")
            self.assertEqual(result["processed"], [])
            self.assertEqual(StateStore(tmp).list_queue_items(status="cancelled")[0]["id"], queue_id)

    def test_recover_ingests_model_marked_w0_without_mutating_ephemeral_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("daemon w0")
            mission_id = store.create_mission(conversation_id, "recover w0")
            run_id = store.create_run(conversation_id, mission_id, "note")
            retained_note_id = store.add_working_note(
                mission_id,
                run_id,
                "User prefers daemon recovery to preserve implementation progress notes",
                metadata={"retention": "memory_candidate", "confidence": 0.83},
            )
            ephemeral_note_id = store.add_working_note(
                mission_id,
                run_id,
                "Temporary daemon scratchpad context",
                metadata={"retention": "ephemeral"},
            )

            result = DaemonRunner(tmp).recover()

            created = result["w0"]["created"][0]
            candidate = store.get_memory_candidate(created["candidate_id"])
            open_notes = {note["id"] for note in store.list_working_notes(status="open")}
            self.assertEqual(created["note_id"], retained_note_id)
            self.assertEqual(candidate["claim"], "User prefers daemon recovery to preserve implementation progress notes")
            self.assertEqual(store.list_working_notes(status="candidate_created")[0]["id"], retained_note_id)
            self.assertIn(ephemeral_note_id, open_notes)
            self.assertEqual(result["w0"]["pending_after"], 0)

    def test_drain_runs_w0_recovery_before_queue_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("daemon drain w0")
            mission_id = store.create_mission(conversation_id, "drain w0")
            run_id = store.create_run(conversation_id, mission_id, "note")
            note_id = store.add_working_note(
                mission_id,
                run_id,
                "User prefers daemon drain to recover marked W0 observations",
                metadata={"retention": "memory_candidate", "confidence": 0.8},
            )

            result = DaemonRunner(tmp).drain(run_local, limit=0)

            self.assertEqual(result["processed"], [])
            self.assertEqual(result["w0"]["created"][0]["note_id"], note_id)
            self.assertEqual(store.list_working_notes(status="candidate_created")[0]["id"], note_id)

    def test_lock_blocks_second_worker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock = DaemonLock(tmp)
            lock.acquire()
            try:
                with self.assertRaises(DaemonLockError):
                    DaemonRunner(tmp).drain(run_local)
            finally:
                lock.release()


if __name__ == "__main__":
    unittest.main()
