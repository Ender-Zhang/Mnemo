from __future__ import annotations

import importlib
from pathlib import Path
import subprocess
import sys
import tomllib
import unittest


class PackageInstallSmokeTests(unittest.TestCase):
    def test_package_exports_memory_client_and_cli(self) -> None:
        module = importlib.import_module("mnemo_memory")
        self.assertTrue(hasattr(module, "MemoryClient"))
        self.assertIn("mnemo_memory", str(module.__file__))

        pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(pyproject["project"]["name"], "mnemo-memory")
        self.assertEqual(pyproject["project"]["scripts"]["mnemo-memory"], "mnemo_memory.interfaces.cli:main")
        self.assertNotIn("mnemo", pyproject["project"]["scripts"])
        package_data = pyproject["tool"]["setuptools"]["package-data"]["mnemo_memory"]
        self.assertIn("interfaces/web_assets/index.html", package_data)
        self.assertIn("interfaces/web_assets/assets/*", package_data)

        result = subprocess.run(
            [sys.executable, "-m", "mnemo_memory", "--version"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("mnemo-memory", result.stdout)


if __name__ == "__main__":
    unittest.main()
