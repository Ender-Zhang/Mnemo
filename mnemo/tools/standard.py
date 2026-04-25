from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import subprocess
from typing import TYPE_CHECKING, Any
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from ..core.errors import NotFoundError, ToolError
from ..core.models import ToolResult, ToolSpec
from ..core.text_patch import apply_exact_replacements, normalize_text_replacements, optional_bool

if TYPE_CHECKING:
    from .registry import ToolContext


ToolHandler = Callable[[dict[str, Any], "ToolContext"], dict[str, Any]]


def _schema(required: list[str], properties: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "object",
        "required": required,
        "properties": properties,
        "additionalProperties": False,
    }


STANDARD_TOOL_SPECS = [
    ToolSpec(
        name="file_search",
        description="Search text files under the workspace root by path or line content.",
        risk="read",
        input_schema=_schema(
            ["query"],
            {
                "query": {"type": "string"},
                "root": {"type": "string", "default": "."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
            },
        ),
    ),
    ToolSpec(
        name="file_read",
        description="Read a UTF-8 text file under the workspace root.",
        risk="read",
        input_schema=_schema(
            ["path"],
            {
                "path": {"type": "string"},
                "max_bytes": {"type": "integer", "minimum": 1, "maximum": 200000, "default": 20000},
            },
        ),
    ),
    ToolSpec(
        name="file_write",
        description="Create, overwrite, or append a text file under the workspace root. Requires admin policy.",
        risk="admin",
        input_schema=_schema(
            ["path", "content"],
            {
                "path": {"type": "string"},
                "content": {"type": "string"},
                "mode": {"type": "string", "enum": ["create", "overwrite", "append"], "default": "create"},
            },
        ),
    ),
    ToolSpec(
        name="file_patch",
        description="Apply exact text replacements to a UTF-8 file under the workspace root. Requires admin policy.",
        risk="admin",
        input_schema=_schema(
            ["path", "replacements"],
            {
                "path": {"type": "string"},
                "replacements": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "required": ["old", "new"],
                        "properties": {
                            "old": {"type": "string"},
                            "new": {"type": "string"},
                        },
                        "additionalProperties": False,
                    },
                },
                "replace_all": {"type": "boolean", "default": False},
            },
        ),
    ),
    ToolSpec(
        name="web_fetch",
        description="Fetch an HTTP or HTTPS URL. Requires external policy.",
        risk="external",
        input_schema=_schema(
            ["url"],
            {
                "url": {"type": "string"},
                "timeout_s": {"type": "number", "minimum": 0.1, "maximum": 30, "default": 10},
                "max_bytes": {"type": "integer", "minimum": 1, "maximum": 200000, "default": 60000},
            },
        ),
    ),
    ToolSpec(
        name="shell_exec",
        description="Run a command as an argv array in the workspace. Requires admin policy.",
        risk="admin",
        input_schema=_schema(
            ["command"],
            {
                "command": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                "cwd": {"type": "string", "default": "."},
                "timeout_s": {"type": "number", "minimum": 0.1, "maximum": 60, "default": 10},
                "max_output_bytes": {"type": "integer", "minimum": 1, "maximum": 100000, "default": 20000},
            },
        ),
    ),
]


def standard_tool_handlers() -> dict[str, ToolHandler]:
    return {
        "file_search": file_search,
        "file_read": file_read,
        "file_write": file_write,
        "file_patch": file_patch,
        "web_fetch": web_fetch,
        "shell_exec": shell_exec,
    }


def file_search(args: dict[str, Any], context: "ToolContext") -> dict[str, Any]:
    query = _require_str(args, "query").casefold()
    root = _resolve_workspace_path(context.workspace_root, str(args.get("root") or "."))
    limit = _bounded_int(args.get("limit", 20), minimum=1, maximum=100)
    matches: list[dict[str, Any]] = []
    scanned = 0
    for path in _iter_search_files(root, context.workspace_root):
        scanned += 1
        rel_path = _relative_path(path, context.workspace_root)
        path_matched = query in rel_path.casefold()
        try:
            content = _read_text_prefix(path, 200000)
        except ToolError:
            continue
        if path_matched:
            matches.append({"path": rel_path, "line": None, "text": "path match"})
            if len(matches) >= limit:
                return {"matches": matches, "scanned_files": scanned, "truncated": True}
        for line_number, line in enumerate(content.splitlines(), start=1):
            if query in line.casefold():
                matches.append({"path": rel_path, "line": line_number, "text": line[:240]})
            if len(matches) >= limit:
                return {"matches": matches, "scanned_files": scanned, "truncated": True}
        if len(matches) >= limit:
            return {"matches": matches, "scanned_files": scanned, "truncated": True}
    return {"matches": matches, "scanned_files": scanned, "truncated": False}


