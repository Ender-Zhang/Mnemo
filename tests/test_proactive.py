from __future__ import annotations

import tempfile
import unittest

from mnemo.channels import FeishuChannelConfig, save_feishu_saved_config
from mnemo.core.models import RunRequest, RunResult
from mnemo.core.settings import save_user_settings
from mnemo.runtime import ScheduleService, run_local
from mnemo.runtime.proactive import ProactiveService, proactive_status
from mnemo.storage import StateStore


class ProactiveServiceTests(unittest.TestCase):
    def test_tick_delivers_due_cron_to_feishu_owner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake = RecordingFeishuClient()
            save_feishu_saved_config(
                tmp,
                {"app_id": "cli_test", "app_secret": "secret_test", "open_id": "ou_owner"},
            )
            ScheduleService(tmp).add_cron(
                title="Morning note",
                message="review today's plan",
                schedule="once",
                next_run_at=0,
            )

            result = ProactiveService(
                tmp,
                executor=run_local,
                feishu_client_factory=lambda _config: fake,
            ).tick(now=1, schedule_limit=10, drain_limit=5)

            self.assertEqual(result["delivery"]["processed"][0]["status"], "sent")
            self.assertEqual(len(fake.messages), 1)
            self.assertEqual(fake.messages[0]["receive_id"], "ou_owner")
            self.assertEqual(fake.messages[0]["receive_id_type"], "open_id")
            self.assertIn("Morning note", fake.messages[0]["markdown"])
            status = proactive_status(tmp)
            self.assertEqual(status["counts"]["sent"], 1)
            self.assertEqual(status["targets"]["primary"]["receive_id_type"], "open_id")

    def test_quiet_hours_defer_feishu_delivery_without_dropping_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake = RecordingFeishuClient()
            save_feishu_saved_config(
                tmp,
                {"app_id": "cli_test", "app_secret": "secret_test", "open_id": "ou_owner"},
            )
            save_user_settings(
                tmp,
                {
                    "quiet_hours": {
                        "enabled": True,
                        "start": "00:00",
                        "end": "23:59",
                        "timezone": "UTC",
                    }
                },
            )
            ScheduleService(tmp).add_cron(message="do not disturb", schedule="once", next_run_at=0)

            result = ProactiveService(
                tmp,
                executor=run_local,
                feishu_client_factory=lambda _config: fake,
            ).tick(now=60 * 60, schedule_limit=10, drain_limit=5)

            self.assertEqual(fake.messages, [])
            processed = result["delivery"]["processed"][0]
            self.assertEqual(processed["status"], "deferred")
            self.assertEqual(processed["reason"], "quiet_hours")
            self.assertGreater(processed["next_attempt_at"], 60 * 60)
            self.assertEqual(proactive_status(tmp)["counts"]["pending"], 1)

    def test_missing_feishu_binding_keeps_delivery_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake = RecordingFeishuClient()
            ScheduleService(tmp).add_cron(message="needs feishu", schedule="once", next_run_at=0)

            result = ProactiveService(
                tmp,
                executor=run_local,
                feishu_client_factory=lambda _config: fake,
            ).tick(now=1, schedule_limit=10, drain_limit=5)

            self.assertEqual(fake.messages, [])
            processed = result["delivery"]["processed"][0]
            self.assertEqual(processed["status"], "deferred")
            self.assertEqual(processed["reason"], "feishu_not_configured")
            self.assertEqual(proactive_status(tmp)["pending"], 1)

    def test_watch_model_silent_response_is_suppressed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake = RecordingFeishuClient()
            save_feishu_saved_config(
                tmp,
                {"app_id": "cli_test", "app_secret": "secret_test", "open_id": "ou_owner"},
            )
            watch = ScheduleService(tmp).add_watch(
                target="Market pulse",
                instruction="Notify only if action is needed.",
                schedule="once",
                next_run_at=0,
            )

            result = ProactiveService(
                tmp,
                executor=silent_executor,
                feishu_client_factory=lambda _config: fake,
            ).tick(now=1, schedule_limit=10, drain_limit=5)

            self.assertEqual(fake.messages, [])
            self.assertEqual(result["staged"][0]["status"], "suppressed")
            updated = StateStore(tmp).get_scheduled_item(watch["id"])
            self.assertEqual(updated["metadata"]["watch_feedback"]["last_outcome"], "silent")
            self.assertEqual(proactive_status(tmp)["counts"]["suppressed"], 1)


class RecordingFeishuClient:
    def __init__(self) -> None:
        self.config: FeishuChannelConfig | None = None
        self.messages: list[dict[str, str]] = []

    def send_markdown(self, receive_id: str, markdown: str, *, receive_id_type: str = "chat_id") -> list[str]:
        self.messages.append(
            {
                "receive_id": receive_id,
                "receive_id_type": receive_id_type,
                "markdown": markdown,
            }
        )
        return [f"om_proactive_{len(self.messages)}"]


def silent_executor(request: RunRequest) -> RunResult:
    store = StateStore(request.state_dir)
    store.initialize()
    conversation_id = request.conversation_id or store.create_conversation("silent proactive")
    mission_id = request.mission_id or store.create_mission(conversation_id, "silent proactive")
    run_id = store.create_run(conversation_id, mission_id, request.message)
    response = "[silent] No meaningful update."
    store.complete_run(run_id, response)
    return RunResult(
        conversation_id=conversation_id,
        mission_id=mission_id,
        run_id=run_id,
        response=response,
        tool_results=[],
    )


if __name__ == "__main__":
    unittest.main()
