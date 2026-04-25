from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest

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

    def test_web_client_asset_persists_last_event_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with RunningServer(WebServerConfig(state_dir=tmp, port=0)) as server:
                status, _, body = server.request("GET", "/app.js")

                self.assertEqual(status, 200)
                self.assertIn("mnemo.last_event_id", body)
                self.assertIn("sinceEventId", body)
                self.assertIn("renderedEventIds", body)

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

                status, _, artifact_body = server.request("GET", f"/api/artifacts?artifact_id={artifact_id}")
                self.assertEqual(status, 200)
                artifact = json.loads(artifact_body)["artifact"]
                self.assertEqual(artifact["id"], artifact_id)
                self.assertEqual(artifact["mission_id"], artifact_event["mission_id"])
                self.assertEqual(artifact["run_id"], artifact_event["run_id"])
                self.assertEqual(artifact["title"], "Draft Artifact")
                self.assertEqual(artifact["kind"], "markdown")
                self.assertEqual(artifact["body"], "Launch secret body")
                self.assertIn("created_at", artifact)
                self.assertIn("updated_at", artifact)

                status, _, missing_body = server.request("GET", "/api/artifacts")
                self.assertEqual(status, 400)
                self.assertEqual(json.loads(missing_body)["error"], "artifact_id is required")

                status, _, unknown_body = server.request("GET", "/api/artifacts?artifact_id=art_missing")
                self.assertEqual(status, 404)
                self.assertEqual(json.loads(unknown_body)["error"], "artifact not found")

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

                self.assertEqual(status, 200)
                self.assertIn("/api/artifacts?artifact_id=", body)
                self.assertIn("toggleArtifact", body)
                self.assertIn("artifact-body", body)

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
                self.assertIn("updateComposerState", script)


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
