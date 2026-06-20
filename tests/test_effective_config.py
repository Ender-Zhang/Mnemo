from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class EffectiveConfigTests(unittest.TestCase):
    def test_reports_value_and_source_per_field(self) -> None:
        from mnemo_memory import MemoryClient

        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "MNEMO_MEMORY_ENV_FILE": str(Path(tmp) / "missing.env"),
                "MNEMO_MEMORY_MODEL": "env-model",
            }
            with patch.dict(os.environ, env, clear=True):
                client = MemoryClient(state_dir=tmp)
                client.save_provider_config(base_url="http://example.local/v1")

                effective = client.effective_config()
                rows = {row["field"]: row for row in effective["rows"]}

                self.assertEqual(rows["base_url"]["source"], "config.json")
                self.assertEqual(rows["base_url"]["value"], "http://example.local/v1")
                self.assertEqual(rows["model"]["source"], "env / .env")
                self.assertEqual(rows["model"]["value"], "env-model")
                self.assertEqual(rows["provider"]["source"], "default")
                self.assertEqual(rows["api_key"]["value"], "未设置")
                self.assertIn("config.json", effective["config_path"])


if __name__ == "__main__":
    unittest.main()
