from __future__ import annotations

import tempfile
import unittest


class ConnectivityTestTests(unittest.TestCase):
    def test_provider_test_reports_not_configured(self) -> None:
        from mnemo_memory import MemoryClient

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)
            result = client.test_provider()
            self.assertFalse(result["ok"])
            self.assertIn("not configured", result["error"])

    def test_embedding_test_reports_not_configured(self) -> None:
        from mnemo_memory import MemoryClient

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)
            result = client.test_embedding()
            self.assertFalse(result["ok"])
            self.assertIn("not configured", result["error"])

    def test_http_dispatch_test_endpoints(self) -> None:
        from mnemo_memory import MemoryClient
        from mnemo_memory.interfaces.web import dispatch_memory_api

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)
            provider = dispatch_memory_api(client, "test-provider", {})
            embedding = dispatch_memory_api(client, "test-embedding", {})
            self.assertEqual(provider["kind"], "memory_provider_test")
            self.assertFalse(provider["ok"])
            self.assertEqual(embedding["kind"], "memory_embedding_test")
            self.assertFalse(embedding["ok"])


if __name__ == "__main__":
    unittest.main()
