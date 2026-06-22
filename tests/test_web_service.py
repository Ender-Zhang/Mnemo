from __future__ import annotations

from http import HTTPStatus
import json
import os
from pathlib import Path
import re
from threading import Thread
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class MemoryWebServiceTests(unittest.TestCase):
    def test_webui_static_routes_and_api_are_public(self) -> None:
        from mnemo_memory.interfaces.web import MemoryWebConfig, build_http_server

        with tempfile.TemporaryDirectory() as tmp:
            server = build_http_server(
                MemoryWebConfig(state_dir=tmp, host="127.0.0.1", port=0, auth_token="ignored-token")
            )
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://{server.server_address[0]}:{server.server_address[1]}"

                index = _get(base + "/")
                self.assertEqual(index.status, HTTPStatus.OK)
                self.assertIn("text/html", index.content_type)
                self.assertIn("Mnemo Memory", index.body)

                fallback = _get(base + "/settings")
                self.assertEqual(fallback.status, HTTPStatus.OK)
                self.assertIn("text/html", fallback.content_type)

                schema = _get(base + "/api/schema")
                self.assertEqual(schema.status, HTTPStatus.OK)
                self.assertIn("application/json", schema.content_type)

                search = _post(base + "/api/memory/search", {"query": "coffee", "limit": 1})
                self.assertEqual(search.status, HTTPStatus.OK)
                self.assertIn("application/json", search.content_type)

                created = _post(
                    base + "/api/memory/stable-create",
                    {
                        "title": "preferences: web stable route",
                        "content": "HTTP routes can create stable memories directly.",
                        "scope": "user:web",
                    },
                )
                self.assertEqual(created.status, HTTPStatus.OK)
                created_payload = json.loads(created.body)
                page_id = created_payload["result"]["memory_id"]

                stable_search = _post(base + "/api/memory/stable-search", {"all": True})
                self.assertEqual(stable_search.status, HTTPStatus.OK)
                stable_payload = json.loads(stable_search.body)
                self.assertEqual(stable_payload["result"]["items"][0]["id"], page_id)

                asset_paths = re.findall(r'/(assets/[^"]+)', index.body)
                self.assertTrue(asset_paths)
                asset = _get(f"{base}/{asset_paths[0]}")
                self.assertEqual(asset.status, HTTPStatus.OK)
                self.assertNotIn("application/json", asset.content_type)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_webui_rejects_static_path_traversal(self) -> None:
        from mnemo_memory.interfaces.web import MemoryWebConfig, build_http_server

        with tempfile.TemporaryDirectory() as tmp:
            server = build_http_server(MemoryWebConfig(state_dir=tmp, host="127.0.0.1", port=0))
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://{server.server_address[0]}:{server.server_address[1]}"

                with self.assertRaises(HTTPError) as not_found:
                    _get(base + "/assets/%2e%2e/web.py")
                self.assertEqual(not_found.exception.code, HTTPStatus.NOT_FOUND)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_insecure_bind_warning_only_for_non_loopback(self) -> None:
        from mnemo_memory.interfaces.web import insecure_bind_warning

        self.assertIsNone(insecure_bind_warning("127.0.0.1"))
        self.assertIsNone(insecure_bind_warning("localhost"))
        self.assertIsNone(insecure_bind_warning("::1"))
        for host in ("0.0.0.0", "192.168.1.5", ""):
            message = insecure_bind_warning(host)
            self.assertIsNotNone(message)
            self.assertIn("UNAUTHENTICATED", message)
            self.assertIn("state-dir", message)

    def test_auto_dream_scheduler_skips_backlog_without_provider(self) -> None:
        from mnemo_memory import MemoryClient
        from mnemo_memory.interfaces.auto_dream import AutoDreamScheduler

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"MNEMO_MEMORY_ENV_FILE": str(Path(tmp) / "missing.env")}, clear=True):
                client = MemoryClient(state_dir=tmp)
                client.update(
                    facts=[
                        {
                            "claim": "User wants automatic Dream maintenance to require a configured provider.",
                            "dimension": "preferences",
                            "confidence": 0.9,
                        }
                    ],
                    source="unit-test",
                )
                scheduler = AutoDreamScheduler(tmp, startup_delay_s=0)

                status = scheduler.tick_once(now=1000, force=True)

                self.assertEqual(status["last_outcome"], "provider_required")
                self.assertEqual(status["last_backlog"]["memory_candidates"], 1)
                self.assertEqual(client.list(kind="page", status="active", limit=10)["items"], [])

    def test_auto_dream_scheduler_counts_pending_goal_proposals_as_backlog(self) -> None:
        from mnemo_memory import MemoryClient
        from mnemo_memory.interfaces.auto_dream import AutoDreamScheduler

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"MNEMO_MEMORY_ENV_FILE": str(Path(tmp) / "missing.env")}, clear=True):
                client = MemoryClient(state_dir=tmp)
                client.ingest_event(
                    text="我计划下周完成自动 Dream 目标维护测试。",
                    source="unit-test",
                    actor="user",
                    scope="user:auto",
                )
                scheduler = AutoDreamScheduler(tmp, startup_delay_s=0)

                status = scheduler.tick_once(now=1000, force=True)

                self.assertEqual(status["last_outcome"], "provider_required")
                self.assertEqual(status["last_backlog"]["pending_plan_proposals"], 1)

    def test_auto_dream_scheduler_runs_local_fallback_without_provider(self) -> None:
        from mnemo_memory import MemoryClient
        from mnemo_memory.interfaces.auto_dream import AutoDreamScheduler

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"MNEMO_MEMORY_ENV_FILE": str(Path(tmp) / "missing.env")}, clear=True):
                client = MemoryClient(state_dir=tmp)
                client.save_auto_dream_config(local_fallback=True)
                client.update(
                    facts=[
                        {
                            "claim": "User prefers concise progress updates with explicit next steps.",
                            "dimension": "preferences",
                            "confidence": 0.9,
                        }
                    ],
                    source="unit-test",
                )
                scheduler = AutoDreamScheduler(tmp, startup_delay_s=0)

                status = scheduler.tick_once(now=1000, force=True)

                self.assertEqual(status["last_outcome"], "ran")
                self.assertEqual(status["last_run_mode"], "local")
                self.assertTrue(status["local_fallback"])
                pages = client.list(kind="page", status="active", limit=10)["items"]
                self.assertTrue(pages, "local fallback should promote the high-confidence candidate")


class HttpResponse:
    def __init__(self, *, status: int, content_type: str, body: str) -> None:
        self.status = status
        self.content_type = content_type
        self.body = body


def _get(url: str) -> HttpResponse:
    request = Request(url)
    with urlopen(request, timeout=5) as response:
        return HttpResponse(
            status=response.status,
            content_type=response.headers.get("Content-Type", ""),
            body=response.read().decode("utf-8", errors="replace"),
        )


def _post(url: str, body: dict[str, object]) -> HttpResponse:
    request = Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=5) as response:
        return HttpResponse(
            status=response.status,
            content_type=response.headers.get("Content-Type", ""),
            body=response.read().decode("utf-8", errors="replace"),
        )


if __name__ == "__main__":
    unittest.main()
