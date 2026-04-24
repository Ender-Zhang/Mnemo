from __future__ import annotations

import importlib.metadata
import importlib.resources
import os
import subprocess
import sys
import sysconfig
from pathlib import Path


def _run(command: list[str]) -> str:
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    return completed.stdout.strip()


def _console_script(name: str) -> str:
    script = Path(sysconfig.get_path("scripts")).joinpath(name)
    if script.exists():
        return str(script)
    return name


def _assert_not_source_import(package_file: Path) -> None:
    repo_root = os.environ.get("MNEMO_REPO_ROOT")
    if not repo_root:
        return

    resolved_repo = Path(repo_root).resolve()
    resolved_file = package_file.resolve()
    try:
        resolved_file.relative_to(resolved_repo)
    except ValueError:
        return

    raise AssertionError(f"mnemo imported from source checkout: {resolved_file}")


def main() -> int:
    import mnemo

    _assert_not_source_import(Path(mnemo.__file__ or ""))

    version = importlib.metadata.version("mnemo")
    if version != mnemo.__version__:
        raise AssertionError(f"metadata version {version!r} != package version {mnemo.__version__!r}")

    console_version = _run([_console_script("mnemo"), "--version"])
    module_version = _run([sys.executable, "-m", "mnemo", "--version"])
    expected_version = f"mnemo {version}"
    if console_version != expected_version:
        raise AssertionError(f"console script returned {console_version!r}, expected {expected_version!r}")
    if module_version != expected_version:
        raise AssertionError(f"module entrypoint returned {module_version!r}, expected {expected_version!r}")

    assets = importlib.resources.files("mnemo.interfaces").joinpath("web_assets")
    required_assets = ["index.html", "app.css", "app.js"]
    missing_assets = [name for name in required_assets if not assets.joinpath(name).is_file()]
    if missing_assets:
        raise AssertionError(f"missing packaged web assets: {', '.join(missing_assets)}")

    print(f"installed mnemo {version} smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
