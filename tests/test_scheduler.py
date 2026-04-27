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

    def test_watch_feedback_records_model_sparsify_decision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = ScheduleService(tmp)
            item = service.add_watch(
                target="Rust progress",
                instruction="Notify only for meaningful blockers.",
                schedule="every:60",
                next_run_at=0,
            )

            service.record_watch_feedback(item["id"], outcome="no_feedback", now=1)
            service.record_watch_feedback(item["id"], outcome="no_feedback", now=2)
            result = service.record_watch_feedback(
                item["id"],
                outcome="no_feedback",
                decision={
                    "action": "sparsify",
                    "schedule": "weekly",
                    "reason": "No response after three pushes.",
                    "source": "model",
                },
                now=3,
            )

            updated = StateStore(tmp).get_scheduled_item(item["id"])
            feedback = updated["metadata"]["watch_feedback"]
            self.assertEqual(result["kind"], "watch_feedback")
            self.assertEqual(feedback["counts"]["no_feedback"], 3)
            self.assertEqual(feedback["streaks"]["no_feedback"], 3)
            self.assertEqual(feedback["last_decision"]["source"], "model")
            self.assertEqual(updated["schedule"], "weekly")
            self.assertEqual(updated["status"], "active")
            self.assertEqual(updated["next_run_at"], 604803.0)

    def test_watch_feedback_rejects_non_watch_and_invalid_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = ScheduleService(tmp)
            cron = service.add_cron(message="remember: cron", schedule="once")
            watch = service.add_watch(target="Calendar", instruction="Check calendar", schedule="daily")

            with self.assertRaisesRegex(ValueError, "not a watch"):
                service.record_watch_feedback(cron["id"], outcome="no_feedback")
            with self.assertRaisesRegex(ValueError, "invalid watch feedback outcome"):
                service.record_watch_feedback(watch["id"], outcome="bad")
            with self.assertRaisesRegex(ValueError, "sparsify requires schedule"):
                service.record_watch_feedback(watch["id"], outcome="no_feedback", decision={"action": "sparsify"})

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
