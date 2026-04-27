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
    from mnemo.core.settings import load_user_settings
    from mnemo.interfaces.web import WebServerConfig, build_http_server
    from mnemo.mcp import MnemoMcpServer, mcp_server_config
    from mnemo.runtime import ScheduleService
    from mnemo.sdk import MnemoClient, mnemo_core_api_schema

    _assert_not_source_import(Path(mnemo.__file__ or ""))
    _assert_not_source_import(Path(sys.modules[MnemoClient.__module__].__file__ or ""))
    _assert_not_source_import(Path(sys.modules[MnemoMcpServer.__module__].__file__ or ""))
    _assert_not_source_import(Path(sys.modules[ScheduleService.__module__].__file__ or ""))
    _assert_not_source_import(Path(sys.modules[WebServerConfig.__module__].__file__ or ""))
    if not callable(build_http_server):
        raise AssertionError("packaged web interface is missing HTTP server builder")

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

    schema = mnemo_core_api_schema()
    methods = schema.get("methods", {})
    if "context" not in methods or "capsule" not in methods or "external_run" not in methods:
        raise AssertionError("packaged SDK schema is missing context, capsule, or external_run method")
    if "schedule_dream" not in methods or not hasattr(MnemoClient, "schedule_dream"):
        raise AssertionError("packaged SDK schema is missing schedule_dream method")
    tool_names = {tool["name"] for tool in MnemoMcpServer().tools()}
    if "mnemo_context" not in tool_names or "mnemo_capsule" not in tool_names or "mnemo_external_run" not in tool_names:
        raise AssertionError("packaged MCP server is missing external runtime tools")
    packaged_mcp_config = mcp_server_config(state_dir=".mnemo")
    if packaged_mcp_config["server"]["args"] != ["mcp", "serve", "--state-dir", ".mnemo"]:
        raise AssertionError("packaged MCP config is not wired to mnemo mcp serve")
    if "mnemo_context" not in packaged_mcp_config["tool_names"] or "inputSchema" in str(packaged_mcp_config):
        raise AssertionError("packaged MCP config should expose compact tool names without raw schemas")
    if not hasattr(MnemoMcpServer(), "serve_content_length"):
        raise AssertionError("packaged MCP server is missing content-length serve transport")
    if "quiet_hours" not in load_user_settings(Path.cwd()):
        raise AssertionError("packaged settings loader is missing quiet-hours defaults")

    print(f"installed mnemo {version} smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
