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
