from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import shlex
import shutil
import signal
import subprocess
import sys
from typing import Any, Iterable

from ..core.errors import MnemoError


SERVICE_NAME = "mnemo-web"
LAUNCHD_LABEL = "io.mnemo.web"
SYSTEMD_UNIT = "mnemo-web.service"
_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class WebServiceConfig:
    state_dir: str
    host: str = "127.0.0.1"
    port: int = 8765
    workspace_root: str | None = None
    command: tuple[str, ...] = ()


@dataclass(frozen=True)
class WebServicePaths:
    state_dir: Path
    service_dir: Path
    env_file: Path
    meta_file: Path
    launcher: Path
    pid_file: Path
    stdout_log: Path
    stderr_log: Path
    feishu_stdout_log: Path
    feishu_stderr_log: Path
    launchd_plist: Path
    systemd_unit: Path


def web_service_paths(state_dir: str | Path) -> WebServicePaths:
    state = _service_path(state_dir)
    service_dir = state / "service"
    logs_dir = state / "logs"
    home = Path.home()
    return WebServicePaths(
        state_dir=state,
        service_dir=service_dir,
        env_file=service_dir / "mnemo-web.env",
        meta_file=service_dir / "mnemo-web.json",
        launcher=service_dir / "mnemo-web.sh",
        pid_file=service_dir / "mnemo-web.pid",
        stdout_log=logs_dir / "mnemo-web.log",
        stderr_log=logs_dir / "mnemo-web.error.log",
        feishu_stdout_log=logs_dir / "mnemo-feishu.log",
        feishu_stderr_log=logs_dir / "mnemo-feishu.error.log",
        launchd_plist=home / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist",
        systemd_unit=home / ".config" / "systemd" / "user" / SYSTEMD_UNIT,
    )


def build_web_service_command(
    *,
    state_dir: str | Path,
    host: str = "127.0.0.1",
    port: int = 8765,
    workspace_root: str | Path | None = None,
    python_executable: str | None = None,
) -> tuple[str, ...]:
    command = [
        python_executable or sys.executable,
        "-m",
        "mnemo",
        "web",
        "--state-dir",
        str(_service_path(state_dir)),
        "--host",
        str(host),
        "--port",
        str(port),
    ]
    if workspace_root:
        command.extend(["--workspace-root", str(_service_path(workspace_root))])
    return tuple(command)


def _service_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def save_service_env(state_dir: str | Path, values: dict[str, str | None]) -> dict[str, Any]:
    paths = web_service_paths(state_dir)
    existing = load_service_env(state_dir)
    for key, value in values.items():
        key = str(key or "").strip()
        if not _ENV_KEY_RE.match(key):
            raise MnemoError(f"invalid service env var name: {key}")
        if value is None or value == "":
            existing.pop(key, None)
        else:
            existing[key] = str(value)
    paths.service_dir.mkdir(parents=True, exist_ok=True)
    _write_secret_env(paths.env_file, existing)
    return _service_env_summary(paths, existing)


def load_service_env(state_dir: str | Path) -> dict[str, str]:
    path = web_service_paths(state_dir).env_file
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    env: dict[str, str] = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        try:
            parts = shlex.split(line, posix=True)
        except ValueError:
            continue
        if not parts or "=" not in parts[0]:
            continue
        key, value = parts[0].split("=", 1)
        if _ENV_KEY_RE.match(key):
            env[key] = value
    return env


def install_web_service(config: WebServiceConfig, *, mode: str = "auto", dry_run: bool = False) -> dict[str, Any]:
    paths = _prepare_service_files(config)
    manager = _select_manager(mode)
    if dry_run:
        return _service_result("install", manager, paths, running=False, skipped=True)
    try:
        if manager == "launchd":
            _install_launchd(paths)
        elif manager == "systemd":
            _install_systemd(paths)
        elif manager == "detached":
            _start_detached(paths)
        else:
            raise MnemoError(f"unsupported service mode: {mode}")
        return service_status(config.state_dir)
    except MnemoError as exc:
        if str(mode or "auto").strip().lower() != "auto" or manager == "detached":
            raise
        _start_detached(paths)
        result = service_status(config.state_dir)
        result["fallback_reason"] = str(exc)
        return result


