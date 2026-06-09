from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch
import unittest


class ProviderConfigTests(unittest.TestCase):
    def test_resolve_memory_config_reads_explicit_env_file(self) -> None:
        from mnemo_memory.core.config import ConfigOverrides, resolve_memory_config

        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text(
                "\n".join(
                    [
                        "MNEMO_MEMORY_BASE_URL=http://env-file.example/v1",
                        "MNEMO_MEMORY_MODEL=env-file-model",
                        "MNEMO_MEMORY_API_KEY=env-file-key",
                        "MNEMO_MEMORY_THINKING_ENABLED=true",
                    ]
                ),
                encoding="utf-8",
            )

            config = resolve_memory_config(
                ConfigOverrides(state_dir=tmp),
                env={"MNEMO_MEMORY_ENV_FILE": str(env_file), "MNEMO_MEMORY_MODEL": "process-env-model"},
            )

            self.assertEqual(config.base_url, "http://env-file.example/v1")
            self.assertEqual(config.model, "process-env-model")
            self.assertEqual(config.api_key, "env-file-key")
            self.assertTrue(config.thinking_enabled)

    def test_resolve_memory_config_reads_default_dotenv_from_current_directory(self) -> None:
        from mnemo_memory.core.config import ConfigOverrides, resolve_memory_config

        original_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "state"
            state_dir.mkdir()
            Path(tmp, ".env").write_text(
                "MNEMO_MEMORY_BASE_URL=http://default-dotenv.example/v1\nMNEMO_MEMORY_MODEL=default-dotenv-model\n",
                encoding="utf-8",
            )
            try:
                os.chdir(tmp)
                with patch.dict(os.environ, {}, clear=True):
                    config = resolve_memory_config(ConfigOverrides(state_dir=str(state_dir)))
            finally:
                os.chdir(original_cwd)

            self.assertEqual(config.base_url, "http://default-dotenv.example/v1")
            self.assertEqual(config.model, "default-dotenv-model")

    def test_state_config_overrides_env_file_for_webui_saved_provider(self) -> None:
        from mnemo_memory.core.config import ConfigOverrides, resolve_memory_config

        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "state"
            state_dir.mkdir()
            env_file = Path(tmp) / ".env"
            env_file.write_text("MNEMO_MEMORY_BASE_URL=http://env-file.example/v1\n", encoding="utf-8")
            (state_dir / "config.json").write_text(
                json.dumps({"base_url": "http://saved.example/v1", "model": "saved-model"}),
                encoding="utf-8",
            )

            config = resolve_memory_config(
                ConfigOverrides(state_dir=str(state_dir)),
                env={"MNEMO_MEMORY_ENV_FILE": str(env_file)},
            )

            self.assertEqual(config.base_url, "http://saved.example/v1")
            self.assertEqual(config.model, "saved-model")

    def test_client_saves_provider_config_and_redacts_secrets(self) -> None:
        from mnemo_memory import MemoryClient

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)

            saved = client.save_provider_config(
                provider="openai-compatible",
                base_url="http://localhost:8000/v1",
                model="memory-maintainer",
                api_key="secret-key",
                api_key_env="",
                timeout_s=12,
                thinking_enabled=True,
            )

            self.assertEqual(saved["kind"], "memory_provider_config")
            self.assertTrue(saved["configured"])
            self.assertTrue(saved["api_key_configured"])
            self.assertEqual(saved["config"]["base_url"], "http://localhost:8000/v1")
            self.assertEqual(saved["config"]["api_key"], "***")
            self.assertTrue(saved["config"]["thinking_enabled"])

            raw = json.loads((Path(tmp) / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(raw["api_key"], "secret-key")
            self.assertTrue(raw["thinking_enabled"])

            updated = client.save_provider_config(
                base_url="http://localhost:9000/v1",
                model="memory-maintainer-v2",
                api_key="",
                thinking_enabled=False,
            )
            raw_after_blank_key = json.loads((Path(tmp) / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(raw_after_blank_key["api_key"], "secret-key")
            self.assertFalse(raw_after_blank_key["thinking_enabled"])
            self.assertEqual(updated["config"]["base_url"], "http://localhost:9000/v1")
            self.assertEqual(updated["config"]["api_key"], "***")
            self.assertFalse(updated["config"]["thinking_enabled"])

    def test_http_dispatch_reads_and_saves_provider_config(self) -> None:
        from mnemo_memory import MemoryClient
        from mnemo_memory.interfaces.web import dispatch_memory_api

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)

            saved = dispatch_memory_api(
                client,
                "save-provider-config",
                {
                    "base_url": "http://localhost:8000/v1",
                    "model": "memory-maintainer",
                    "api_key": "secret-key",
                    "thinking_enabled": True,
                },
            )
            loaded = dispatch_memory_api(client, "provider-config", {})

            self.assertEqual(saved["config"]["api_key"], "***")
            self.assertTrue(saved["config"]["thinking_enabled"])
            self.assertEqual(loaded["config"]["base_url"], "http://localhost:8000/v1")
            self.assertEqual(loaded["config"]["api_key"], "***")
            self.assertTrue(loaded["config"]["thinking_enabled"])

    def test_openai_provider_adds_thinking_payload_when_enabled(self) -> None:
        from mnemo_memory.core.config import MemoryConfig
        from mnemo_memory.providers.openai import OpenAICompatibleMemoryMaintainer

        class CapturingMaintainer(OpenAICompatibleMemoryMaintainer):
            def _post_json(self, path, payload):
                self.last_payload = payload
                return {"choices": [{"message": {"content": '{"actions": []}'}}]}

        enabled = CapturingMaintainer(
            MemoryConfig(
                base_url="http://provider.example/v1",
                model="memory-maintainer",
                thinking_enabled=True,
            )
        )
        self.assertEqual(enabled.propose_actions(delta={}, plan={}), [])
        self.assertEqual(enabled.last_payload["thinking"], {"type": "enabled"})

        disabled = CapturingMaintainer(
            MemoryConfig(
                base_url="http://provider.example/v1",
                model="memory-maintainer",
                thinking_enabled=False,
            )
        )
        self.assertEqual(disabled.propose_actions(delta={}, plan={}), [])
        self.assertNotIn("thinking", disabled.last_payload)

    def test_openai_provider_parses_actions_from_reasoning_fallback(self) -> None:
        from mnemo_memory.core.config import MemoryConfig
        from mnemo_memory.providers.openai import OpenAICompatibleMemoryMaintainer

        class ReasoningMaintainer(OpenAICompatibleMemoryMaintainer):
            def _post_json(self, path, payload):
                return {
                    "choices": [
                        {
                            "message": {
                                "content": "",
                                "reasoning": (
                                    "model thinking omitted. "
                                    '{"actions": [{"tool": "memory_reject_candidate", "candidate_id": "memcand_1", "reason": "low_value"}]}'
                                ),
                            }
                        }
                    ]
                }

        maintainer = ReasoningMaintainer(
            MemoryConfig(
                base_url="http://provider.example/v1",
                model="memory-maintainer",
                thinking_enabled=True,
            )
        )

        actions = maintainer.propose_actions(delta={}, plan={})

        self.assertEqual(actions[0]["tool"], "memory_reject_candidate")
        self.assertEqual(actions[0]["reason"], "low_value")

    def test_openai_provider_parses_event_memory_from_reasoning_content_fallback(self) -> None:
        from mnemo_memory.core.config import MemoryConfig
        from mnemo_memory.providers.openai import OpenAICompatibleMemoryMaintainer

        class ReasoningContentMaintainer(OpenAICompatibleMemoryMaintainer):
            def _post_json(self, path, payload):
                return {
                    "choices": [
                        {
                            "message": {
                                "reasoning_content": (
                                    "```json\n"
                                    '{"facts": [{"claim": "User prefers concise updates.", "dimension": "preferences"}], "observations": []}'
                                    "\n```"
                                )
                            }
                        }
                    ]
                }

        maintainer = ReasoningContentMaintainer(
            MemoryConfig(
                base_url="http://provider.example/v1",
                model="memory-maintainer",
                thinking_enabled=True,
            )
        )

        result = maintainer.extract_event_memory(event={"text": "x"}, context=[])

        self.assertEqual(result["facts"][0]["claim"], "User prefers concise updates.")

    def test_public_schema_exposes_provider_config_methods(self) -> None:
        from mnemo_memory.sdk import memory_api_schema

        schema = memory_api_schema()

        self.assertEqual(schema["methods"]["provider_config"]["side_effects"], "read_only")
        self.assertEqual(schema["methods"]["save_provider_config"]["side_effects"], "writes_provider_config")


if __name__ == "__main__":
    unittest.main()
