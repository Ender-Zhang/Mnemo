from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
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
            self.assertIn("passed quality and confidence gates", promoted["reason"])

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

    def test_client_lists_memory_by_uid_scope(self) -> None:
        from mnemo_memory import MemoryClient

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)

            alpha_update = client.update(
                facts=[
                    {
                        "claim": "UID user_123 prefers concise implementation updates that include test results.",
                        "dimension": "preferences",
                        "scope": "user:user_123",
                        "confidence": 0.9,
                    }
                ],
                source="unit-test",
            )
            beta_update = client.update(
                facts=[
                    {
                        "claim": "UID userX123 wants quarterly roadmap goals summarized before tactical tasks.",
                        "dimension": "goals",
                        "scope": "user:userX123",
                        "confidence": 0.9,
                    }
                ],
                source="unit-test",
            )
            alpha_candidate_id = alpha_update["memory_candidates"][0]["candidate_id"]
            beta_candidate_id = beta_update["memory_candidates"][0]["candidate_id"]
            alpha_page_id = client.promote_candidate(alpha_candidate_id)["page_id"]
            beta_page_id = client.promote_candidate(beta_candidate_id)["page_id"]

            result = client.list(kind="all", status=None, uid="user_123", limit=20)
            ids = {item["id"] for item in result["items"]}

            self.assertEqual(result["uid"], "user_123")
            self.assertIn(alpha_candidate_id, ids)
            self.assertIn(alpha_page_id, ids)
            self.assertNotIn(beta_candidate_id, ids)
            self.assertNotIn(beta_page_id, ids)

    def test_client_directly_cruds_stable_memory_pages(self) -> None:
        from mnemo_memory import MemoryClient

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)

            created = client.stable_create(
                title="preferences: user_123 direct stable CRUD",
                content="user_123 prefers direct stable memory CRUD examples.\nKeep markdown newlines.",
                scope="user:user_123",
                dimension="preferences",
                confidence=0.91,
            )
            page_id = created["memory_id"]

            self.assertEqual(created["kind"], "stable_memory_create")
            self.assertEqual(created["item"]["id"], page_id)
            self.assertEqual(created["item"]["metadata"]["dimension"], "preferences")
            self.assertTrue(Path(tmp).joinpath(created["wiki"]["path"]).exists())

            keyword = client.stable_search("direct stable CRUD", limit=5)
            self.assertEqual(keyword["kind"], "stable_memory_search")
            self.assertFalse(keyword["all"])
            self.assertEqual(keyword["items"][0]["id"], page_id)

            all_pages = client.stable_search(all_items=True)
            self.assertTrue(all_pages["all"])
            self.assertEqual(all_pages["count"], 1)
            self.assertEqual(all_pages["items"][0]["id"], page_id)

            updated = client.stable_update(
                page_id,
                content="user_123 prefers direct stable memory CRUD examples with update coverage.",
            )
            self.assertEqual(updated["kind"], "stable_memory_update")
            self.assertIn("update coverage", client.stable_read(page_id)["item"]["content"])

            deleted = client.stable_delete(page_id, mode="tombstone", reason="outdated")
            self.assertEqual(deleted["kind"], "stable_memory_delete")
            self.assertEqual(deleted["mode"], "tombstone")
            self.assertEqual(deleted["result"]["target_type"], "page")
            self.assertTrue(client.stable_read(page_id)["item"]["status"].startswith("tombstoned:"))

    def test_client_cruds_plan_items_and_includes_active_plans_in_context(self) -> None:
        from mnemo_memory import MemoryClient

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)

            goal = client.plan_create(
                kind="goal",
                title="完成 Mnemo 计划模块",
                detail="覆盖 SDK、HTTP、CLI、WebUI 和测试。",
                uid="user_123",
                priority="high",
            )["item"]
            todo = client.plan_create(
                kind="todo",
                title="补齐 plan-list HTTP 测试",
                parent_id=goal["id"],
                uid="user_123",
            )["item"]
            client.plan_create(kind="todo", title="另一个用户的计划", uid="user_456")

            listed = client.plan_list(uid="user_123")
            ids = {item["id"] for item in listed["items"]}
            self.assertEqual(listed["kind"], "plan_item_list")
            self.assertIn(goal["id"], ids)
            self.assertIn(todo["id"], ids)
            self.assertNotIn("另一个用户的计划", {item["title"] for item in listed["items"]})

            user_goals = client.user_goals("user:user_123")
            goal_ids = {item["id"] for item in user_goals["goals"]}
            self.assertEqual(user_goals["kind"], "user_goals")
            self.assertEqual(user_goals["uid"], "user_123")
            self.assertEqual(user_goals["scope"], "user:user_123")
            self.assertIn(goal["id"], goal_ids)
            self.assertIn(todo["id"], goal_ids)
            self.assertEqual(user_goals["proposal_count"], 0)

            updated = client.plan_update(todo["id"], status="doing", detail="HTTP dispatch 需要覆盖 query 和全量 list。")
            self.assertEqual(updated["item"]["status"], "doing")

            context = client.context("Mnemo 计划模块 HTTP 测试", limit=5)
            plan_cards = [card for card in context["cards"] if card["type"] == "plan_item"]
            self.assertTrue(plan_cards)
            self.assertIn("计划", plan_cards[0]["title"])

            completed = client.plan_complete(todo["id"])
            self.assertEqual(completed["item"]["status"], "done")
            cancelled = client.plan_cancel(goal["id"], reason="changed_direction")
            self.assertEqual(cancelled["item"]["status"], "cancelled")
            self.assertEqual(cancelled["item"]["metadata"]["cancel_reason"], "changed_direction")

    def test_ingest_event_extracts_plan_proposal_before_direct_plan_write(self) -> None:
        from mnemo_memory import MemoryClient

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)

            result = client.ingest_event(
                text="我计划下周完成 Mnemo 的计划页面。",
                source="unit-test",
                actor="user",
                scope="user:demo",
            )

            self.assertEqual(result["kind"], "memory_event_ingest")
            self.assertEqual(result["memory_candidates"], [])
            self.assertEqual(result["working_notes"], [])
            self.assertEqual(result["plan_proposals"][0]["proposal_status"], "pending")
            self.assertEqual(result["plan_proposals"][0]["scope"], "user:demo")

            user_goals = client.user_goals("demo")
            self.assertEqual(user_goals["count"], 0)
            self.assertEqual(user_goals["proposal_count"], 1)
            self.assertEqual(user_goals["proposals"][0]["id"], result["plan_proposals"][0]["id"])
            self.assertEqual(client.user_goals("demo", include_proposals=False)["proposals"], [])

            listed = client.plan_list(uid="demo")
            self.assertEqual(listed["items"], [])
            applied = client.apply_plan_proposal(result["plan_proposals"][0]["id"])
            self.assertEqual(applied["proposal"]["proposal_status"], "accepted")
            self.assertEqual(applied["result"]["item"]["kind"], "goal")
            self.assertEqual(client.plan_list(uid="demo")["count"], 1)

            other = client.ingest_event(text="提醒我补齐计划模块 README。", source="unit-test", scope="user:demo")
            rejected = client.reject_plan_proposal(other["plan_proposals"][0]["id"], reason="duplicate")
            self.assertEqual(rejected["proposal"]["proposal_status"], "rejected")

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

    def test_user_provided_private_profile_fact_can_be_promoted(self) -> None:
        from mnemo_memory import MemoryClient

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)
            update = client.update(
                facts=[
                    {
                        "claim": "User private address is 123 Main St.",
                        "dimension": "identity",
                        "scope": "user:demo",
                        "confidence": 0.9,
                    }
                ],
                source="unit-test",
            )
            candidate = update["memory_candidates"][0]
            candidate_id = candidate["candidate_id"]

            self.assertEqual(candidate["status"], "draft")
            self.assertEqual(candidate["quality"]["recommendation"], "write")

            promoted = client.promote_candidate(candidate_id)

            self.assertEqual(promoted["decision"], "promoted")
            self.assertEqual(promoted["status"], "promoted")
            page = client.read(promoted["page_id"])["item"]
            self.assertEqual(page["metadata"]["dimension"], "identity")
            self.assertIn("private address", page["content"])

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

    def test_hard_delete_removes_tombstoned_memory_records(self) -> None:
        from mnemo_memory import MemoryClient

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)
            update = client.update(
                facts=[
                    {
                        "claim": "User wants obsolete memory records to be physically removable from tombstone review.",
                        "dimension": "preferences",
                        "confidence": 0.92,
                    }
                ],
                source="unit-test",
            )
            candidate_id = update["memory_candidates"][0]["candidate_id"]
            promoted = client.promote_candidate(candidate_id)
            page_id = promoted["page_id"]
            self.assertTrue(Path(tmp).joinpath(promoted["wiki"]["path"]).exists())

            tombstone = client.tombstone(page_id, "outdated", target_type="page")
            tombstone_id = tombstone["tombstone_id"]

            deleted = client.hard_delete(tombstone_id=tombstone_id)

            self.assertEqual(deleted["kind"], "memory_hard_delete")
            self.assertTrue(deleted["deleted"])
            self.assertIn(page_id, deleted["deleted_pages"])
            self.assertIn(candidate_id, deleted["deleted_candidates"])
            self.assertGreaterEqual(deleted["counts"]["pages"], 1)
            self.assertGreaterEqual(deleted["counts"]["candidates"], 1)
            self.assertEqual(client.tombstones(limit=10)["tombstones"], [])
            with self.assertRaises(ValueError):
                client.read(page_id)
            with self.assertRaises(ValueError):
                client.read(candidate_id)
            self.assertFalse(any(Path(tmp).joinpath(path).exists() for path in deleted["removed_wiki"]))

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
        self.assertIn("dream_proposals", schema["methods"])
        self.assertIn("apply_dream_proposal", schema["methods"])
        self.assertIn("reject_dream_proposal", schema["methods"])
        self.assertIn("force_promote_candidate", schema["methods"])
        self.assertIn("hard_delete", schema["methods"])
        self.assertIn("stable_create", schema["methods"])
        self.assertIn("stable_read", schema["methods"])
        self.assertIn("stable_update", schema["methods"])
        self.assertIn("stable_search", schema["methods"])
        self.assertIn("stable_delete", schema["methods"])
        self.assertIn("plan_create", schema["methods"])
        self.assertIn("plan_read", schema["methods"])
        self.assertIn("plan_update", schema["methods"])
        self.assertIn("plan_list", schema["methods"])
        self.assertIn("plan_complete", schema["methods"])
        self.assertIn("plan_cancel", schema["methods"])
        self.assertIn("plan_archive", schema["methods"])
        self.assertIn("plan_proposals", schema["methods"])
        self.assertIn("user_goals", schema["methods"])
        self.assertIn("apply_plan_proposal", schema["methods"])
        self.assertIn("reject_plan_proposal", schema["methods"])

    def test_http_dispatch_lists_memory_items(self) -> None:
        from mnemo_memory import MemoryClient
        from mnemo_memory.interfaces.web import dispatch_memory_api

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)
            update = client.update(
                facts=[
                    {
                        "claim": "HTTP clients can list memory inventory for alpha users.",
                        "scope": "user:alpha",
                    }
                ],
                source="unit-test",
            )
            client.update(
                facts=[
                    {
                        "claim": "HTTP clients can list memory inventory for beta users.",
                        "scope": "user:beta",
                    }
                ],
                source="unit-test",
            )
            candidate_id = update["memory_candidates"][0]["candidate_id"]

            listed = dispatch_memory_api(client, "list", {"kind": "candidate", "status": "draft", "uid": "alpha"})

            self.assertEqual(listed["kind"], "memory_list")
            self.assertEqual(listed["uid"], "alpha")
            self.assertEqual(len(listed["items"]), 1)
            self.assertEqual(listed["items"][0]["id"], candidate_id)

    def test_http_dispatch_directly_cruds_stable_memory_pages(self) -> None:
        from mnemo_memory import MemoryClient
        from mnemo_memory.interfaces.web import dispatch_memory_api

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)

            created = dispatch_memory_api(
                client,
                "stable-create",
                {
                    "title": "preferences: HTTP direct stable memory",
                    "content": "HTTP clients can create stable memory pages directly.",
                    "scope": "user:http",
                    "dimension": "preferences",
                    "confidence": 0.9,
                },
            )
            page_id = created["memory_id"]

            keyword = dispatch_memory_api(
                client,
                "stable-search",
                {"query": "direct stable", "uid": "http", "limit": 5},
            )
            self.assertEqual(keyword["items"][0]["id"], page_id)
            self.assertFalse(keyword["all"])

            all_pages = dispatch_memory_api(client, "stable-search", {"all": True})
            self.assertEqual(all_pages["count"], 1)
            self.assertTrue(all_pages["all"])

            updated = dispatch_memory_api(
                client,
                "stable-update",
                {
                    "memory_id": page_id,
                    "content": "HTTP clients can update stable memory pages directly.",
                },
            )
            self.assertIn("update stable", updated["item"]["content"])

            read = dispatch_memory_api(client, "stable-read", {"memory_id": page_id})
            self.assertEqual(read["item"]["id"], page_id)

            deleted = dispatch_memory_api(
                client,
                "stable-delete",
                {"memory_id": page_id, "mode": "tombstone", "reason": "outdated"},
            )
            self.assertEqual(deleted["result"]["target_type"], "page")

    def test_http_dispatch_cruds_plan_items_and_proposals(self) -> None:
        from mnemo_memory import MemoryClient
        from mnemo_memory.interfaces.web import dispatch_memory_api

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)

            created = dispatch_memory_api(
                client,
                "plan-create",
                {
                    "kind": "goal",
                    "title": "完成 HTTP 计划接口",
                    "uid": "http",
                    "priority": "high",
                },
            )
            plan_id = created["item"]["id"]

            listed = dispatch_memory_api(client, "plan-list", {"uid": "http", "limit": 20})
            self.assertEqual(listed["kind"], "plan_item_list")
            self.assertEqual(listed["items"][0]["id"], plan_id)

            updated = dispatch_memory_api(client, "plan-update", {"plan_id": plan_id, "status": "paused"})
            self.assertEqual(updated["item"]["status"], "paused")

            completed = dispatch_memory_api(client, "plan-complete", {"plan_id": plan_id})
            self.assertEqual(completed["item"]["status"], "completed")

            ingest = dispatch_memory_api(
                client,
                "ingest-event",
                {"text": "待办：补齐 HTTP plan proposal 测试。", "scope": "user:http", "source": "http-test"},
            )
            proposal_id = ingest["plan_proposals"][0]["id"]
            proposals = dispatch_memory_api(client, "plan-proposals", {"uid": "http"})
            self.assertEqual(proposals["proposals"][0]["id"], proposal_id)

            user_goals = dispatch_memory_api(client, "user-goals", {"uid": "user:http", "limit": 20})
            self.assertEqual(user_goals["kind"], "user_goals")
            self.assertEqual(user_goals["uid"], "http")
            self.assertEqual(user_goals["scope"], "user:http")
            self.assertEqual(user_goals["count"], 1)
            self.assertEqual(user_goals["proposal_count"], 1)
            self.assertEqual(user_goals["proposals"][0]["id"], proposal_id)

            rejected = dispatch_memory_api(
                client,
                "reject-plan-proposal",
                {"proposal_id": proposal_id, "reason": "test_rejected"},
            )
            self.assertEqual(rejected["proposal"]["proposal_status"], "rejected")

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

    def test_cli_directly_cruds_stable_memory_pages(self) -> None:
        from mnemo_memory.interfaces.cli import main

        def run_cli(argv: list[str]) -> dict[str, object]:
            output = StringIO()
            with redirect_stdout(output):
                code = main(argv)
            self.assertEqual(code, 0, output.getvalue())
            return json.loads(output.getvalue())

        with tempfile.TemporaryDirectory() as tmp:
            created = run_cli(
                [
                    "stable",
                    "add",
                    "--title",
                    "preferences: CLI direct stable memory",
                    "--content",
                    "CLI users can create stable memories directly.",
                    "--scope",
                    "user:cli",
                    "--dimension",
                    "preferences",
                    "--state-dir",
                    tmp,
                    "--json",
                ]
            )
            page_id = str(created["memory_id"])

            keyword = run_cli(["stable", "search", "direct stable", "--state-dir", tmp, "--json"])
            self.assertEqual(keyword["items"][0]["id"], page_id)
            self.assertFalse(keyword["all"])

            all_pages = run_cli(["stable", "search", "--all", "--state-dir", tmp, "--json"])
            self.assertTrue(all_pages["all"])
            self.assertEqual(all_pages["items"][0]["id"], page_id)

            updated = run_cli(
                [
                    "stable",
                    "update",
                    page_id,
                    "--content",
                    "CLI users can update stable memories directly.",
                    "--state-dir",
                    tmp,
                    "--json",
                ]
            )
            self.assertIn("update stable", updated["item"]["content"])

    def test_cli_cruds_plan_items(self) -> None:
        from mnemo_memory.interfaces.cli import main

        def run_cli(argv: list[str]) -> dict[str, object]:
            output = StringIO()
            with redirect_stdout(output):
                code = main(argv)
            self.assertEqual(code, 0, output.getvalue())
            return json.loads(output.getvalue())

        with tempfile.TemporaryDirectory() as tmp:
            created = run_cli(
                [
                    "plan",
                    "add",
                    "--kind",
                    "todo",
                    "--title",
                    "补齐 CLI 计划测试",
                    "--uid",
                    "cli",
                    "--state-dir",
                    tmp,
                    "--json",
                ]
            )
            plan_id = str(created["item"]["id"])

            listed = run_cli(["plan", "list", "CLI", "--uid", "cli", "--state-dir", tmp, "--json"])
            self.assertEqual(listed["items"][0]["id"], plan_id)

            user_goals = run_cli(["plan", "user-goals", "--uid", "user:cli", "--state-dir", tmp, "--json"])
            self.assertEqual(user_goals["kind"], "user_goals")
            self.assertEqual(user_goals["uid"], "cli")
            self.assertEqual(user_goals["goals"][0]["id"], plan_id)

            updated = run_cli(["plan", "update", plan_id, "--status", "doing", "--state-dir", tmp, "--json"])
            self.assertEqual(updated["item"]["status"], "doing")

            completed = run_cli(["plan", "complete", plan_id, "--state-dir", tmp, "--json"])
            self.assertEqual(completed["item"]["status"], "done")

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

    def test_http_dispatch_hard_deletes_tombstone_target(self) -> None:
        from mnemo_memory import MemoryClient
        from mnemo_memory.interfaces.web import dispatch_memory_api

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)
            update = client.update(
                facts=[
                    {
                        "claim": "HTTP clients can physically delete a tombstoned memory from the review page.",
                        "dimension": "preferences",
                        "confidence": 0.9,
                    }
                ],
                source="unit-test",
            )
            candidate_id = update["memory_candidates"][0]["candidate_id"]
            page_id = client.promote_candidate(candidate_id)["page_id"]
            tombstone_id = client.tombstone(page_id, "outdated", target_type="page")["tombstone_id"]

            deleted = dispatch_memory_api(client, "hard-delete", {"tombstone_id": tombstone_id})

            self.assertEqual(deleted["kind"], "memory_hard_delete")
            self.assertIn(page_id, deleted["deleted_pages"])
            self.assertEqual(client.tombstones(limit=10)["tombstones"], [])

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

    def test_dream_backlog_keeps_unresolved_candidates_after_latest_report(self) -> None:
        from mnemo_memory import MemoryClient

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)
            client.update(
                facts=[
                    {
                        "claim": "User prefers Dream maintenance to keep unresolved memory candidates visible across repeated runs.",
                        "dimension": "preferences",
                        "confidence": 0.9,
                    }
                ],
                source="unit-test",
            )

            # Deterministic fallback promotes the high-confidence candidate
            first = client.dream_run()
            self.assertGreaterEqual(first["execution"]["result"]["actions"]["counts"]["requested"], 1)
            self.assertEqual(first["execution"]["mode"], "deterministic_fallback")

            # After promotion, backlog should be clear
            second = client.dream_run()
            self.assertEqual(second["delta"]["counts"]["draft_candidates"], 0)

    def test_dream_status_exposes_reject_reasons(self) -> None:
        from mnemo_memory import MemoryClient

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)
            update = client.update(
                facts=[
                    {
                        "claim": "User prefers stale Dream reject reasons to remain visible after refresh.",
                        "dimension": "preferences",
                        "confidence": 0.8,
                    }
                ],
                source="unit-test",
            )
            candidate_id = update["memory_candidates"][0]["candidate_id"]

            report = client.dream_run(
                actions=[
                    {
                        "tool": "memory_reject_candidate",
                        "candidate_id": candidate_id,
                        "reason": "not_enough_evidence",
                    }
                ],
            )
            applied = report["execution"]["result"]["actions"]["applied"]
            self.assertEqual(applied[0]["reason"], "not_enough_evidence")

            status = client.dream_status()
            review_results = status["latest"]["execution"]["review_results"]
            self.assertEqual(review_results[0]["candidate_id"], candidate_id)
            self.assertEqual(review_results[0]["decision"], "rejected")
            self.assertEqual(review_results[0]["reason"], "not_enough_evidence")
            reasons = status["latest"]["execution"]["reject_reasons"]
            self.assertEqual(reasons[0]["candidate_id"], candidate_id)
            self.assertEqual(reasons[0]["reason"], "not_enough_evidence")

    def test_dream_status_exposes_promote_reasons(self) -> None:
        from mnemo_memory import MemoryClient

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)
            update = client.update(
                facts=[
                    {
                        "claim": "User prefers Dream approval reasons to appear in candidate review panels and audit badges.",
                        "dimension": "preferences",
                        "confidence": 0.9,
                    }
                ],
                source="unit-test",
            )
            candidate_id = update["memory_candidates"][0]["candidate_id"]

            report = client.dream_run(
                actions=[
                    {
                        "tool": "memory_promote_candidate",
                        "candidate_id": candidate_id,
                        "reason": "explicit_user_preference",
                    }
                ],
            )
            applied = report["execution"]["result"]["actions"]["applied"]
            self.assertEqual(applied[0]["decision"], "promoted")
            self.assertEqual(applied[0]["reason"], "explicit_user_preference")
            self.assertIn("passed quality and confidence gates", applied[0]["gate_reason"])

            status = client.dream_status()
            review_results = status["latest"]["execution"]["review_results"]
            self.assertEqual(review_results[0]["candidate_id"], candidate_id)
            self.assertEqual(review_results[0]["decision"], "promoted")
            self.assertEqual(review_results[0]["reason"], "explicit_user_preference")
            self.assertIn("passed quality and confidence gates", review_results[0]["gate_reason"])

    def test_dream_maintains_goal_proposals_and_goal_items(self) -> None:
        from mnemo_memory import MemoryClient

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)
            ingest = client.ingest_event(
                text="我计划下周完成 Dream 目标维护测试。",
                source="unit-test",
                actor="user",
                scope="user:demo",
            )
            proposal_id = ingest["plan_proposals"][0]["id"]

            status = client.dream_status()
            self.assertEqual(status["backlog"]["pending_plan_proposals"], 1)

            accepted = client.dream_run(
                actions=[
                    {
                        "tool": "goal_apply_proposal",
                        "proposal_id": proposal_id,
                        "reason": "explicit_user_goal",
                    }
                ],
            )
            applied = accepted["execution"]["result"]["actions"]["applied"][0]
            self.assertEqual(applied["tool"], "goal_apply_proposal")
            self.assertEqual(applied["decision"], "accepted")
            self.assertEqual(applied["reason"], "explicit_user_goal")
            self.assertEqual(applied["proposal_status"], "accepted")

            all_proposals = client.plan_proposals(status=None, uid="demo")
            self.assertEqual(all_proposals["proposals"][0]["decision_reason"], "explicit_user_goal")
            user_goals = client.user_goals("demo")
            goal_id = user_goals["goals"][0]["id"]
            self.assertEqual(user_goals["proposal_count"], 0)

            created = client.dream_run(
                actions=[
                    {
                        "tool": "goal_create",
                        "title": "维护 Dream 直接目标",
                        "uid": "demo",
                        "priority": "high",
                        "reason": "follow_up_needed",
                    }
                ],
            )
            direct_goal_id = created["execution"]["result"]["actions"]["applied"][0]["goal_id"]
            direct_goal = client.plan_read(direct_goal_id)["item"]
            self.assertEqual(direct_goal["scope"], "user:demo")
            self.assertEqual(direct_goal["metadata"]["dream_reason"], "follow_up_needed")

            maintained = client.dream_run(
                actions=[
                    {"tool": "goal_update", "goal_id": goal_id, "status": "paused", "reason": "waiting_for_context"},
                    {"tool": "goal_complete", "goal_id": goal_id, "reason": "done_by_user"},
                    {"tool": "goal_cancel", "goal_id": direct_goal_id, "reason": "duplicate_goal"},
                    {"tool": "goal_archive", "goal_id": direct_goal_id, "reason": "closed_out"},
                    {"tool": "goal_update", "goal_id": "missing_goal", "reason": "bad_id"},
                ],
            )
            actions = maintained["execution"]["result"]["actions"]
            self.assertEqual(actions["counts"]["applied"], 4)
            self.assertEqual(actions["counts"]["skipped"], 1)
            self.assertEqual(actions["skipped"][0]["tool"], "goal_update")
            self.assertIn("plan item not found", actions["skipped"][0]["reason"])
            self.assertEqual(client.plan_read(goal_id)["item"]["status"], "completed")
            archived = client.plan_read(direct_goal_id)["item"]
            self.assertEqual(archived["status"], "archived")
            self.assertEqual(archived["metadata"]["cancel_reason"], "duplicate_goal")

            rejected_ingest = client.ingest_event(
                text="提醒我补齐一个重复目标。",
                source="unit-test",
                actor="user",
                scope="user:demo",
            )
            rejected_id = rejected_ingest["plan_proposals"][0]["id"]
            rejected_report = client.dream_run(
                actions=[
                    {
                        "tool": "goal_reject_proposal",
                        "proposal_id": rejected_id,
                        "reason": "duplicate_goal",
                    }
                ],
            )
            rejected = rejected_report["execution"]["result"]["actions"]["applied"][0]
            self.assertEqual(rejected["decision"], "rejected")
            self.assertEqual(rejected["proposal_status"], "rejected")
            self.assertEqual(rejected["reason"], "duplicate_goal")

    def test_webui_can_enable_provider_backed_dream_run(self) -> None:
        source = Path(__file__).resolve().parents[1] / "webui" / "src" / "main.tsx"
        app = source.read_text(encoding="utf-8")

        self.assertIn("mnemo.useProvider", app)
        self.assertIn("use_provider: useProvider", app)

    def test_advanced_dreaming_creates_and_applies_rewrite_proposal(self) -> None:
        from mnemo_memory import MemoryClient

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)
            page = client.stable_create(
                title="context: scattered notes",
                content="- Old scattered project note.",
                scope="project:mnemo",
                confidence=0.8,
            )["item"]

            report = client.dream_run(
                advanced_dreaming=True,
                actions=[
                    {
                        "tool": "memory_rewrite_page",
                        "page_id": page["id"],
                        "proposed_title": "context: Mnemo WebUI direction",
                        "proposed_content": "- Mnemo WebUI should default to a memory workbench and keep debug details in advanced mode.",
                        "rationale": "Consolidate scattered wording into a clearer stable memory page.",
                    }
                ],
            )
            proposals = report["execution"]["result"]["actions"]["proposals"]
            self.assertEqual(len(proposals), 1)
            self.assertEqual(proposals[0]["tool"], "memory_rewrite_page")
            self.assertEqual(proposals[0]["status"], "pending")

            listed = client.dream_proposals()
            proposal = listed["proposals"][0]
            self.assertEqual(proposal["status"], "pending")
            self.assertEqual(proposal["before"]["page"]["id"], page["id"])

            applied = client.apply_dream_proposal(proposal["id"])
            self.assertEqual(applied["proposal"]["status"], "applied")
            updated = client.stable_read(page["id"])["item"]
            self.assertEqual(updated["title"], "context: Mnemo WebUI direction")
            self.assertIn("memory workbench", updated["content"])

    def test_advanced_dreaming_auto_applies_page_links(self) -> None:
        from mnemo_memory import MemoryClient

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)
            left = client.stable_create(title="User preferences", content="- Prefers concise updates.")["item"]
            right = client.stable_create(title="Project rules", content="- Keep WebUI assets packaged.")["item"]

            report = client.dream_run(
                advanced_dreaming=True,
                actions=[
                    {
                        "tool": "memory_link_pages",
                        "source_id": left["id"],
                        "target_id": right["id"],
                        "relation": "related_context",
                        "weight": 0.8,
                    }
                ],
            )

            applied = report["execution"]["result"]["actions"]["applied"][0]
            self.assertEqual(applied["tool"], "memory_link_pages")
            self.assertEqual(applied["status"], "applied")
            links = client.links(left["id"])
            self.assertEqual(links["outgoing"][0]["target_id"], right["id"])
            self.assertEqual(links["outgoing"][0]["relation"], "related_context")

    def test_http_dispatch_lists_and_rejects_dream_proposals(self) -> None:
        from mnemo_memory import MemoryClient
        from mnemo_memory.interfaces.web import dispatch_memory_api

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)
            page = client.stable_create(
                title="context: stale stable page",
                content="- Old version.",
                scope="project:mnemo",
            )["item"]
            client.dream_run(
                advanced_dreaming=True,
                actions=[
                    {
                        "tool": "memory_rewrite_page",
                        "page_id": page["id"],
                        "proposed_content": "- New version.",
                        "rationale": "Test proposal dispatch.",
                    }
                ],
            )

            pending = dispatch_memory_api(client, "dream-proposals", {"limit": 50})
            proposal_id = pending["proposals"][0]["id"]
            rejected = dispatch_memory_api(
                client,
                "reject-dream-proposal",
                {"proposal_id": proposal_id, "reason": "test_rejected"},
            )
            all_proposals = dispatch_memory_api(client, "dream-proposals", {"status": None, "limit": 50})

            self.assertEqual(rejected["proposal"]["status"], "rejected")
            self.assertEqual(all_proposals["count"], 1)
            self.assertEqual(all_proposals["proposals"][0]["status"], "rejected")

    def test_webui_exposes_advanced_dreaming_controls(self) -> None:
        source = Path(__file__).resolve().parents[1] / "webui" / "src" / "main.tsx"
        app = source.read_text(encoding="utf-8")

        self.assertIn("mnemo.advancedDreaming", app)
        self.assertIn("advanced_dreaming: advancedDreaming", app)
        self.assertIn("DreamProposalsPanel", app)

    def test_webui_keeps_dream_run_feedback_after_refresh(self) -> None:
        source = Path(__file__).resolve().parents[1] / "webui" / "src" / "main.tsx"
        app = source.read_text(encoding="utf-8")

        self.assertIn('const report = await callMemory<DreamRunReport>("dream-run"', app)
        self.assertIn("await refresh({ clearNotice: false })", app)
        self.assertIn("setOk(dreamRunMessage(report, useProvider, advancedDreaming))", app)
        self.assertIn("Dream 已运行：已生成报告和快照", app)
        self.assertIn("duration_s", app)
        self.assertIn("用时", app)

    def test_webui_exposes_auto_dream_settings(self) -> None:
        source = Path(__file__).resolve().parents[1] / "webui" / "src" / "main.tsx"
        app = source.read_text(encoding="utf-8")
        provider_settings = (Path(__file__).resolve().parents[1] / "webui" / "src" / "providerSettings.ts").read_text(
            encoding="utf-8"
        )

        self.assertIn('callMemory<AutoDreamStatusResult>("auto-dream-status"', app)
        self.assertIn('callMemory<AutoDreamStatusResult>("save-auto-dream-config"', app)
        self.assertIn("自动 Dreaming", app)
        self.assertIn("间隔分钟", app)
        self.assertIn("autoDreamFormFromStatus", provider_settings)
        self.assertIn("autoDreamSavePayload", provider_settings)

    def test_webui_shows_dream_elapsed_time_while_running(self) -> None:
        source = Path(__file__).resolve().parents[1] / "webui" / "src" / "main.tsx"
        app = source.read_text(encoding="utf-8")

        self.assertIn("dreamStartedAtMs", app)
        self.assertIn("dreamElapsedS", app)
        self.assertIn("DreamTiming", app)
        self.assertIn("Running ${formatDuration(props.dreamElapsedS)}", app)

    def test_webui_displays_dream_review_reasons(self) -> None:
        source = Path(__file__).resolve().parents[1] / "webui" / "src" / "main.tsx"
        app = source.read_text(encoding="utf-8")

        self.assertIn("DreamReviewReasons", app)
        self.assertIn("审核原因", app)
        self.assertIn("dreamStatusReviewReasons", app)
        self.assertIn("dreamRunRejectReasons", app)

    def test_webui_displays_memory_audit_result_column(self) -> None:
        source = Path(__file__).resolve().parents[1] / "webui" / "src" / "main.tsx"
        app = source.read_text(encoding="utf-8")

        self.assertIn("审核结果", app)
        self.assertIn("AuditResultBadge", app)
        self.assertIn("AuditDetail", app)
        self.assertIn("detailedAuditReason", app)
        self.assertIn("stableMemoryFallbackReason", app)
        self.assertIn("dreamReviewResultMap", app)
        self.assertIn("review_results", app)

    def test_webui_displays_candidate_review_reasons(self) -> None:
        source = Path(__file__).resolve().parents[1] / "webui" / "src" / "main.tsx"
        app = source.read_text(encoding="utf-8")

        self.assertIn("dreamStatus={dreamStatus}", app)
        self.assertIn("const reviewResults = dreamReviewResultMap(props.dreamStatus)", app)
        self.assertIn("<AuditResultBadge item={candidate} review={reviewForItem(candidate, reviewResults)} />", app)
        self.assertIn("isReviewableCandidate(candidate)", app)

    def test_webui_keeps_promoted_candidates_out_of_candidate_review(self) -> None:
        root = Path(__file__).resolve().parents[1]
        app = root.joinpath("webui", "src", "main.tsx").read_text(encoding="utf-8")
        filters = root.joinpath("webui", "src", "candidateFilters.ts").read_text(encoding="utf-8")

        self.assertIn('useState<"all" | "candidate" | "page">("page")', app)
        self.assertIn("filterCandidateReviewItems(candidates)", app)
        self.assertIn("candidates={candidateReviewItems}", app)
        self.assertIn("Promote 通过后会进入记忆页", app)
        self.assertIn("!isPromotedCandidate(candidate)", filters)

    def test_webui_displays_memory_provenance_timeline(self) -> None:
        source = Path(__file__).resolve().parents[1] / "webui" / "src" / "main.tsx"
        app = source.read_text(encoding="utf-8")

        self.assertIn('callMemory<MemoryProvenanceResult>("provenance"', app)
        self.assertIn("来源时间线", app)

    def test_webui_has_tombstone_review_actions(self) -> None:
        source = Path(__file__).resolve().parents[1] / "webui" / "src" / "main.tsx"
        app = source.read_text(encoding="utf-8")

        self.assertIn('key: "tombstones"', app)
        self.assertIn("function TombstonePanel", app)
        self.assertIn('callMemory("forget"', app)
        self.assertIn('callMemory("hard-delete"', app)
        self.assertIn("selectedTombstoneIds", app)
        self.assertIn("toggleAllTombstones", app)
        self.assertIn("hardDeleteSelectedTombstones", app)
        self.assertIn("彻底删除选中", app)
        self.assertIn("全选", app)
        self.assertIn("彻底删除", app)

    def test_webui_exposes_plan_page_and_plan_proposals(self) -> None:
        source = Path(__file__).resolve().parents[1] / "webui" / "src" / "main.tsx"
        app = source.read_text(encoding="utf-8")

        self.assertIn('key: "plans"', app)
        self.assertIn("function PlanPanel", app)
        self.assertIn('callMemory<PlanListResult>("plan-list"', app)
        self.assertIn('callMemory<PlanProposalsResult>("plan-proposals"', app)
        self.assertIn('callMemory("plan-create"', app)
        self.assertIn('callMemory("plan-complete"', app)
        self.assertIn('callMemory("apply-plan-proposal"', app)
        self.assertIn("候选目标", app)
        self.assertIn("新增目标", app)
        self.assertIn("buildGoalUserGroups", app)
        self.assertIn("goal-user-workspace", app)
        self.assertIn("点开用户后查看他的多个目标", app)
        self.assertNotIn('<option value="todo">Todo</option>', app)
        self.assertNotIn('title="Todos"', app)

    def test_webui_can_filter_memories_by_uid(self) -> None:
        source = Path(__file__).resolve().parents[1] / "webui" / "src" / "main.tsx"
        app = source.read_text(encoding="utf-8")

        self.assertNotIn('{ key: "search"', app)
        self.assertIn('useState<TabKey>("memories")', app)
        self.assertIn("uidFilter", app)
        self.assertIn("uid: cleanUid", app)
        self.assertIn("uid: scopedUid", app)
        self.assertIn("全部 scope", app)
        self.assertIn("function scopeFromUidFilter", app)
        self.assertIn("memoryFactPayload(factText.trim(), writeScope)", app)
        self.assertIn("confidence: 0.9", app)
        self.assertIn('retention: "memory_candidate"', app)
        self.assertIn("UID 检索完成", app)
        self.assertIn("user_123 或 user:user_123", app)

    def test_webui_compacts_long_status_badges(self) -> None:
        root = Path(__file__).resolve().parents[1]
        app = root.joinpath("webui", "src", "main.tsx").read_text(encoding="utf-8")
        css = root.joinpath("webui", "src", "styles.css").read_text(encoding="utf-8")

        self.assertIn("function compactStatusText", app)
        self.assertIn("title={text}", app)
        self.assertIn("<label>状态</label>", app)
        self.assertIn("text-overflow: ellipsis", css)
        self.assertIn("overflow: hidden", css)

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