def start_web_service(config: WebServiceConfig, *, mode: str = "auto", dry_run: bool = False) -> dict[str, Any]:
    paths = _prepare_service_files(config)
    manager = _select_manager(mode)
    if dry_run:
        return _service_result("start", manager, paths, running=False, skipped=True)
    try:
        if manager == "launchd":
            if not paths.launchd_plist.exists():
                _write_launchd_plist(paths)
            _run(["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{LAUNCHD_LABEL}"], check=True)
        elif manager == "systemd":
            if not paths.systemd_unit.exists():
                _write_systemd_unit(paths)
                _run(["systemctl", "--user", "daemon-reload"], check=False)
            _run(["systemctl", "--user", "start", SYSTEMD_UNIT], check=True)
        elif manager == "detached":
            _start_detached(paths)
        else:
            raise MnemoError(f"unsupported service mode: {mode}")
        return service_status(config.state_dir)
    except MnemoError as exc:
        if str(mode or "auto").strip().lower() != "auto" or manager == "detached":
            raise
        _start_detached(paths)
        result = service_status(config.state_dir)
        result["fallback_reason"] = str(exc)
        return result


def stop_web_service(state_dir: str | Path, *, mode: str = "auto", dry_run: bool = False) -> dict[str, Any]:
    paths = web_service_paths(state_dir)
    manager = _installed_manager(paths) or _select_manager(mode)
    if dry_run:
        return _service_result("stop", manager, paths, running=False, skipped=True)
    if manager == "launchd" and paths.launchd_plist.exists():
        _run(["launchctl", "bootout", f"gui/{os.getuid()}", str(paths.launchd_plist)], check=False)
    elif manager == "systemd" and paths.systemd_unit.exists():
        _run(["systemctl", "--user", "stop", SYSTEMD_UNIT], check=False)
    _stop_detached(paths)
    return service_status(state_dir)


def restart_web_service(config: WebServiceConfig, *, mode: str = "auto", dry_run: bool = False) -> dict[str, Any]:
    if dry_run:
        paths = _prepare_service_files(config)
        return _service_result("restart", _select_manager(mode), paths, running=False, skipped=True)
    stop_web_service(config.state_dir, mode=mode)
    return install_web_service(config, mode=mode)


def service_status(state_dir: str | Path) -> dict[str, Any]:
    paths = web_service_paths(state_dir)
    manager = _installed_manager(paths) or "none"
    running = False
    pid: int | None = None
    if paths.launchd_plist.exists() and shutil.which("launchctl"):
        running, pid = _launchd_running()
        if running:
            manager = "launchd"
    if not running and paths.systemd_unit.exists() and shutil.which("systemctl"):
        running = _systemd_running()
        manager = "systemd"
    if not running:
        detached_pid = _detached_pid(paths)
        if detached_pid:
            running = True
            pid = detached_pid
            manager = "detached"
    return _service_result("status", manager, paths, running=running, pid=pid)


