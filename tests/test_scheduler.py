from __future__ import annotations

import tempfile
import unittest

from mnemo.runtime import DaemonRunner, ScheduleService, run_local
from mnemo.runtime.scheduler import ensure_default_dream_schedule, next_due_time, parse_schedule_time, scheduled_prompt_items
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
            self.assertIn("exact user-visible push body", queue[0]["message"])
            self.assertIn("Use watch_feedback only for explicit policy changes", queue[0]["message"])
            self.assertIn("not for routine notified/silent outcomes", queue[0]["message"])
            self.assertNotIn("record watch_feedback", queue[0]["message"])
            self.assertNotIn("mnemo_watch_feedback", queue[0]["message"])
            self.assertEqual(queue[0]["metadata"]["scheduled_item_id"], item["id"])
            self.assertEqual(updated["status"], "active")
            self.assertEqual(updated["next_run_at"], 70.0)

    def test_tick_runs_due_dream_maintenance_and_refreshes_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("dream schedule")
            mission_id = store.create_mission(conversation_id, "dream schedule")
            run_id = store.create_run(conversation_id, mission_id, "remember dream schedule")
            candidate_id = store.add_memory_candidate(
                run_id,
                "User prefers scheduled Dream maintenance",
                confidence=0.9,
            )
            service = ScheduleService(tmp)
            item = service.add_dream(schedule="once", next_run_at=0, limit=10)

            result = service.tick(now=1, limit=10)

            queue = store.list_queue_items(status=None)
            updated = store.get_scheduled_item(item["id"])
            latest_report = store.state_dir / "runs" / "dream-reports" / "latest.json"
            snapshot = store.state_dir / "wiki" / "l1-memory-snapshot.json"
            processed = result["processed"][0]
            self.assertEqual(processed["scheduled_item_id"], item["id"])
            self.assertEqual(processed["status"], "dream_completed")
            self.assertEqual(processed["item_status"], "completed")
            self.assertEqual(processed["dream_report"]["mode"], "model_required")
            self.assertEqual(processed["dream_report"]["promoted"], 0)
            self.assertEqual(processed["dream_report"]["actions_applied"], 0)
            self.assertEqual(processed["dream_report"]["snapshot_items"], 0)
            self.assertEqual(queue, [])
            self.assertEqual(updated["status"], "completed")
            self.assertIsNone(updated["next_run_at"])
            self.assertEqual(updated["metadata"]["last_dream_report"]["id"], processed["dream_report"]["id"])
            self.assertEqual(store.get_memory_candidate(candidate_id)["status"], "draft")
            self.assertTrue(latest_report.exists())
            self.assertTrue(snapshot.exists())

    def test_tick_advances_recurring_dream_schedule(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = ScheduleService(tmp)
            item = service.add_dream(schedule="every:60", next_run_at=10, limit=5)

            result = service.tick(now=10, limit=10)

            updated = StateStore(tmp).get_scheduled_item(item["id"])
            self.assertEqual(result["processed"][0]["status"], "dream_completed")
            self.assertEqual(updated["status"], "active")
            self.assertEqual(updated["next_run_at"], 70.0)

    def test_ensure_default_dream_schedule_creates_immediate_auto_item_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first = ensure_default_dream_schedule(tmp, now=42)
            second = ensure_default_dream_schedule(tmp, now=99)

            item = first["item"]
            self.assertTrue(first["created"])
            self.assertFalse(second["created"])
            self.assertEqual(second["item"]["id"], item["id"])
            self.assertEqual(item["kind"], "dream")
            self.assertEqual(item["source"], "service")
            self.assertEqual(item["status"], "active")
            self.assertEqual(item["next_run_at"], 42.0)
            self.assertTrue(item["metadata"]["auto_dream"])
            self.assertEqual(item["metadata"]["dream"]["limit"], 20)
            self.assertEqual(len(ScheduleService(tmp).list_items(kind="dream", status=None, limit=10)), 1)

    def test_ensure_default_dream_schedule_respects_disabled_auto_item(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first = ensure_default_dream_schedule(tmp, now=42)
            service = ScheduleService(tmp)
            service.update_status(first["item"]["id"], "disabled")

            second = ensure_default_dream_schedule(tmp, now=99)

            self.assertFalse(second["created"])
            self.assertEqual(second["item"]["id"], first["item"]["id"])
            self.assertEqual(second["item"]["status"], "disabled")
            self.assertEqual(service.list_items(kind="dream", status="active", limit=10), [])

    def test_tick_can_process_only_due_dream_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = ScheduleService(tmp)
            cron = service.add_cron(message="remember: should stay queued later", schedule="once", next_run_at=0)
            dream = service.add_dream(schedule="once", next_run_at=0, limit=5)

            def fake_dream_runner(_item: dict) -> dict:
                return {
                    "id": "dream_fake",
                    "completed_at": 1,
                    "execution": {
                        "mode": "model_tool_calls",
                        "result": {
                            "promoted": [],
                            "rejected": [],
                            "skipped": [],
                            "conflicts": [],
                            "counts": {"tool_calls": 0},
                            "actions": {"counts": {"applied": 0, "skipped": 0}},
                            "snapshot": {"page_count": 0},
                        },
                    },
                }

            result = service.tick(now=1, limit=10, kind="dream", dream_runner=fake_dream_runner)

            store = StateStore(tmp)
            self.assertEqual([item["scheduled_item_id"] for item in result["processed"]], [dream["id"]])
            self.assertEqual(store.get_scheduled_item(dream["id"])["status"], "completed")
            self.assertEqual(store.get_scheduled_item(cron["id"])["status"], "active")
            self.assertEqual(store.get_scheduled_item(cron["id"])["next_run_at"], 0.0)
            self.assertEqual(store.list_queue_items(status=None), [])

    def test_scheduled_prompt_items_include_active_and_paused_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = ScheduleService(tmp)
            active = service.add_watch(target="Active watch", instruction="Check active", schedule="daily")
            paused = service.add_watch(target="Paused watch", instruction="Check paused", schedule="daily")
            completed = service.add_cron(message="done", schedule="once", next_run_at=0)
            dream = service.add_dream(schedule="daily")
            service.update_status(paused["id"], "paused")
            service.update_status(completed["id"], "completed")

            cards = scheduled_prompt_items(StateStore(tmp), limit=10)

            self.assertEqual([item["id"] for item in cards], [active["id"], paused["id"]])
            self.assertNotIn(dream["id"], [item["id"] for item in cards])

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