def file_read(args: dict[str, Any], context: "ToolContext") -> dict[str, Any]:
    path = _resolve_workspace_path(context.workspace_root, _require_str(args, "path"))
    if not path.is_file():
        raise NotFoundError(f"file not found: {_relative_path(path, context.workspace_root)}")
    max_bytes = _bounded_int(args.get("max_bytes", 20000), minimum=1, maximum=200000)
    with path.open("rb") as handle:
        raw = handle.read(max_bytes + 1)
    if b"\0" in raw[:4096]:
        raise ToolError("file appears to be binary")
    truncated = len(raw) > max_bytes
    text = raw[:max_bytes].decode("utf-8", errors="replace")
    return {
        "path": _relative_path(path, context.workspace_root),
        "text": text,
        "bytes_read": min(len(raw), max_bytes),
        "truncated": truncated,
    }


def file_write(args: dict[str, Any], context: "ToolContext") -> dict[str, Any]:
    path = _resolve_workspace_path(context.workspace_root, _require_str(args, "path"))
    content = _require_raw_str(args, "content")
    mode = str(args.get("mode") or "create")
    if mode not in {"create", "overwrite", "append"}:
        raise ToolError("mode must be one of: create, overwrite, append")
    if mode == "create" and path.exists():
        raise ToolError(f"file already exists: {_relative_path(path, context.workspace_root)}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if mode == "append":
        with path.open("a", encoding="utf-8") as handle:
            handle.write(content)
    else:
        path.write_text(content, encoding="utf-8")
    return {
        "path": _relative_path(path, context.workspace_root),
        "mode": mode,
        "bytes_written": len(content.encode("utf-8")),
    }


def file_patch(args: dict[str, Any], context: "ToolContext") -> dict[str, Any]:
    path = _resolve_workspace_path(context.workspace_root, _require_str(args, "path"))
    if not path.is_file():
        raise NotFoundError(f"file not found: {_relative_path(path, context.workspace_root)}")
    replacements = normalize_text_replacements(args.get("replacements"))
    replace_all = optional_bool(args.get("replace_all"), default=False)
    content = _read_text_prefix(path, 2_000_000)
    updated, applied = apply_exact_replacements(content, replacements, replace_all=replace_all)

    path.write_text(updated, encoding="utf-8")
    return {
        "path": _relative_path(path, context.workspace_root),
        "replacements": applied,
        "replace_all": replace_all,
        "bytes_written": len(updated.encode("utf-8")),
    }


def web_fetch(args: dict[str, Any], context: "ToolContext") -> dict[str, Any]:
    url = _require_str(args, "url")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ToolError("web_fetch supports only http and https URLs")
    timeout_s = _bounded_float(args.get("timeout_s", 10), minimum=0.1, maximum=30)
    max_bytes = _bounded_int(args.get("max_bytes", 60000), minimum=1, maximum=200000)
    request = Request(url, headers={"User-Agent": "mnemo-agent/0"})
    try:
        with urlopen(request, timeout=timeout_s) as response:
            raw = response.read(max_bytes + 1)
            content_type = response.headers.get("content-type", "")
            charset = response.headers.get_content_charset() or "utf-8"
            status = getattr(response, "status", 200)
    except URLError as exc:
        raise ToolError(f"web_fetch failed: {exc}") from exc
    truncated = len(raw) > max_bytes
    text = raw[:max_bytes].decode(charset, errors="replace")
    return {
        "url": url,
        "status": status,
        "content_type": content_type,
        "text": text,
        "bytes_read": min(len(raw), max_bytes),
        "truncated": truncated,
    }


def shell_exec(args: dict[str, Any], context: "ToolContext") -> dict[str, Any]:
    command = _require_str_list(args, "command")
    cwd = _resolve_workspace_path(context.workspace_root, str(args.get("cwd") or "."))
    timeout_s = _bounded_float(args.get("timeout_s", 10), minimum=0.1, maximum=60)
    max_output_bytes = _bounded_int(args.get("max_output_bytes", 20000), minimum=1, maximum=100000)
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            shell=False,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
        )
    except FileNotFoundError as exc:
        raise NotFoundError(f"command not found: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ToolError(f"command timed out after {timeout_s:g}s") from exc
    stdout, stdout_truncated = _truncate_text(completed.stdout, max_output_bytes)
    stderr, stderr_truncated = _truncate_text(completed.stderr, max_output_bytes)
    return {
        "command": command,
        "cwd": _relative_path(cwd, context.workspace_root),
        "exit_code": completed.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
    }


def standard_tool_summary(result: ToolResult) -> str | None:
    if result.name == "file_search":
        return f"Found {len(result.result.get('matches', []))} file matches."
    if result.name == "file_read":
        return f"Read file: {result.result.get('path', 'unknown')}."
    if result.name == "file_write":
        return f"Wrote file: {result.result.get('path', 'unknown')}."
    if result.name == "file_patch":
        count = sum(item.get("count", 0) for item in result.result.get("replacements", []))
        return f"Patched file: {result.result.get('path', 'unknown')} ({count} replacements)."
    if result.name == "web_fetch":
        return f"Fetched URL with status {result.result.get('status', 'unknown')}."
    if result.name == "shell_exec":
        return f"Command exited with code {result.result.get('exit_code', 'unknown')}."
    return None


def standard_tool_evidence(result: ToolResult) -> list[dict[str, Any]] | None:
    if result.name == "file_search":
        matches = result.result.get("matches", [])
        return [
            {
                "kind": "file_search",
                "summary": f"{len(matches)} matches",
                "items": matches[:10],
            }
        ]
    if result.name == "file_read":
        return [
            {
                "kind": "file",
                "id": str(result.result.get("path") or ""),
                "title": str(result.result.get("path") or "File"),
                "truncated": bool(result.result.get("truncated")),
            }
        ]
    if result.name == "file_write":
        return [_evidence("file", result.result.get("path"), str(result.result.get("path") or "File"))]
    if result.name == "file_patch":
        return [
            {
                "kind": "file_patch",
                "id": str(result.result.get("path") or ""),
                "title": str(result.result.get("path") or "File patch"),
                "replacement_count": sum(item.get("count", 0) for item in result.result.get("replacements", [])),
            }
        ]
    if result.name == "web_fetch":
        return [
            {
                "kind": "web_page",
                "id": str(result.result.get("url") or ""),
                "title": str(result.result.get("url") or "Web page"),
                "status": result.result.get("status"),
                "content_type": result.result.get("content_type"),
                "truncated": bool(result.result.get("truncated")),
            }
        ]
    if result.name == "shell_exec":
        return [
            {
                "kind": "command",
                "id": result.call_id,
                "title": " ".join(str(part) for part in result.result.get("command", [])),
                "exit_code": result.result.get("exit_code"),
            }
        ]
    return None


def _evidence(kind: str, item_id: Any, title: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "id": str(item_id or ""),
        "title": title,
    }


def _require_str(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ToolError(f"missing string argument: {key}")
    return value.strip()


def _require_raw_str(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str):
        raise ToolError(f"missing string argument: {key}")
    return value


def _require_str_list(args: dict[str, Any], key: str) -> list[str]:
    value = args.get(key)
    if not isinstance(value, list) or not value:
        raise ToolError(f"missing string array argument: {key}")
    strings: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise ToolError(f"expected non-empty string array argument: {key}")
        strings.append(item)
    return strings


def _bounded_int(value: Any, *, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ToolError("expected integer argument") from exc
    if number < minimum or number > maximum:
        raise ToolError(f"integer argument must be between {minimum} and {maximum}")
    return number


def _bounded_float(value: Any, *, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ToolError("expected number argument") from exc
    if number < minimum or number > maximum:
        raise ToolError(f"number argument must be between {minimum:g} and {maximum:g}")
    return number


def _resolve_workspace_path(workspace_root: Path, path: str) -> Path:
    if not path.strip():
        raise ToolError("path must not be empty")
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = workspace_root / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(workspace_root)
    except ValueError as exc:
        raise ToolError("path is outside the workspace root") from exc
    return resolved


def _relative_path(path: Path, workspace_root: Path) -> str:
    try:
        return path.relative_to(workspace_root).as_posix() or "."
    except ValueError:
        return path.as_posix()


def _iter_search_files(root: Path, workspace_root: Path):
    if root.is_file():
        if _is_searchable_file(root, workspace_root):
            yield root
        return
    if not root.exists():
        raise NotFoundError(f"search root not found: {_relative_path(root, workspace_root)}")
    if not root.is_dir():
        raise ToolError(f"search root is not a directory: {_relative_path(root, workspace_root)}")
    for path in root.rglob("*"):
        if _is_searchable_file(path, workspace_root):
            yield path


def _is_searchable_file(path: Path, workspace_root: Path) -> bool:
    try:
        resolved = _resolve_workspace_path(workspace_root, path.as_posix())
    except ToolError:
        return False
    if not resolved.is_file():
        return False
    rel_parts = resolved.relative_to(workspace_root).parts
    if any(part.startswith(".") for part in rel_parts):
        return False
    if resolved.stat().st_size > 500000:
        return False
    return True


def _read_text_prefix(path: Path, max_bytes: int) -> str:
    raw = path.read_bytes()[:max_bytes]
    if b"\0" in raw[:4096]:
        raise ToolError("file appears to be binary")
    return raw.decode("utf-8", errors="replace")


def _truncate_text(text: str, max_bytes: int) -> tuple[str, bool]:
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return text, False
    truncated = raw[:max_bytes].decode("utf-8", errors="replace")
    return truncated, True