def _prepare_service_files(config: WebServiceConfig) -> WebServicePaths:
    paths = web_service_paths(config.state_dir)
    paths.service_dir.mkdir(parents=True, exist_ok=True)
    paths.stdout_log.parent.mkdir(parents=True, exist_ok=True)
    if not paths.env_file.exists():
        _write_secret_env(paths.env_file, {})
    command = _resolved_command(config)
    sidecars = _service_sidecars(config, command)
    _write_launcher(paths, command, sidecars)
    paths.meta_file.write_text(
        json.dumps(
            {
                "host": config.host,
                "port": int(config.port),
                "workspace_root": config.workspace_root or "",
                "command": list(command),
                "sidecars": [
                    {
                        "name": sidecar["name"],
                        "command": list(sidecar["command"]),
                        "logs": sidecar["logs"],
                    }
                    for sidecar in sidecars
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return paths


def _resolved_command(config: WebServiceConfig) -> tuple[str, ...]:
    if config.command:
        return config.command
    return build_web_service_command(
        state_dir=config.state_dir,
        host=config.host,
        port=config.port,
        workspace_root=config.workspace_root,
    )


def _service_sidecars(config: WebServiceConfig, primary_command: tuple[str, ...]) -> list[dict[str, Any]]:
    sidecars: list[dict[str, Any]] = []
    feishu = _feishu_sidecar(config, primary_command)
    if feishu:
        sidecars.append(feishu)
    return sidecars


def _feishu_sidecar(config: WebServiceConfig, primary_command: tuple[str, ...]) -> dict[str, Any] | None:
    from ..channels.feishu import load_feishu_saved_config
    from ..core.settings import load_user_settings

    saved = load_feishu_saved_config(config.state_dir)
    if not saved.get("app_id") or not saved.get("app_secret"):
        return None
    if str(saved.get("connection") or "").strip().lower() != "websocket":
        return None

    runtime = load_user_settings(config.state_dir).get("runtime", {})
    runtime = runtime if isinstance(runtime, dict) else {}
    python_executable = primary_command[0] if primary_command else sys.executable
    command = [
        python_executable,
        "-m",
        "mnemo",
        "channels",
        "feishu",
        "serve",
        "--state-dir",
        str(_service_path(config.state_dir)),
        "--connection",
        "websocket",
    ]
    if config.workspace_root:
        command.extend(["--workspace-root", str(_service_path(config.workspace_root))])
    command.append("--streaming" if bool(saved.get("streaming", True)) else "--no-streaming")
    _append_runtime_args(command, runtime)
    paths = web_service_paths(config.state_dir)
    return {
        "name": "feishu",
        "command": tuple(command),
        "logs": {"stdout": str(paths.feishu_stdout_log), "stderr": str(paths.feishu_stderr_log)},
    }


def _append_runtime_args(command: list[str], runtime: dict[str, Any]) -> None:
    provider = str(runtime.get("provider") or "").strip()
    if provider:
        command.extend(["--provider", provider])
    for field, flag in (
        ("base_url", "--base-url"),
        ("model", "--model"),
        ("api_key_env", "--api-key-env"),
    ):
        value = str(runtime.get(field) or "").strip()
        if value:
            command.extend([flag, value])
    for field, flag in (
        ("timeout_s", "--timeout-s"),
        ("retry_count", "--retry-count"),
        ("retry_backoff_s", "--retry-backoff-s"),
        ("max_tool_rounds", "--max-tool-rounds"),
    ):
        value = runtime.get(field)
        if value is not None and value != "":
            command.extend([flag, str(value)])


def _write_secret_env(path: Path, env: dict[str, str]) -> None:
    lines = ["# Mnemo service-only environment. Do not commit this file."]
    for key in sorted(env):
        lines.append(f"export {key}={shlex.quote(env[key])}")
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(tmp_path, 0o600)
    os.replace(tmp_path, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _write_launcher(paths: WebServicePaths, command: Iterable[str], sidecars: list[dict[str, Any]]) -> None:
    header = (
        "#!/usr/bin/env sh\n"
        "set -eu\n"
        f"mkdir -p {shlex.quote(str(paths.stdout_log.parent))}\n"
        f"if [ -f {shlex.quote(str(paths.env_file))} ]; then\n"
        f"  . {shlex.quote(str(paths.env_file))}\n"
        "fi\n"
        f"export MNEMO_STATE_DIR={shlex.quote(str(paths.state_dir))}\n"
    )
    if not sidecars:
        command_text = " ".join(shlex.quote(part) for part in command)
        body = header + f"exec {command_text}\n"
    else:
        body = _python_supervisor_body(paths, command, sidecars)
    tmp_path = paths.launcher.with_name(f"{paths.launcher.name}.tmp")
    tmp_path.write_text(body, encoding="utf-8")
    os.chmod(tmp_path, 0o700)
    os.replace(tmp_path, paths.launcher)
    try:
        os.chmod(paths.launcher, 0o700)
    except OSError:
        pass


def _python_supervisor_body(paths: WebServicePaths, command: Iterable[str], sidecars: list[dict[str, Any]]) -> str:
    primary_command = list(command)
    commands = [
        {
            "name": "web",
            "command": primary_command,
            "stdout": str(paths.stdout_log),
            "stderr": str(paths.stderr_log),
        }
    ]
    for sidecar in sidecars:
        commands.append(
            {
                "name": str(sidecar["name"]),
                "command": list(sidecar["command"]),
                "stdout": str(sidecar["logs"]["stdout"]),
                "stderr": str(sidecar["logs"]["stderr"]),
            }
        )
    shebang = str(primary_command[0] if primary_command else sys.executable)
    payload = json.dumps(commands, ensure_ascii=False)
    state_dir = json.dumps(str(paths.state_dir), ensure_ascii=False)
    env_file = json.dumps(str(paths.env_file), ensure_ascii=False)
    logs_dir = json.dumps(str(paths.stdout_log.parent), ensure_ascii=False)
    return f"""#!{shebang}
import os
import shlex
import signal
import subprocess
import sys
import time

COMMANDS = {payload}
STATE_DIR = {state_dir}
ENV_FILE = {env_file}
LOGS_DIR = {logs_dir}


def _load_env(path):
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if not key or not key.replace("_", "").isalnum() or key[0].isdigit():
                continue
            try:
                parts = shlex.split(value, posix=True)
            except ValueError:
                parts = [value.strip("'\\\"")]
            os.environ[key] = parts[0] if parts else ""


def _open_log(path):
    return open(path, "ab", buffering=0)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--mnemo-supervisor-check":
        return 0
    os.makedirs(LOGS_DIR, exist_ok=True)
    _load_env(ENV_FILE)
    os.environ["MNEMO_STATE_DIR"] = STATE_DIR
    children = []
    log_handles = []

    def cleanup():
        for process, _name in children:
            if process.poll() is None:
                process.terminate()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and any(process.poll() is None for process, _name in children):
            time.sleep(0.2)
        for process, _name in children:
            if process.poll() is None:
                process.kill()
        for process, _name in children:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for handle in log_handles:
            handle.close()

    def handle_signal(_signum, _frame):
        cleanup()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        for item in COMMANDS:
            stdout = _open_log(item["stdout"])
            stderr = _open_log(item["stderr"])
            log_handles.extend([stdout, stderr])
            process = subprocess.Popen(item["command"], stdout=stdout, stderr=stderr)
            children.append((process, item["name"]))
        while True:
            for process, _name in children:
                code = process.poll()
                if code is not None:
                    cleanup()
                    return code if code >= 0 else 128 - code
            time.sleep(1)
    except BaseException:
        cleanup()
        raise


if __name__ == "__main__":
    raise SystemExit(main())
"""


def _write_launchd_plist(paths: WebServicePaths) -> None:
    paths.launchd_plist.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "Label": LAUNCHD_LABEL,
        "ProgramArguments": ["/bin/sh", str(paths.launcher)],
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(paths.stdout_log),
        "StandardErrorPath": str(paths.stderr_log),
    }
    with paths.launchd_plist.open("wb") as handle:
        plistlib.dump(payload, handle)


def _write_systemd_unit(paths: WebServicePaths) -> None:
    paths.systemd_unit.parent.mkdir(parents=True, exist_ok=True)
    unit = (
        "[Unit]\n"
        "Description=Mnemo web service\n"
        "After=default.target\n\n"
        "[Service]\n"
        "Type=simple\n"
        f"ExecStart=/bin/sh {shlex.quote(str(paths.launcher))}\n"
        "Restart=always\n"
        "RestartSec=3\n"
        f"StandardOutput=append:{paths.stdout_log}\n"
        f"StandardError=append:{paths.stderr_log}\n\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )
    paths.systemd_unit.write_text(unit, encoding="utf-8")


def _install_launchd(paths: WebServicePaths) -> None:
    if not shutil.which("launchctl"):
        raise MnemoError("launchctl not found; use --mode detached")
    _write_launchd_plist(paths)
    _run(["launchctl", "bootout", f"gui/{os.getuid()}", str(paths.launchd_plist)], check=False)
    _run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(paths.launchd_plist)], check=True)
    _run(["launchctl", "enable", f"gui/{os.getuid()}/{LAUNCHD_LABEL}"], check=False)
    _run(["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{LAUNCHD_LABEL}"], check=False)


def _install_systemd(paths: WebServicePaths) -> None:
    if not shutil.which("systemctl"):
        raise MnemoError("systemctl not found; use --mode detached")
    _write_systemd_unit(paths)
    _run(["systemctl", "--user", "daemon-reload"], check=True)
    _run(["systemctl", "--user", "enable", "--now", SYSTEMD_UNIT], check=True)


def _start_detached(paths: WebServicePaths) -> None:
    old_pid = _detached_pid(paths)
    if old_pid:
        return
    stdout = paths.stdout_log.open("ab")
    stderr = paths.stderr_log.open("ab")
    try:
        proc = subprocess.Popen(
            ["/bin/sh", str(paths.launcher)],
            stdout=stdout,
            stderr=stderr,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    finally:
        stdout.close()
        stderr.close()
    paths.pid_file.write_text(str(proc.pid), encoding="ascii")


def _stop_detached(paths: WebServicePaths) -> None:
    pid = _detached_pid(paths)
    if not pid:
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except OSError:
        return
    try:
        paths.pid_file.unlink()
    except OSError:
        pass


def _detached_pid(paths: WebServicePaths) -> int | None:
    try:
        pid = int(paths.pid_file.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None
    if pid <= 1:
        return None
    try:
        os.kill(pid, 0)
    except OSError:
        return None
    if not _pid_looks_like_mnemo_web(pid):
        try:
            paths.pid_file.unlink()
        except OSError:
            pass
        return None
    return pid


def _pid_looks_like_mnemo_web(pid: int) -> bool:
    try:
        result = subprocess.run(
            ["ps", "-o", "command=", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return True
    command = result.stdout.strip()
    if not command:
        return False
    return ("mnemo" in command and "web" in command) or "mnemo-web.sh" in command


def _select_manager(mode: str) -> str:
    normalized = str(mode or "auto").strip().lower()
    if normalized in {"launchd", "systemd", "detached"}:
        return normalized
    if normalized != "auto":
        raise MnemoError(f"unsupported service mode: {mode}")
    system = platform.system()
    if system == "Darwin" and shutil.which("launchctl"):
        return "launchd"
    if system == "Linux" and shutil.which("systemctl"):
        return "systemd"
    return "detached"


def _installed_manager(paths: WebServicePaths) -> str | None:
    if paths.launchd_plist.exists():
        return "launchd"
    if paths.systemd_unit.exists():
        return "systemd"
    if paths.pid_file.exists():
        return "detached"
    return None


def _launchd_running() -> tuple[bool, int | None]:
    try:
        result = _run(["launchctl", "list", LAUNCHD_LABEL], check=False)
    except OSError:
        return False, None
    if result.returncode != 0:
        return False, None
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[2] == LAUNCHD_LABEL:
            try:
                return True, int(parts[0])
            except ValueError:
                return True, None
    return True, None


def _systemd_running() -> bool:
    try:
        result = _run(["systemctl", "--user", "is-active", SYSTEMD_UNIT], check=False)
    except OSError:
        return False
    return result.stdout.strip() == "active"


def _run(args: list[str], *, check: bool) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(args, capture_output=True, text=True, check=False, timeout=30)
    except subprocess.TimeoutExpired as exc:
        raise MnemoError(f"service command timed out: {' '.join(args)}") from exc
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or f"exit {result.returncode}").strip()
        raise MnemoError(f"service command failed: {' '.join(args)}: {detail}")
    return result


def _service_result(
    action: str,
    manager: str,
    paths: WebServicePaths,
    *,
    running: bool,
    skipped: bool = False,
    pid: int | None = None,
) -> dict[str, Any]:
    host, port = _service_endpoint(paths)
    return {
        "action": action,
        "manager": manager,
        "installed": paths.launchd_plist.exists() or paths.systemd_unit.exists() or paths.launcher.exists(),
        "running": running,
        "pid": pid,
        "state_dir": str(paths.state_dir),
        "url": f"http://{host}:{port}",
        "launcher": str(paths.launcher),
        "env_file": str(paths.env_file),
        "logs": {"stdout": str(paths.stdout_log), "stderr": str(paths.stderr_log)},
        "sidecars": _service_sidecar_status(paths),
        "skipped": skipped,
    }


def _service_endpoint(paths: WebServicePaths) -> tuple[str, int]:
    try:
        parsed = json.loads(paths.meta_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "127.0.0.1", 8765
    host = str(parsed.get("host") or "127.0.0.1").strip() or "127.0.0.1"
    try:
        port = int(parsed.get("port") or 8765)
    except (TypeError, ValueError):
        port = 8765
    return host, port


def _service_env_summary(paths: WebServicePaths, env: dict[str, str]) -> dict[str, Any]:
    return {
        "path": str(paths.env_file),
        "keys": sorted(env),
        "exists": paths.env_file.exists(),
    }


def _service_sidecar_status(paths: WebServicePaths) -> list[dict[str, Any]]:
    try:
        parsed = json.loads(paths.meta_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    sidecars = parsed.get("sidecars") if isinstance(parsed, dict) else None
    if not isinstance(sidecars, list):
        return []
    result: list[dict[str, Any]] = []
    for sidecar in sidecars:
        if not isinstance(sidecar, dict):
            continue
        logs = sidecar.get("logs") if isinstance(sidecar.get("logs"), dict) else {}
        result.append(
            {
                "name": str(sidecar.get("name") or ""),
                "logs": {
                    "stdout": str(logs.get("stdout") or ""),
                    "stderr": str(logs.get("stderr") or ""),
                },
            }
        )
    return result
