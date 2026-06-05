from __future__ import annotations

import tempfile
from pathlib import Path
import unittest


class MemoryServiceTests(unittest.TestCase):
    def test_client_update_search_and_curate_candidate(self) -> None:
        from mnemo_memory import MemoryClient

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)

            update = client.update(
                facts=[
                    {
                        "claim": "User prefers concise implementation updates.",
                        "dimension": "preferences",
                        "confidence": 0.9,
                    }
                ],
                source="unit-test",
            )

            candidate_id = update["memory_candidates"][0]["candidate_id"]
            self.assertEqual(update["kind"], "memory_update")
            self.assertEqual(update["memory_candidates"][0]["status"], "draft")

            search = client.search("concise implementation", limit=5)
            self.assertEqual(search["kind"], "memory_search")
            self.assertEqual(search["matches"][0]["id"], candidate_id)

            promoted = client.promote_candidate(candidate_id)
            self.assertEqual(promoted["status"], "promoted")

            context = client.context("implementation status", limit=5)
            self.assertEqual(context["kind"], "memory_context")
            self.assertEqual(context["cards"][0]["type"], "memory_page")

    def test_client_lists_candidates_and_pages_for_admin_ui(self) -> None:
        from mnemo_memory import MemoryClient

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)

            update = client.update(
                facts=[
                    {
                        "claim": "User prefers a React WebUI dashboard for local memory curation with explicit candidate review controls.",
                        "dimension": "preferences",
                        "confidence": 0.9,
                    }
                ],
                source="unit-test",
            )
            candidate_id = update["memory_candidates"][0]["candidate_id"]
            promoted = client.promote_candidate(candidate_id)

            candidates = client.list(kind="candidate", status="promoted", limit=10)
            self.assertEqual(candidates["kind"], "memory_list")
            self.assertEqual(candidates["items"][0]["type"], "candidate")
            self.assertEqual(candidates["items"][0]["id"], candidate_id)

            pages = client.list(kind="page", status="active", limit=10)
            self.assertEqual(pages["items"][0]["type"], "page")
            self.assertEqual(pages["items"][0]["id"], promoted["page_id"])

            combined = client.list(kind="all", status=None, limit=10)
            self.assertEqual({item["type"] for item in combined["items"]}, {"candidate", "page"})
            self.assertEqual(combined["count"], 2)

    def test_client_traces_promoted_memory_to_source_event(self) -> None:
        from mnemo_memory import MemoryClient

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)
            update = client.update(
                facts=[
                    {
                        "claim": "User prefers provenance timelines in memory detail panels for debugging agent-written memories.",
                        "dimension": "preferences",
                        "confidence": 0.92,
                        "event_at": 1710000000,
                        "actor": "user",
                        "agent_id": "agent-alpha",
                        "conversation_id": "conv-123",
                        "message_id": "msg-456",
                        "excerpt": "Please show where each memory came from.",
                    }
                ],
                source="unit-test",
                run_id="run-123",
                mission_id="mission-456",
            )
            candidate_id = update["memory_candidates"][0]["candidate_id"]
            promoted = client.promote_candidate(candidate_id)

            provenance = client.provenance(promoted["page_id"])

            self.assertEqual(provenance["kind"], "memory_provenance")
            self.assertEqual(provenance["memory_id"], promoted["page_id"])
            self.assertEqual(provenance["candidates"][0]["id"], candidate_id)
            self.assertEqual(provenance["events"][0]["event_at"], 1710000000.0)
            self.assertEqual(provenance["events"][0]["observed_at"], provenance["candidates"][0]["created_at"])
            self.assertEqual(provenance["events"][0]["source"], "unit-test")
            self.assertEqual(provenance["events"][0]["agent_id"], "agent-alpha")
            self.assertEqual(provenance["events"][0]["run_id"], "run-123")
            self.assertEqual(provenance["events"][0]["mission_id"], "mission-456")
            self.assertEqual(provenance["events"][0]["conversation_id"], "conv-123")
            self.assertEqual(provenance["events"][0]["message_id"], "msg-456")
            self.assertEqual(provenance["events"][0]["actor"], "user")
            self.assertEqual(provenance["events"][0]["excerpt"], "Please show where each memory came from.")
            self.assertTrue(str(provenance["events"][0]["raw_hash"]).startswith("sha256:"))

    def test_ingest_event_keeps_coffee_slot_answer_as_ephemeral_observation(self) -> None:
        from mnemo_memory import MemoryClient

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)

            result = client.ingest_event(
                text="冰美式",
                source="unit-test",
                actor="user",
                mission_id="coffee-order-123",
                conversation_id="conv-coffee",
                message_id="msg-coffee",
                context=[
                    {"role": "user", "content": "帮我买杯咖啡"},
                    {"role": "assistant", "content": "想要哪个咖啡？"},
                ],
            )

            self.assertEqual(result["kind"], "memory_event_ingest")
            self.assertEqual(result["memory_candidates"], [])
            self.assertEqual(result["working_notes"][0]["retention"], "ephemeral")
            note = client._store().list_working_notes(status="open", limit=1)[0]
            self.assertIn("冰美式", note["content"])
            self.assertEqual(note["metadata"]["event_id"], result["event"]["id"])
            self.assertEqual(client.list(kind="candidate", limit=10)["items"], [])

    def test_ingest_event_extracts_explicit_long_term_preference_candidate(self) -> None:
        from mnemo_memory import MemoryClient

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)

            result = client.ingest_event(
                text="我以后默认都喝冰美式。",
                source="unit-test",
                actor="user",
                mission_id="coffee-order-123",
                conversation_id="conv-coffee",
                message_id="msg-coffee-preference",
                scope="user:demo",
                auto_promote=True,
            )

            self.assertEqual(result["working_notes"], [])
            self.assertEqual(result["memory_candidates"][0]["status"], "draft")
            self.assertEqual(result["memory_candidates"][0]["scope"], "user:demo")
            self.assertEqual(result["promotions"][0]["decision"], "promoted")
            promoted_id = result["promotions"][0]["page_id"]
            search = client.search("冰美式 咖啡 偏好", limit=5)
            self.assertEqual(search["matches"][0]["id"], promoted_id)

    def test_promote_candidate_runs_review_guards_by_default(self) -> None:
        from mnemo_memory import MemoryClient

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)
            update = client.update(facts=["stuff"], source="unit-test")
            candidate_id = update["memory_candidates"][0]["candidate_id"]

            reviewed = client.promote_candidate(candidate_id)

            self.assertEqual(reviewed["decision"], "rejected")
            self.assertEqual(reviewed["reason"], "low_quality")
            self.assertEqual(client.list(kind="page", status="active", limit=10)["items"], [])

    def test_force_promote_candidate_is_admin_override(self) -> None:
        from mnemo_memory import MemoryClient

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)
            update = client.update(facts=["stuff"], source="unit-test")
            candidate_id = update["memory_candidates"][0]["candidate_id"]

            promoted = client.force_promote_candidate(candidate_id)

            self.assertEqual(promoted["kind"], "memory_force_promote")
            self.assertEqual(promoted["status"], "promoted")
            self.assertEqual(client.list(kind="page", status="active", limit=10)["count"], 1)

    def test_public_schema_is_memory_only(self) -> None:
        from mnemo_memory.sdk import memory_api_schema

        schema = memory_api_schema()
        self.assertEqual(schema["title"], "Mnemo Memory")
        self.assertEqual(schema["schema_version"], "mnemo_memory.api.v1")
        self.assertNotIn("run", schema["methods"])
        self.assertNotIn("external_run", schema["methods"])
        self.assertIn("ingest_event", schema["methods"])
        self.assertIn("update", schema["methods"])
        self.assertIn("list", schema["methods"])
        self.assertIn("provenance", schema["methods"])
        self.assertIn("dream_run", schema["methods"])
        self.assertIn("force_promote_candidate", schema["methods"])

    def test_http_dispatch_lists_memory_items(self) -> None:
        from mnemo_memory import MemoryClient
        from mnemo_memory.interfaces.web import dispatch_memory_api

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)
            update = client.update(facts=["HTTP clients can list memory inventory."], source="unit-test")
            candidate_id = update["memory_candidates"][0]["candidate_id"]

            listed = dispatch_memory_api(client, "list", {"kind": "candidate", "status": "draft"})

            self.assertEqual(listed["kind"], "memory_list")
            self.assertEqual(listed["items"][0]["id"], candidate_id)

    def test_http_dispatch_returns_memory_provenance(self) -> None:
        from mnemo_memory import MemoryClient
        from mnemo_memory.interfaces.web import dispatch_memory_api

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)
            update = client.update(
                facts=[
                    {
                        "claim": "HTTP clients can inspect provenance for selected memories.",
                        "confidence": 0.9,
                        "event_at": 1710000001,
                    }
                ],
                source="http-test",
            )
            candidate_id = update["memory_candidates"][0]["candidate_id"]

            result = dispatch_memory_api(client, "provenance", {"memory_id": candidate_id})

            self.assertEqual(result["kind"], "memory_provenance")
            self.assertEqual(result["memory_id"], candidate_id)
            self.assertEqual(result["events"][0]["source"], "http-test")

    def test_http_dispatch_ingests_raw_event(self) -> None:
        from mnemo_memory import MemoryClient
        from mnemo_memory.interfaces.web import dispatch_memory_api

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)
            result = dispatch_memory_api(
                client,
                "ingest-event",
                {
                    "text": "冰美式",
                    "source": "http-test",
                    "mission_id": "coffee-order-123",
                    "context": [{"role": "assistant", "content": "想要哪个咖啡？"}],
                },
            )

            self.assertEqual(result["kind"], "memory_event_ingest")
            self.assertEqual(result["memory_candidates"], [])
            self.assertEqual(result["working_notes"][0]["retention"], "ephemeral")

    def test_http_dispatch_force_promotes_candidate(self) -> None:
        from mnemo_memory import MemoryClient
        from mnemo_memory.interfaces.web import dispatch_memory_api

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)
            update = client.update(facts=["stuff"], source="unit-test")
            candidate_id = update["memory_candidates"][0]["candidate_id"]

            promoted = dispatch_memory_api(client, "force-promote-candidate", {"candidate_id": candidate_id})

            self.assertEqual(promoted["kind"], "memory_force_promote")
            self.assertEqual(promoted["status"], "promoted")

    def test_dream_run_min_confidence_applies_to_promote_actions(self) -> None:
        from mnemo_memory import MemoryClient

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)
            update = client.update(
                facts=[
                    {
                        "claim": "User prefers concise implementation updates for code changes and test results.",
                        "dimension": "preferences",
                        "confidence": 0.8,
                    }
                ],
                source="unit-test",
            )
            candidate_id = update["memory_candidates"][0]["candidate_id"]

            report = client.dream_run(
                min_confidence=0.9,
                actions=[{"tool": "memory_promote_candidate", "candidate_id": candidate_id}],
            )

            applied = report["execution"]["result"]["actions"]["applied"]
            self.assertEqual(applied[0]["decision"], "skipped")
            self.assertEqual(applied[0]["reason"], "below_confidence_threshold")
            self.assertEqual(client.list(kind="page", status="active", limit=10)["items"], [])

    def test_webui_can_enable_provider_backed_dream_run(self) -> None:
        source = Path(__file__).resolve().parents[1] / "webui" / "src" / "main.tsx"
        app = source.read_text(encoding="utf-8")

        self.assertIn("mnemo.useProvider", app)
        self.assertIn("use_provider: useProvider", app)

    def test_webui_displays_memory_provenance_timeline(self) -> None:
        source = Path(__file__).resolve().parents[1] / "webui" / "src" / "main.tsx"
        app = source.read_text(encoding="utf-8")

        self.assertIn('callMemory<MemoryProvenanceResult>("provenance"', app)
        self.assertIn("来源时间线", app)

    def test_mcp_exposes_only_memory_tools_with_new_prefix(self) -> None:
        from mnemo_memory.mcp import MemoryMcpServer

        with tempfile.TemporaryDirectory() as tmp:
            server = MemoryMcpServer(state_dir=tmp)
            names = {tool["name"] for tool in server.tools()}

            self.assertIn("mnemo_memory_update", names)
            self.assertIn("mnemo_memory_ingest_event", names)
            self.assertIn("mnemo_memory_search", names)
            self.assertIn("mnemo_memory_provenance", names)
            self.assertIn("mnemo_memory_dream_run", names)
            self.assertNotIn("mnemo_run", names)
            self.assertTrue(all(name.startswith("mnemo_memory_") for name in names))

            result = server.call_tool(
                "mnemo_memory_update",
                {"facts": ["User prefers compact memory capsules."], "source": "unit-test"},
            )
            self.assertEqual(result["kind"], "memory_update")
            self.assertEqual(result["memory_candidates"][0]["status"], "draft")


if __name__ == "__main__":
    unittest.main()
