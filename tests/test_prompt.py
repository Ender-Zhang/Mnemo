from __future__ import annotations

import unittest

from mnemo.core.models import ToolSpec
from mnemo.prompt import PromptAssembler


class PromptAssemblerTests(unittest.TestCase):
    def test_block_order_is_deterministic(self) -> None:
        prompt = PromptAssembler().assemble(
            "Continue the work",
            mission={"brief": "Build prompt assembly", "checkpoint": {"open_decisions": ["none"]}},
            tool_specs=[_tool("z_tool"), _tool("a_tool")],
        )

        self.assertEqual(
            [block.id for block in prompt.blocks],
            [
                "system.identity",
                "developer.operating_principles",
                "tools.cards",
                "mission.continuation",
                "turn.current_user_message",
            ],
        )
        tool_content = prompt.blocks[2].content
        self.assertLess(tool_content.index("a_tool"), tool_content.index("z_tool"))

    def test_cache_policy_splits_stable_prefix_and_dynamic_tail(self) -> None:
        metadata = PromptAssembler().assemble("Hello", tool_specs=[_tool("memory_search")]).metadata()

        self.assertEqual(
            metadata["stable_prefix"],
            ["system.identity", "developer.operating_principles", "tools.cards"],
        )
        self.assertEqual(metadata["dynamic_tail"], ["mission.continuation", "turn.current_user_message"])

        policies = {block["id"]: block["cache_policy"] for block in metadata["blocks"]}
        segments = {block["id"]: block["cache_segment"] for block in metadata["blocks"]}
        self.assertEqual(policies["system.identity"], "stable")
        self.assertEqual(policies["tools.cards"], "stable")
        self.assertEqual(policies["mission.continuation"], "mission")
        self.assertEqual(policies["turn.current_user_message"], "turn")
        self.assertEqual(segments["system.identity"], "core")
        self.assertEqual(segments["tools.cards"], "tool_bundle")
        self.assertEqual(segments["mission.continuation"], "mission")
        self.assertEqual(segments["turn.current_user_message"], "turn")

    def test_messages_include_openai_compatible_roles(self) -> None:
        messages = PromptAssembler().assemble("What is next?").messages()

        roles = [message["role"] for message in messages]
        self.assertIn("system", roles)
        self.assertIn("developer", roles)
        self.assertIn("user", roles)
        self.assertEqual(messages[-1], {"role": "user", "content": "What is next?"})

    def test_metadata_shape_has_estimates_without_content(self) -> None:
        metadata = PromptAssembler().assemble(
            "Use provider key sk-test-secret?",
            mission={"brief": "Keep secrets out of metadata", "checkpoint": {"recent_summary": "secret mentioned"}},
        ).metadata()

        self.assertIn("blocks", metadata)
        self.assertIn("total_token_estimate", metadata)
        self.assertIn("dropped_blocks", metadata)
        self.assertGreater(metadata["total_token_estimate"], 0)

        first_block = metadata["blocks"][0]
        self.assertEqual(
            set(first_block),
            {
                "id",
                "role",
                "layer",
                "title",
                "source",
                "cache_policy",
                "cache_segment",
                "token_estimate",
                "priority",
                "can_drop",
            },
        )
        self.assertTrue(all("content" not in block for block in metadata["blocks"]))
        self.assertNotIn("sk-test-secret", str(metadata))

    def test_memory_and_skill_indexes_are_progressive_blocks(self) -> None:
        prompt = PromptAssembler().assemble(
            "Help with writing",
            tool_specs=[_tool("memory_search"), _tool("skill_view")],
            memory_cards=[
                {
                    "id": "mempg_1",
                    "type": "page",
                    "title": "preference",
                    "summary": "User prefers concise updates",
                    "confidence": 0.9,
                    "status": "active",
                }
            ],
            skill_cards=[
                {
                    "name": "writer",
                    "description": "Draft concise prose",
                    "status": "active",
                }
            ],
        )

        self.assertEqual(
            [block.id for block in prompt.blocks],
            [
                "system.identity",
                "developer.operating_principles",
                "tools.cards",
                "memory.index",
                "skills.index",
                "mission.continuation",
                "turn.current_user_message",
            ],
        )
        memory = next(block for block in prompt.blocks if block.id == "memory.index")
        skills = next(block for block in prompt.blocks if block.id == "skills.index")
        self.assertIn("memory_read", memory.content)
        self.assertIn("mempg_1", memory.content)
        self.assertIn("skill_view", skills.content)
        self.assertIn("writer", skills.content)
        self.assertEqual(memory.cache_policy, "turn")
        self.assertEqual(skills.cache_policy, "daily")


def _tool(name: str) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=f"Description for {name}",
        risk="read",
        input_schema={"type": "object", "properties": {}, "required": []},
    )


if __name__ == "__main__":
    unittest.main()
