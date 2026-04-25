from __future__ import annotations

import tempfile
import unittest

from mnemo.runtime import DaemonRunner, ScheduleService, run_local
from mnemo.runtime.scheduler import next_due_time, parse_schedule_time
from mnemo.storage import StateStore


class ScheduleServiceTests(unittest.TestCase):
    def test_tick_enqueues_due_cron_and_completes_one_shot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = ScheduleService(tmp)
            item = service.add_cron(
                title="Memory upkeep",
                message="remember: scheduled cron preference",
                schedule="once",
                next_run_at=0,
            )

            result = service.tick(now=1, limit=10)

            store = StateStore(tmp)
            queue = store.list_queue_items(status="pending")
            updated = store.get_scheduled_item(item["id"])
            self.assertEqual(result["processed"][0]["scheduled_item_id"], item["id"])
            self.assertEqual(queue[0]["metadata"]["source"], "scheduler")
            self.assertEqual(queue[0]["metadata"]["scheduled_kind"], "cron")
            self.assertEqual(queue[0]["message"], "remember: scheduled cron preference")
            self.assertEqual(updated["status"], "completed")
            self.assertIsNone(updated["next_run_at"])

    def test_tick_enqueues_due_watch_and_advances_interval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = ScheduleService(tmp)
            item = service.add_watch(
                target="Rust progress",
                instruction="Check blockers and decide whether to notify the user.",
                schedule="every:60",
                next_run_at=10,
            )

            result = service.tick(now=10, limit=10)

            store = StateStore(tmp)
            queue = store.list_queue_items(status="pending")
            updated = store.get_scheduled_item(item["id"])
            self.assertEqual(result["processed"][0]["queue_id"], queue[0]["id"])
            self.assertIn("Watch check: Rust progress", queue[0]["message"])
            self.assertEqual(queue[0]["metadata"]["scheduled_item_id"], item["id"])
            self.assertEqual(updated["status"], "active")
            self.assertEqual(updated["next_run_at"], 70.0)

    def test_daemon_can_drain_scheduler_queue_through_existing_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = ScheduleService(tmp)
            service.add_cron(
                message="remember: scheduler drain should reuse daemon runtime",
                schedule="once",
                next_run_at=0,
            )
            service.tick(now=1)

            drained = DaemonRunner(tmp).drain(run_local, limit=5)

            store = StateStore(tmp)
            self.assertEqual(drained["processed"][0]["status"], "completed")
            self.assertEqual(store.queue_stats()["counts"]["completed"], 1)
            self.assertEqual(
                store.search_memory_candidates("scheduler drain")[0]["claim"],
                "scheduler drain should reuse daemon runtime",
            )

    def test_schedule_time_parsing_and_intervals(self) -> None:
        self.assertEqual(parse_schedule_time(12), 12.0)
        self.assertEqual(parse_schedule_time("12.5"), 12.5)
        self.assertEqual(next_due_time("every 2m", after=10), 130.0)
        self.assertEqual(next_due_time("hourly", after=10), 3610.0)
        self.assertIsNone(next_due_time("once", after=10))
        with self.assertRaisesRegex(ValueError, "unsupported schedule"):
            next_due_time("0 9 * * 1", after=10)


if __name__ == "__main__":
    unittest.main()
