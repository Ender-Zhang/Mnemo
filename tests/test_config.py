from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from mnemo.core.config import ConfigOverrides, resolve_runtime_config


class RuntimeConfigTests(unittest.TestCase):
    def test_cli_overrides_env_and_config_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "provider": "local",
                        "base_url": "http://from-file",
                        "model": "file-model",
                        "timeout_s": 10,
                    }
                ),
                encoding="utf-8",
            )

            config = resolve_runtime_config(
                ConfigOverrides(
                    provider="openai-compatible",
                    model="cli-model",
                    config_path=str(config_path),
                ),
                env={
                    "MNEMO_BASE_URL": "http://from-env",
                    "MNEMO_MODEL": "env-model",
                    "MNEMO_TIMEOUT_S": "12",
                },
            )

            self.assertEqual(config.provider, "openai-compatible")
            self.assertEqual(config.base_url, "http://from-env")
            self.assertEqual(config.model, "cli-model")
            self.assertEqual(config.timeout_s, 12.0)

    def test_api_key_resolves_from_env_and_redacts(self) -> None:
        config = resolve_runtime_config(
            ConfigOverrides(api_key_env="MNEMO_TEST_KEY"),
            env={"MNEMO_TEST_KEY": "secret-value"},
        )

        self.assertEqual(config.api_key, "secret-value")
        self.assertEqual(config.redacted()["api_key"], "***")
        self.assertNotIn("secret-value", str(config.redacted()))


if __name__ == "__main__":
    unittest.main()
