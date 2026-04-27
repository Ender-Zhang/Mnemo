from __future__ import annotations

import http.client
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from mnemo.interfaces.web import WebServerConfig, build_http_server
from mnemo.storage import StateStore


class WebInterfaceTests(unittest.TestCase):
    def test_web_server_uses_threaded_handlers_for_stream_and_cancel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with RunningServer(WebServerConfig(state_dir=tmp, port=0)) as server:
                self.assertTrue(getattr(server.server, "daemon_threads", False))

    def test_web_chat_streams_chat_events_and_preserves_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with RunningServer(WebServerConfig(state_dir=tmp, port=0)) as server:
                status, _, body = server.request(
                    "POST",
                    "/api/chat",
                    {"message": "remember: web continuity"},
                )

                self.assertEqual(status, 200)
                events = [json.loads(line) for line in body.splitlines() if line.strip()]
                event_types = [event["type"] for event in events]
                self.assertIn("assistant.delta", event_types)
                self.assertIn("action.completed", event_types)
                self.assertEqual(events[-1]["type"], "run.completed")

                result = events[-1]["data"]["result"]
                status, _, followup = server.request(
                    "POST",
                    "/api/chat",
                    {
                        "message": "search: web continuity",
                        "conversation_id": result["conversation_id"],
                    },
                )

                self.assertEqual(status, 200)
                followup_events = [json.loads(line) for line in followup.splitlines() if line.strip()]
                followup_result = followup_events[-1]["data"]["result"]
                self.assertEqual(result["conversation_id"], followup_result["conversation_id"])
                self.assertEqual(result["mission_id"], followup_result["mission_id"])

    def test_web_chat_passes_workspace_bootstrap_to_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_dir = root / "state"
            workspace = root / "workspace"
            state_dir.mkdir()
            workspace.mkdir()
            (state_dir / "SOUL.md").write_text("User prefers web continuity.", encoding="utf-8")
            (workspace / "AGENTS.md").write_text("Workspace bootstrap from web config.", encoding="utf-8")

            with RunningServer(WebServerConfig(state_dir=str(state_dir), port=0, workspace_root=str(workspace))) as server:
                status, _, body = server.request("POST", "/api/chat", {"message": "remember: web bootstrap"})

            self.assertEqual(status, 200)
            events = [json.loads(line) for line in body.splitlines() if line.strip()]
            run_id = events[-1]["run_id"]
            store = StateStore(str(state_dir))
            prompt_event = next(
                event for event in store.get_run_events(run_id) if event["event_type"] == "prompt.assembled"
            )
            blocks = {block["id"]: block for block in prompt_event["payload"]["blocks"]}

            self.assertIn("soul.user_contract", blocks)
            self.assertIn("workspace.bootstrap.agents_md", blocks)
            self.assertEqual(blocks["workspace.bootstrap.agents_md"]["metadata"]["path"], "AGENTS.md")
            self.assertNotIn("Workspace bootstrap from web config.", str(prompt_event["payload"]))

    def test_web_serves_assets_and_event_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with RunningServer(WebServerConfig(state_dir=tmp, port=0)) as server:
                status, headers, body = server.request("GET", "/")
                self.assertEqual(status, 200)
                self.assertIn("text/html", headers["content-type"])
                self.assertIn("Mnemo", body)

                status, _, run_body = server.request("POST", "/api/chat", {"message": "remember: replay over web"})
                self.assertEqual(status, 200)
                run_id = json.loads(run_body.splitlines()[-1])["run_id"]

                status, _, replay_body = server.request("GET", f"/api/events?run_id={run_id}&chat=1")
                self.assertEqual(status, 200)
                replay_events = json.loads(replay_body)["events"]
                self.assertEqual(replay_events[0]["type"], "turn.started")

                since_event_id = replay_events[0]["event_id"]
                status, _, resumed_body = server.request(
                    "GET",
                    f"/api/events?run_id={run_id}&chat=1&sinceEventId={since_event_id}",
                )
                self.assertEqual(status, 200)
                resumed_payload = json.loads(resumed_body)
                self.assertEqual(resumed_payload["events"][0]["event_id"], replay_events[1]["event_id"])
                self.assertEqual(resumed_payload["last_event_id"], replay_events[-1]["event_id"])

                status, _, unknown_body = server.request(
                    "GET",
                    f"/api/events?run_id={run_id}&chat=1&sinceEventId=evt_missing",
                )
                self.assertEqual(status, 200)
                unknown_events = json.loads(unknown_body)["events"]
                self.assertEqual(unknown_events[0]["event_id"], replay_events[0]["event_id"])

    def test_core_http_api_exposes_schema_openapi_and_sdk_methods(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            page_id = store.upsert_memory_page(
                "preferences: http api",
                "HTTP API results should stay compact. FULL_PRIVATE_BODY_SECRET_TOKEN",
                confidence=0.9,
            )
            script = Path(tmp) / "adapter.py"
            script.write_text(
                """
import json
import sys

payload = json.loads(sys.stdin.read())
print(json.dumps({
    "summary": "http adapter " + payload["capsule"]["capsule_id"],
    "memory_writes": [{"claim": "must not persist"}]
}))
""".strip(),
                encoding="utf-8",
            )

            with RunningServer(WebServerConfig(state_dir=tmp, port=0)) as server:
                schema_status, _, schema_body = server.request("GET", "/api/core/schema")
                openapi_status, _, openapi_body = server.request("GET", "/api/core/openapi.json")
                context_status, _, context_body = server.request(
                    "POST",
                    "/api/core/context",
                    {"intent": "HTTP API", "agent_role": "integrator", "prompt_mode": "minimal"},
                )
                capsule_status, _, capsule_body = server.request(
                    "POST",
                    "/api/core/capsule",
                    {
                        "task": "HTTP capsule",
                        "runtime": "codex",
                        "requested_pages": [page_id],
                        "allowed_pages": [page_id],
                    },
                )
                external_status, _, external_body = server.request(
                    "POST",
                    "/api/core/external-run",
                    {
                        "task": "HTTP external runtime",
                        "command": [sys.executable, str(script)],
                        "timeout_s": 5.0,
                    },
                )
                run_status, _, run_body = server.request(
                    "POST",
                    "/api/core/run",
                    {"message": "remember: HTTP core API should reuse SDK"},
                )
                dream_status, _, dream_body = server.request(
                    "POST",
                    "/api/core/schedule-dream",
                    {"schedule": "once", "next_run_at": 0, "limit": 11, "min_confidence": 0.83},
                )
                watch_status, _, watch_body = server.request(
                    "POST",
                    "/api/core/schedule-watch",
                    {
                        "target": "Calendar",
                        "instruction": "Check calendar risk",
                        "schedule": "hourly",
                        "next_run_at": 0,
                    },
                )
                cron_status, _, cron_body = server.request(
                    "POST",
                    "/api/core/schedule-cron",
                    {
                        "message": "remember: HTTP scheduled task",
                        "title": "HTTP scheduled task",
                        "schedule": "once",
                        "next_run_at": 0,
                    },
                )
                runtime_status, _, runtime_body = server.request(
                    "POST",
                    "/api/core/runtime-status",
                    {"limit": 5},
                )

            schema = json.loads(schema_body)["api_schema"]
            openapi = json.loads(openapi_body)
            context = json.loads(context_body)
            capsule = json.loads(capsule_body)
            external = json.loads(external_body)
            run = json.loads(run_body)
            dream = json.loads(dream_body)
            watch = json.loads(watch_body)
            cron = json.loads(cron_body)
            runtime = json.loads(runtime_body)

            self.assertEqual(schema_status, 200)
            self.assertEqual(schema["schema_version"], "mnemo.core_api.v1")
            self.assertEqual(openapi_status, 200)
            self.assertEqual(openapi["openapi"], "3.1.0")
            self.assertIn("/api/core/external-run", openapi["paths"])
            self.assertIn("/api/core/schedule-dream", openapi["paths"])
            self.assertIn("/api/core/schedule-watch", openapi["paths"])
            self.assertIn("/api/core/schedule-cron", openapi["paths"])
            self.assertIn("/api/core/runtime-status", openapi["paths"])
            self.assertEqual(context_status, 200)
            self.assertEqual(context["method"], "context")
            self.assertEqual(context["result"]["kind"], "context_block")
            self.assertEqual(capsule_status, 200)
            self.assertEqual(capsule["result"]["kind"], "context_capsule")
            self.assertNotIn("FULL_PRIVATE_BODY_SECRET_TOKEN", json.dumps(capsule))
            self.assertEqual(external_status, 200)
            self.assertEqual(external["method"], "external_run")
            self.assertIn("http adapter capsule_", external["result"]["proposal"]["summary"])
            self.assertIn("memory_writes", external["result"]["ignored_fields"])
            self.assertEqual(run_status, 200)
            self.assertTrue(run["result"]["run_id"].startswith("run_"))
            self.assertEqual(dream_status, 200)
            self.assertEqual(dream["method"], "schedule_dream")
            self.assertEqual(dream["result"]["item"]["kind"], "dream")
            self.assertEqual(dream["result"]["item"]["source"], "http")
            self.assertEqual(dream["result"]["item"]["metadata"]["dream"]["limit"], 11)
            self.assertNotIn("dream_report", dream_body)
            self.assertEqual(watch_status, 200)
            self.assertEqual(watch["method"], "schedule_watch")
            self.assertEqual(watch["result"]["item"]["kind"], "watch")
            self.assertEqual(watch["result"]["item"]["title"], "Calendar")
            self.assertEqual(watch["result"]["item"]["source"], "http")
            self.assertEqual(cron_status, 200)
            self.assertEqual(cron["method"], "schedule_cron")
            self.assertEqual(cron["result"]["item"]["kind"], "cron")
            self.assertEqual(cron["result"]["item"]["title"], "HTTP scheduled task")
            self.assertEqual(cron["result"]["item"]["source"], "http")
            self.assertEqual(runtime_status, 200)
            self.assertEqual(runtime["method"], "runtime_status")
            self.assertEqual(runtime["result"]["kind"], "runtime_status")
            self.assertEqual(runtime["result"]["scheduled"]["counts"]["dream"]["active"], 1)
            self.assertEqual(runtime["result"]["scheduled"]["counts"]["watch"]["active"], 1)
            self.assertEqual(runtime["result"]["scheduled"]["counts"]["cron"]["active"], 1)
            self.assertNotIn("output_text", runtime_body)

    def test_core_http_api_normalizes_request_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with RunningServer(WebServerConfig(state_dir=tmp, port=0)) as server:
                missing_status, _, missing_body = server.request("POST", "/api/core/recall", {})
                unknown_status, _, unknown_body = server.request("POST", "/api/core/not-a-method", {})
                bad_schedule_status, _, bad_schedule_body = server.request(
                    "POST",
                    "/api/core/schedule-dream",
                    {"next_run_at": {"bad": True}},
                )
                bad_runtime_status, _, bad_runtime_body = server.request(
                    "POST",
                    "/api/core/runtime-status",
                    {"limit": "many"},
                )
                bad_watch_status, _, bad_watch_body = server.request(
                    "POST",
                    "/api/core/schedule-watch",
                    {"instruction": "Missing target"},
                )
                bad_cron_status, _, bad_cron_body = server.request(
                    "POST",
                    "/api/core/schedule-cron",
                    {"message": "bad schedule", "next_run_at": {"bad": True}},
                )

                host, port = server.server.server_address
                conn = http.client.HTTPConnection(host, port, timeout=5)
                conn.request(
                    "POST",
                    "/api/core/context",
                    body="{not json",
                    headers={"Content-Type": "application/json"},
                )
                invalid_response = conn.getresponse()
                invalid_body = invalid_response.read().decode("utf-8")
                conn.close()

            self.assertEqual(missing_status, 400)
            self.assertEqual(json.loads(missing_body)["error"], "seed is required")
            self.assertEqual(unknown_status, 404)
            self.assertIn("unknown core API method", json.loads(unknown_body)["error"])
            self.assertEqual(bad_schedule_status, 400)
            self.assertIn("next_run_at must be a string, number, or null", json.loads(bad_schedule_body)["error"])
            self.assertEqual(bad_runtime_status, 400)
            self.assertIn("limit must be an integer", json.loads(bad_runtime_body)["error"])
            self.assertEqual(bad_watch_status, 400)
            self.assertIn("target is required", json.loads(bad_watch_body)["error"])
            self.assertEqual(bad_cron_status, 400)
            self.assertIn("next_run_at must be a string, number, or null", json.loads(bad_cron_body)["error"])
            self.assertEqual(invalid_response.status, 400)
            self.assertEqual(json.loads(invalid_body)["error"], "request body must be JSON")

    def test_web_client_asset_persists_last_event_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with RunningServer(WebServerConfig(state_dir=tmp, port=0)) as server:
                status, _, body = server.request("GET", "/app.js")

                self.assertEqual(status, 200)
                self.assertIn("mnemo.last_event_id", body)
                self.assertIn("sinceEventId", body)
                self.assertIn("renderedEventIds", body)

    def test_web_client_asset_guards_untrusted_event_shapes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with RunningServer(WebServerConfig(state_dir=tmp, port=0)) as server:
                status, _, body = server.request("GET", "/app.js")

                self.assertEqual(status, 200)
                self.assertIn('if (!event || typeof event !== "object" || Array.isArray(event)) return;', body)
                self.assertIn("event.data?.artifact", body)
                self.assertIn("event.data?.decision", body)
                self.assertIn("event.data?.item", body)
                self.assertIn("event.data?.recall", body)

    def test_web_artifact_api_returns_stored_artifact_on_demand(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with RunningServer(WebServerConfig(state_dir=tmp, port=0)) as server:
                status, _, run_body = server.request("POST", "/api/chat", {"message": "artifact: Launch secret body"})

                self.assertEqual(status, 200)
                events = [json.loads(line) for line in run_body.splitlines() if line.strip()]
                artifact_event = next(event for event in events if event["type"] == "artifact.card")
                artifact_card = artifact_event["data"]["artifact"]
                artifact_id = artifact_card["artifact_id"]
                self.assertEqual(artifact_card["title"], "Draft Artifact")
                self.assertEqual(artifact_card["kind"], "markdown")
                self.assertNotIn("Launch secret body", json.dumps(artifact_event))

                store = StateStore(tmp)
                related_id = store.upsert_artifact(
                    artifact_event["mission_id"],
                    artifact_event["run_id"],
                    "Related Draft",
                    "Related body should stay out of related metadata",
                    "markdown",
                )

                status, _, artifact_body = server.request("GET", f"/api/artifacts?artifact_id={artifact_id}")
                self.assertEqual(status, 200)
                artifact_payload = json.loads(artifact_body)
                artifact = artifact_payload["artifact"]
                self.assertEqual(artifact["id"], artifact_id)
                self.assertEqual(artifact["mission_id"], artifact_event["mission_id"])
                self.assertEqual(artifact["run_id"], artifact_event["run_id"])
                self.assertEqual(artifact["title"], "Draft Artifact")
                self.assertEqual(artifact["kind"], "markdown")
                self.assertEqual(artifact["body"], "Launch secret body")
                self.assertIn("created_at", artifact)
                self.assertIn("updated_at", artifact)
                self.assertEqual([item["id"] for item in artifact_payload["related"]], [related_id])
                self.assertNotIn("Related body should stay out", json.dumps(artifact_payload["related"]))

                status, _, missing_body = server.request("GET", "/api/artifacts")
                self.assertEqual(status, 400)
                self.assertEqual(json.loads(missing_body)["error"], "artifact_id is required")

                status, _, unknown_body = server.request("GET", "/api/artifacts?artifact_id=art_missing")
                self.assertEqual(status, 404)
                self.assertEqual(json.loads(unknown_body)["error"], "artifact not found")

    def test_web_decision_card_is_persisted_and_resolvable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with RunningServer(WebServerConfig(state_dir=tmp, port=0)) as server:
                status, _, run_body = server.request("POST", "/api/chat", {"message": "ask: Send external update?"})

                self.assertEqual(status, 200)
                events = [json.loads(line) for line in run_body.splitlines() if line.strip()]
                decision_event = next(event for event in events if event["type"] == "decision.card")
                decision = decision_event["data"]["decision"]
                self.assertEqual(decision["question"], "Send external update?")
                self.assertTrue(decision["item_id"].startswith("inbox_"))

                status, _, list_body = server.request("GET", "/api/inbox?status=open&priority=high")
                self.assertEqual(status, 200)
                listed = json.loads(list_body)["items"]
                self.assertEqual([item["id"] for item in listed], [decision["item_id"]])
                self.assertNotIn("action_data_json", list_body)

                status, _, resolve_body = server.request(
                    "POST",
                    "/api/inbox/resolve",
                    {"item_id": decision["item_id"], "resolution": "accepted", "notes": "ok"},
                )
                self.assertEqual(status, 200)
                resolved = json.loads(resolve_body)["item"]
                self.assertTrue(resolved["changed"])
                self.assertEqual(resolved["status"], "resolved")
                self.assertEqual(resolved["resolution"], "accepted")

                missing_status, _, missing_body = server.request(
                    "POST",
                    "/api/inbox/resolve",
                    {"item_id": "inbox_missing", "resolution": "accepted"},
                )
                invalid_status, _, invalid_body = server.request(
                    "POST",
                    "/api/inbox/resolve",
                    {"item_id": decision["item_id"], "resolution": "maybe"},
                )
                self.assertEqual(missing_status, 404)
                self.assertIn("not found", json.loads(missing_body)["error"])
                self.assertEqual(invalid_status, 400)
                self.assertIn("invalid inbox resolution", json.loads(invalid_body)["error"])

    def test_web_resolves_tool_approval_decision_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("tool approval")
            mission_id = store.create_mission(conversation_id, "tool approval")
            run_id = store.create_run(conversation_id, mission_id, "open external app")
            item_id = store.add_inbox_item(
                category="decision",
                title="Approve browser_open?",
                priority=1,
                body="tool risk is not allowed: external",
                action_type="tool_approval",
                action_data={
                    "source": "tool_policy",
                    "tool_call": {
                        "call_id": "call_browser",
                        "provider": "fake",
                        "tool_name": "browser_open",
                        "risk": "external",
                        "arguments": {"url": "https://example.com", "dry_run": True},
                    },
                },
                source_run_id=run_id,
            )

            with RunningServer(WebServerConfig(state_dir=tmp, port=0)) as server:
                status, _, list_body = server.request("GET", "/api/inbox?status=open&priority=high")
                resolve_status, _, resolve_body = server.request(
                    "POST",
                    "/api/inbox/resolve",
                    {"item_id": item_id, "resolution": "accepted"},
                )
                repeat_status, _, repeat_body = server.request(
                    "POST",
                    "/api/inbox/resolve",
                    {"item_id": item_id, "resolution": "accepted"},
                )

            listed = json.loads(list_body)["items"][0]
            resolved_payload = json.loads(resolve_body)
            repeated_payload = json.loads(repeat_body)
            resolved = resolved_payload["item"]
            run_event_types = [event["event_type"] for event in store.get_run_events(run_id)]
            self.assertEqual(status, 200)
            self.assertEqual(resolve_status, 200)
            self.assertEqual(repeat_status, 200)
            self.assertEqual(listed["action_type"], "tool_approval")
            self.assertEqual(listed["action_data"]["tool_call"]["tool_name"], "browser_open")
            self.assertEqual(resolved["resolution"], "accepted")
            self.assertEqual(resolved_payload["tool_result"]["tool"], "browser_open")
            self.assertTrue(resolved_payload["tool_result"]["ok"])
            self.assertIn("Browser prepared", resolved_payload["tool_result"]["summary"])
            self.assertFalse(repeated_payload["item"]["changed"])
            self.assertNotIn("tool_result", repeated_payload)
            self.assertIn("tool.approval.executing", run_event_types)
            self.assertIn("tool.approval.executed", run_event_types)
            self.assertIn("tool.called", run_event_types)
            self.assertIn("tool.result", run_event_types)
            self.assertEqual(run_event_types.count("tool.approval.executed"), 1)

    def test_web_rejecting_tool_approval_does_not_execute_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("tool approval reject")
            mission_id = store.create_mission(conversation_id, "tool approval reject")
            run_id = store.create_run(conversation_id, mission_id, "open external app")
            item_id = store.add_inbox_item(
                category="decision",
                title="Approve browser_open?",
                priority=1,
                action_type="tool_approval",
                action_data={
                    "source": "tool_policy",
                    "tool_call": {
                        "call_id": "call_browser",
                        "provider": "fake",
                        "tool_name": "browser_open",
                        "risk": "external",
                        "arguments": {"url": "https://example.com", "dry_run": True},
                    },
                },
                source_run_id=run_id,
            )

            with RunningServer(WebServerConfig(state_dir=tmp, port=0)) as server:
                status, _, body = server.request(
                    "POST",
                    "/api/inbox/resolve",
                    {"item_id": item_id, "resolution": "rejected"},
                )

            payload = json.loads(body)
            run_event_types = [event["event_type"] for event in store.get_run_events(run_id)]
            self.assertEqual(status, 200)
            self.assertEqual(payload["item"]["resolution"], "rejected")
            self.assertNotIn("tool_result", payload)
            self.assertNotIn("tool.approval.executed", run_event_types)

    def test_web_recall_card_streams_compact_actionable_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("web recall")
            mission_id = store.create_mission(conversation_id, "web recall")
            run_id = store.create_run(conversation_id, mission_id, "Zephyr web recall")
            store.complete_run(run_id, "Zephyr web recall response")
            store.upsert_memory_page("knowledge: zephyr", "Zephyr web recall prefers concise cards", confidence=0.9)
            store.upsert_artifact(
                mission_id,
                run_id,
                "Zephyr web artifact",
                "Zephyr artifact body " + ("hidden detail " * 40) + "sensitive tail",
            )
            store.add_inbox_item(category="decision", title="Approve Zephyr web recall", source_run_id=run_id)

            with RunningServer(WebServerConfig(state_dir=tmp, port=0)) as server:
                status, _, run_body = server.request(
                    "POST",
                    "/api/chat",
                    {"message": "recall: Zephyr", "conversation_id": conversation_id},
                )

            self.assertEqual(status, 200)
            events = [json.loads(line) for line in run_body.splitlines() if line.strip()]
            recall_event = next(event for event in events if event["type"] == "recall.card")
            recall = recall_event["data"]["recall"]
            self.assertEqual(recall["query"], "Zephyr")
            self.assertGreaterEqual(recall["count"], 4)
            self.assertIn("artifact", {item["kind"] for item in recall["items"]})
            self.assertIn("decision", {item["kind"] for item in recall["items"]})
            self.assertNotIn("sensitive tail", json.dumps(recall_event))

    def test_web_learning_memory_actions_resolve_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("web learning")
            mission_id = store.create_mission(conversation_id, "web learning")
            run_id = store.create_run(conversation_id, mission_id, "learn from chip")
            accept_id = store.add_memory_candidate(
                run_id,
                "User prefers inline learning chip actions",
                dimension="preferences",
                confidence=0.84,
            )
            this_time_id = store.add_memory_candidate(run_id, "Temporary web-only learning")
            reject_id = store.add_memory_candidate(run_id, "Wrong web learning")

            with RunningServer(WebServerConfig(state_dir=tmp, port=0)) as server:
                status, _, body = server.request(
                    "POST",
                    "/api/learning/memory",
                    {"candidate_id": accept_id, "action": "accept"},
                )
                undo_status, _, undo_body = server.request(
                    "POST",
                    "/api/learning/memory",
                    {"candidate_id": accept_id, "action": "undo"},
                )
                this_time_status, _, this_time_body = server.request(
                    "POST",
                    "/api/learning/memory",
                    {"candidate_id": this_time_id, "action": "this_time"},
                )
                reject_status, _, reject_body = server.request(
                    "POST",
                    "/api/learning/memory",
                    {"candidate_id": reject_id, "action": "reject"},
                )
                missing_status, _, missing_body = server.request(
                    "POST",
                    "/api/learning/memory",
                    {"candidate_id": "mem_missing", "action": "accept"},
                )
                invalid_status, _, invalid_body = server.request(
                    "POST",
                    "/api/learning/memory",
                    {"candidate_id": reject_id, "action": "maybe"},
                )

            payload = json.loads(body)
            self.assertEqual(status, 200)
            self.assertEqual(payload["action"], "accept")
            self.assertEqual(payload["candidate"]["id"], accept_id)
            self.assertEqual(payload["candidate"]["status"], "promoted")
            self.assertTrue(payload["page_id"].startswith("mempg_"))
            page = store.get_memory_page(payload["page_id"])
            self.assertEqual(page["content"], "User prefers inline learning chip actions")

            undo_payload = json.loads(undo_body)
            self.assertEqual(undo_status, 200)
            self.assertEqual(undo_payload["action"], "undo")
            self.assertEqual(undo_payload["candidate"]["status"], "tombstoned:user_undo")
            self.assertEqual(undo_payload["page_id"], payload["page_id"])
            self.assertEqual(store.get_memory_page(payload["page_id"])["status"], "tombstoned:user_undo")

            this_time_payload = json.loads(this_time_body)
            reject_payload = json.loads(reject_body)
            self.assertEqual(this_time_status, 200)
            self.assertEqual(this_time_payload["candidate"]["status"], "rejected:this_time_only")
            self.assertIsNone(this_time_payload["page_id"])
            self.assertEqual(reject_status, 200)
            self.assertEqual(reject_payload["candidate"]["status"], "rejected:user_rejected")
            self.assertIsNone(reject_payload["page_id"])

            self.assertEqual(missing_status, 404)
            self.assertIn("memory candidate not found", json.loads(missing_body)["error"])
            self.assertEqual(invalid_status, 400)
            self.assertIn("invalid learning action", json.loads(invalid_body)["error"])

            event = store.get_run_events(run_id)[-1]
            self.assertEqual(event["event_type"], "learning.memory_action")
            self.assertEqual(event["payload"]["candidate_id"], reject_id)
            self.assertEqual(event["payload"]["action"], "reject")
            actions = [
                event["payload"]["action"]
                for event in store.get_run_events(run_id)
                if event["event_type"] == "learning.memory_action"
            ]
            self.assertIn("undo", actions)

    def test_web_settings_api_returns_summary_and_updates_quiet_hours(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("web settings")
            mission_id = store.create_mission(conversation_id, "web settings")
            run_id = store.create_run(conversation_id, mission_id, "settings summary")
            store.upsert_memory_page(
                "preferences: reports",
                "User prefers concise report summaries.",
                confidence=0.88,
            )
            store.add_memory_candidate(run_id, "User may prefer settings drawers", dimension="preferences")
            store.upsert_artifact(mission_id, run_id, "Settings artifact", "Hidden artifact body")
            store.add_inbox_item(category="decision", title="Approve settings action?", priority=1, source_run_id=run_id)

            workspace = Path(tmp) / "workspace"
            with RunningServer(
                WebServerConfig(
                    state_dir=tmp,
                    port=0,
                    workspace_root=str(workspace),
                    provider="openai-compatible",
                    model="settings-model",
                    api_key="secret-settings-key",
                )
            ) as server:
                status, _, body = server.request("GET", "/api/settings")
                update_status, _, update_body = server.request(
                    "POST",
                    "/api/settings",
                    {"quiet_hours": {"enabled": True, "start": "21:30", "end": "07:15"}},
                )
                invalid_status, _, invalid_body = server.request(
                    "POST",
                    "/api/settings",
                    {"quiet_hours": {"enabled": True, "start": "99:00", "end": "07:15"}},
                )

            payload = json.loads(body)
            updated = json.loads(update_body)
            self.assertEqual(status, 200)
            self.assertNotIn("secret-settings-key", body)
            self.assertNotIn("Hidden artifact body", body)
            self.assertEqual(payload["connected_apps"][0]["detail"], "openai-compatible · settings-model")
            self.assertEqual(payload["permissions"]["open_decisions"], 1)
            self.assertEqual(payload["learned_preferences"]["count"], 1)
            self.assertEqual(payload["data_controls"]["counts"]["artifacts"], 1)
            self.assertEqual(payload["data_controls"]["counts"]["memory_candidates"], 1)
            self.assertFalse(payload["quiet_hours"]["enabled"])

            self.assertEqual(update_status, 200)
            self.assertTrue(updated["quiet_hours"]["enabled"])
            self.assertEqual(updated["quiet_hours"]["start"], "21:30")
            self.assertEqual(updated["quiet_hours"]["end"], "07:15")

            self.assertEqual(invalid_status, 400)
            self.assertIn("quiet_hours start", json.loads(invalid_body)["error"])

    def test_web_cancel_run_endpoint_marks_run_and_records_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("web cancel")
            mission_id = store.create_mission(conversation_id, "web cancel")
            run_id = store.create_run(conversation_id, mission_id, "long work")

            with RunningServer(WebServerConfig(state_dir=tmp, port=0)) as server:
                status, _, body = server.request(
                    "POST",
                    "/api/runs/cancel",
                    {"run_id": run_id, "reason": "user stop"},
                )
                repeated_status, _, repeated_body = server.request(
                    "POST",
                    "/api/runs/cancel",
                    {"run_id": run_id},
                )
                missing_status, _, missing_body = server.request("POST", "/api/runs/cancel", {})
                unknown_status, _, unknown_body = server.request(
                    "POST",
                    "/api/runs/cancel",
                    {"run_id": "run_missing"},
                )

            payload = json.loads(body)
            repeated_payload = json.loads(repeated_body)
            self.assertEqual(status, 200)
            self.assertEqual(payload, {"run_id": run_id, "status": "cancelled", "changed": True})
            self.assertEqual(repeated_status, 200)
            self.assertFalse(repeated_payload["changed"])
            self.assertEqual(store.get_run(run_id)["status"], "cancelled")
            event_types = [event["event_type"] for event in store.get_run_events(run_id)]
            self.assertEqual(event_types.count("run.cancel.requested"), 2)
            self.assertEqual(missing_status, 400)
            self.assertEqual(json.loads(missing_body)["error"], "run_id is required")
            self.assertEqual(unknown_status, 404)
            self.assertEqual(json.loads(unknown_body)["error"], "run not found: run_missing")

    def test_web_client_asset_renders_artifact_viewer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with RunningServer(WebServerConfig(state_dir=tmp, port=0)) as server:
                status, _, body = server.request("GET", "/app.js")
                css_status, _, css = server.request("GET", "/app.css")

                self.assertEqual(status, 200)
                self.assertEqual(css_status, 200)
                self.assertIn("/api/artifacts?artifact_id=", body)
                self.assertIn("toggleArtifact", body)
                self.assertIn("loadArtifact", body)
                self.assertIn("exportArtifact", body)
                self.assertIn("toggleArtifactRelated", body)
                self.assertIn("Continue editing artifact", body)
                self.assertIn("Send artifact", body)
                self.assertIn("Apply artifact", body)
                self.assertIn("Revert changes from artifact", body)
                self.assertIn("artifact-body", body)
                self.assertIn("artifact-related", css)
                self.assertIn("artifact-related-row", css)

    def test_web_client_asset_exposes_stop_control(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with RunningServer(WebServerConfig(state_dir=tmp, port=0)) as server:
                status, _, html = server.request("GET", "/")
                script_status, _, script = server.request("GET", "/app.js")

                self.assertEqual(status, 200)
                self.assertEqual(script_status, 200)
                self.assertIn('id="stop"', html)
                self.assertIn("/api/runs/cancel", script)
                self.assertIn("requestCancel", script)
                self.assertIn("cancelRequested", script)
                self.assertIn("activeRunId", script)
                self.assertIn("run_id: state.activeRunId", script)
                self.assertIn("stop.disabled = !state.activeRunId || state.cancelRequested", script)
                self.assertIn("updateComposerState", script)
                self.assertIn("if (state.busy) return;", script)
                self.assertIn("reset.disabled = state.busy", script)

    def test_web_client_asset_uses_polished_single_chat_shell(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with RunningServer(WebServerConfig(state_dir=tmp, port=0)) as server:
                status, _, html = server.request("GET", "/")
                script_status, _, script = server.request("GET", "/app.js")
                css_status, _, css = server.request("GET", "/app.css")

                self.assertEqual(status, 200)
                self.assertEqual(script_status, 200)
                self.assertEqual(css_status, 200)
                self.assertIn('class="app-shell"', html)
                self.assertIn('class="rail"', html)
                self.assertIn('id="activityPanel"', html)
                self.assertIn('class="composer-tools"', html)
                self.assertIn('id="attachButton"', html)
                self.assertIn('id="voiceButton"', html)
                self.assertIn('id="mentionButton"', html)
                self.assertIn("renderActivity", script)
                self.assertIn("pushActivity", script)
                self.assertIn("activity-collapsed", script)
                self.assertIn("runBadge.textContent", script)
                self.assertIn("activity-panel", css)
                self.assertIn("composer-tools", css)
                self.assertIn("app-shell", css)

    def test_web_client_asset_resolves_decision_cards_inline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with RunningServer(WebServerConfig(state_dir=tmp, port=0)) as server:
                status, _, script = server.request("GET", "/app.js")
                css_status, _, css = server.request("GET", "/app.css")

                self.assertEqual(status, 200)
                self.assertEqual(css_status, 200)
                self.assertIn("decision-actions", script)
                self.assertIn("/api/inbox/resolve", script)
                self.assertIn("resolveDecision", script)
                self.assertIn("item_id: itemId", script)
                self.assertIn("payload.tool_result", script)
                self.assertIn("decision-button", css)
                self.assertIn("event-card.decision", css)

    def test_web_client_asset_resolves_learning_chips_inline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with RunningServer(WebServerConfig(state_dir=tmp, port=0)) as server:
                status, _, script = server.request("GET", "/app.js")
                css_status, _, css = server.request("GET", "/app.css")

                self.assertEqual(status, 200)
                self.assertEqual(css_status, 200)
                self.assertIn("learning-actions", script)
                self.assertIn("/api/learning/memory", script)
                self.assertIn("resolveLearningMemory", script)
                self.assertIn("candidate_id: itemId", script)
                self.assertIn("以后这样", script)
                self.assertIn("这次而已", script)
                self.assertIn("撤销", script)
                self.assertIn("确认记住", script)
                self.assertIn("requires_confirmation", script)
                self.assertIn('action === "undo"', script)
                self.assertIn("learning-button", css)
                self.assertIn("event-card.learning", css)
                self.assertIn("event-card.learning.confirmation", css)

    def test_web_client_asset_renders_recall_cards_inline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with RunningServer(WebServerConfig(state_dir=tmp, port=0)) as server:
                status, _, script = server.request("GET", "/app.js")
                css_status, _, css = server.request("GET", "/app.css")

                self.assertEqual(status, 200)
                self.assertEqual(css_status, 200)
                self.assertIn("recall.card", script)
                self.assertIn("renderRecall", script)
                self.assertIn("recall-actions", script)
                self.assertIn("prefillMessage", script)
                self.assertIn("toggleArtifact(item.artifact_id", script)
                self.assertIn("decisionButton(\"Approve\"", script)
                self.assertIn("event-card.recall", css)
                self.assertIn("recall-button", css)

    def test_web_client_asset_renders_settings_drawer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with RunningServer(WebServerConfig(state_dir=tmp, port=0)) as server:
                status, _, html = server.request("GET", "/")
                script_status, _, script = server.request("GET", "/app.js")
                css_status, _, css = server.request("GET", "/app.css")

                self.assertEqual(status, 200)
                self.assertEqual(script_status, 200)
                self.assertEqual(css_status, 200)
                self.assertIn('id="settingsOpen"', html)
                self.assertIn('id="settingsOverlay"', html)
                self.assertIn("/api/settings", script)
                self.assertIn("renderSettings", script)
                self.assertIn("settingsQuietHoursSection", script)
                self.assertIn("prefillMessage(item.prompt", script)
                self.assertIn("settings-drawer", css)
                self.assertIn("settings-action", css)


class RunningServer:
    def __init__(self, config: WebServerConfig) -> None:
        self.server = build_http_server(config)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> RunningServer:
        self.thread.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=1)

    def request(self, method: str, path: str, payload: dict | None = None) -> tuple[int, dict[str, str], str]:
        host, port = self.server.server_address
        conn = http.client.HTTPConnection(host, port, timeout=5)
        body = json.dumps(payload) if payload is not None else None
        headers = {"Content-Type": "application/json"} if body else {}
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        raw_body = response.read().decode("utf-8")
        response_headers = {key.casefold(): value for key, value in response.getheaders()}
        conn.close()
        return response.status, response_headers, raw_body


if __name__ == "__main__":
    unittest.main()
