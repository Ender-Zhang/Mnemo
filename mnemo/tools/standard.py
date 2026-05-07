from __future__ import annotations

from collections.abc import Callable
from html.parser import HTMLParser
import ipaddress
import os
from pathlib import Path
import socket
import subprocess
import sys
from typing import TYPE_CHECKING, Any
from urllib.error import URLError
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen
import webbrowser

from ..core.errors import NotFoundError, ToolError
from ..core.models import ToolResult, ToolSpec
from ..core.text_patch import apply_exact_replacements, normalize_text_replacements, optional_bool

if TYPE_CHECKING:
    from .registry import ToolContext


ToolHandler = Callable[[dict[str, Any], "ToolContext"], dict[str, Any]]

# Web tool design acknowledgement: inspired by Hermes Agent's MIT-licensed
# web tool split between search metadata and page extraction/fetching.
# This implementation is Mnemo-specific and keeps stdlib-only dependencies.
_WEB_USER_AGENT = "mnemo-agent/0"
_DUCKDUCKGO_HTML_SEARCH_URL = "https://duckduckgo.com/html/?q={query}"
_BLOCKED_WEB_HOSTNAMES = frozenset({"metadata.google.internal", "metadata.goog"})
_ALWAYS_BLOCKED_WEB_IPS = frozenset(
    {
        ipaddress.ip_address("169.254.169.254"),
        ipaddress.ip_address("169.254.170.2"),
        ipaddress.ip_address("169.254.169.253"),
        ipaddress.ip_address("100.100.100.200"),
        ipaddress.ip_address("fd00:ec2::254"),
    }
)
_ALWAYS_BLOCKED_WEB_NETWORKS = (ipaddress.ip_network("169.254.0.0/16"),)
_CGNAT_NETWORK = ipaddress.ip_network("100.64.0.0/10")
_TEXTUAL_CONTENT_MARKERS = (
    "json",
    "javascript",
    "markdown",
    "text",
    "xhtml",
    "xml",
    "yaml",
)


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
        name="web_search",
        description="Search the public web and return compact result metadata. Requires external policy.",
        risk="external",
        input_schema=_schema(
            ["query"],
            {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
                "timeout_s": {"type": "number", "minimum": 0.1, "maximum": 30, "default": 10},
            },
        ),
    ),
    ToolSpec(
        name="web_fetch",
        description="Fetch an HTTP or HTTPS URL and return readable text. Requires external policy.",
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
    ToolSpec(
        name="browser_open",
        description="Open an HTTP or HTTPS URL in the user's default browser. Requires external policy.",
        risk="external",
        input_schema=_schema(
            ["url"],
            {
                "url": {"type": "string"},
                "new": {"type": "integer", "enum": [0, 1, 2], "default": 2},
                "dry_run": {"type": "boolean", "default": False},
            },
        ),
    ),
    ToolSpec(
        name="app_open",
        description="Open a workspace-scoped file or folder with the OS default app. Requires admin policy.",
        risk="admin",
        input_schema=_schema(
            ["path"],
            {
                "path": {"type": "string"},
                "dry_run": {"type": "boolean", "default": False},
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
        "web_search": web_search,
        "web_fetch": web_fetch,
        "shell_exec": shell_exec,
        "browser_open": browser_open,
        "app_open": app_open,
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


def web_search(args: dict[str, Any], context: "ToolContext") -> dict[str, Any]:
    query = _require_str(args, "query")
    limit = _bounded_int(args.get("limit", 5), minimum=1, maximum=20)
    timeout_s = _bounded_float(args.get("timeout_s", 10), minimum=0.1, maximum=30)
    search_url = _DUCKDUCKGO_HTML_SEARCH_URL.format(query=quote_plus(query))
    fetched = _fetch_http(search_url, timeout_s=timeout_s, max_bytes=120000)
    charset = fetched["headers"].get_content_charset() or "utf-8"
    html = fetched["raw"].decode(charset, errors="replace")
    results = _parse_search_results(html, limit=limit)
    return {
        "query": query,
        "source": "duckduckgo_html",
        "results": results,
        "count": len(results),
        "truncated": bool(fetched["truncated"]),
    }


def web_fetch(args: dict[str, Any], context: "ToolContext") -> dict[str, Any]:
    url = _require_public_http_url(args, "url")
    timeout_s = _bounded_float(args.get("timeout_s", 10), minimum=0.1, maximum=30)
    max_bytes = _bounded_int(args.get("max_bytes", 60000), minimum=1, maximum=200000)
    fetched = _fetch_http(url, timeout_s=timeout_s, max_bytes=max_bytes)
    content_type = fetched["headers"].get("content-type", "")
    text, title = _decode_web_body(fetched["raw"][:max_bytes], fetched["headers"])
    return {
        "url": url,
        "final_url": fetched["final_url"],
        "status": fetched["status"],
        "content_type": content_type,
        "title": title,
        "text": text,
        "bytes_read": fetched["bytes_read"],
        "truncated": fetched["truncated"],
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


def browser_open(args: dict[str, Any], context: "ToolContext") -> dict[str, Any]:
    url = _require_http_url(args, "url")
    new = _bounded_int(args.get("new", 2), minimum=0, maximum=2)
    dry_run = optional_bool(args.get("dry_run"), default=False)
    opened = False
    if not dry_run:
        opened = webbrowser.open(url, new=new)
        if not opened:
            raise ToolError("browser_open could not open the URL")
    return {
        "url": url,
        "new": new,
        "dry_run": dry_run,
        "opened": opened,
    }


def app_open(args: dict[str, Any], context: "ToolContext") -> dict[str, Any]:
    path = _resolve_workspace_path(context.workspace_root, _require_str(args, "path"))
    if not path.exists():
        raise NotFoundError(f"path not found: {_relative_path(path, context.workspace_root)}")
    dry_run = optional_bool(args.get("dry_run"), default=False)
    opened = False
    if not dry_run:
        _open_path_with_default_app(path)
        opened = True
    return {
        "path": _relative_path(path, context.workspace_root),
        "is_directory": path.is_dir(),
        "dry_run": dry_run,
        "opened": opened,
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
    if result.name == "web_search":
        return f"Found {len(result.result.get('results', []))} web results."
    if result.name == "web_fetch":
        return f"Fetched URL with status {result.result.get('status', 'unknown')}."
    if result.name == "shell_exec":
        return f"Command exited with code {result.result.get('exit_code', 'unknown')}."
    if result.name == "browser_open":
        state = "prepared" if result.result.get("dry_run") else "opened"
        return f"Browser {state}: {result.result.get('url', 'unknown')}."
    if result.name == "app_open":
        state = "prepared" if result.result.get("dry_run") else "opened"
        return f"App {state}: {result.result.get('path', 'unknown')}."
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
    if result.name == "web_search":
        results = result.result.get("results", [])
        return [
            {
                "kind": "web_search",
                "id": str(result.result.get("query") or ""),
                "title": str(result.result.get("query") or "Web search"),
                "items": results[:10],
                "source": result.result.get("source"),
            }
        ]
    if result.name == "web_fetch":
        return [
            {
                "kind": "web_page",
                "id": str(result.result.get("final_url") or result.result.get("url") or ""),
                "title": str(result.result.get("title") or result.result.get("url") or "Web page"),
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
    if result.name == "browser_open":
        return [
            {
                "kind": "browser",
                "id": str(result.result.get("url") or ""),
                "title": str(result.result.get("url") or "Browser"),
                "opened": bool(result.result.get("opened")),
                "dry_run": bool(result.result.get("dry_run")),
            }
        ]
    if result.name == "app_open":
        return [
            {
                "kind": "app",
                "id": str(result.result.get("path") or ""),
                "title": str(result.result.get("path") or "App"),
                "opened": bool(result.result.get("opened")),
                "dry_run": bool(result.result.get("dry_run")),
                "is_directory": bool(result.result.get("is_directory")),
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


def _require_http_url(args: dict[str, Any], key: str) -> str:
    url = _require_str(args, key)
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ToolError(f"{key} must be an http or https URL")
    return url


def _require_public_http_url(args: dict[str, Any], key: str) -> str:
    return _validate_public_http_url(_require_http_url(args, key), key=key)


def _validate_public_http_url(url: str, *, key: str = "url") -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ToolError(f"{key} must be an http or https URL")
    hostname = (parsed.hostname or "").strip().lower().rstrip(".")
    if not hostname:
        raise ToolError(f"{key} must be an http or https URL")
    if hostname in _BLOCKED_WEB_HOSTNAMES:
        raise ToolError(f"{key} points to a blocked internal host")
    resolved_ips = _resolve_hostname_ips(hostname)
    if any(_is_always_blocked_web_ip(ip) for ip in resolved_ips):
        raise ToolError(f"{key} points to a private or internal network address")
    if _allow_private_web_urls():
        return url
    for ip in resolved_ips:
        if _is_blocked_web_ip(ip):
            raise ToolError(f"{key} points to a private or internal network address")
    return url


def _allow_private_web_urls() -> bool:
    return str(os.getenv("MNEMO_ALLOW_PRIVATE_WEB_URLS") or "").strip().lower() in {"1", "true", "yes"}


def _resolve_hostname_ips(hostname: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None
    if literal is not None:
        return [literal]
    try:
        addr_info = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ToolError("URL host could not be resolved") from exc
    ips: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for item in addr_info:
        sockaddr = item[4]
        try:
            ips.append(ipaddress.ip_address(str(sockaddr[0])))
        except (IndexError, ValueError):
            continue
    if not ips:
        raise ToolError("URL host could not be resolved")
    return ips


def _is_always_blocked_web_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return ip in _ALWAYS_BLOCKED_WEB_IPS or any(ip in network for network in _ALWAYS_BLOCKED_WEB_NETWORKS)


def _is_blocked_web_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if _is_always_blocked_web_ip(ip):
        return True
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
        return True
    if ip.is_multicast or ip.is_unspecified:
        return True
    if ip in _CGNAT_NETWORK:
        return True
    return False


class _SafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        target = urljoin(req.full_url, newurl)
        _validate_public_http_url(target)
        return super().redirect_request(req, fp, code, msg, headers, target)


def _fetch_http(url: str, *, timeout_s: float, max_bytes: int) -> dict[str, Any]:
    _validate_public_http_url(url)
    request = Request(url, headers={"User-Agent": _WEB_USER_AGENT})
    try:
        with build_opener(_SafeRedirectHandler).open(request, timeout=timeout_s) as response:
            final_url = _validate_public_http_url(response.geturl())
            raw = response.read(max_bytes + 1)
            status = getattr(response, "status", 200)
            headers = response.headers
    except URLError as exc:
        raise ToolError(f"web request failed: {exc}") from exc
    truncated = len(raw) > max_bytes
    return {
        "url": url,
        "final_url": final_url,
        "status": status,
        "headers": headers,
        "raw": raw[:max_bytes],
        "bytes_read": min(len(raw), max_bytes),
        "truncated": truncated,
    }


def _decode_web_body(raw: bytes, headers: Any) -> tuple[str, str | None]:
    content_type = str(headers.get("content-type", "") or "").casefold()
    if raw.startswith(b"%PDF"):
        raise ToolError("web_fetch does not decode PDF content")
    if b"\0" in raw[:4096]:
        raise ToolError("web_fetch response appears to be binary")
    if content_type and not _is_textual_content_type(content_type):
        raise ToolError(f"web_fetch response is not text content: {content_type}")
    charset = headers.get_content_charset() or "utf-8"
    decoded = raw.decode(charset, errors="replace")
    if "html" not in content_type and not _looks_like_html(decoded):
        return decoded, None
    return _html_to_text(decoded)


def _is_textual_content_type(content_type: str) -> bool:
    return any(marker in content_type for marker in _TEXTUAL_CONTENT_MARKERS)


def _looks_like_html(text: str) -> bool:
    prefix = text.lstrip()[:200].casefold()
    return prefix.startswith("<!doctype html") or prefix.startswith("<html") or "<body" in prefix


def _html_to_text(html: str) -> tuple[str, str | None]:
    parser = _HTMLTextExtractor()
    parser.feed(html)
    parser.close()
    return parser.text(), parser.title()


class _HTMLTextExtractor(HTMLParser):
    _BLOCK_TAGS = {
        "article",
        "br",
        "dd",
        "div",
        "dt",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "li",
        "main",
        "p",
        "pre",
        "section",
        "table",
        "td",
        "th",
        "tr",
        "ul",
        "ol",
    }
    _SKIP_TAGS = {"script", "style", "noscript", "template", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._title_chunks: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag == "title":
            self._in_title = True
            return
        if tag in self._BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
            return
        if tag == "title":
            self._in_title = False
            return
        if tag in self._BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self._title_chunks.append(data)
            return
        self._chunks.append(data)

    def text(self) -> str:
        return _clean_visible_text("".join(self._chunks))

    def title(self) -> str | None:
        title = _clean_inline_text("".join(self._title_chunks))
        return title or None


def _clean_visible_text(text: str) -> str:
    lines = [_clean_inline_text(line) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _clean_inline_text(text: str) -> str:
    return " ".join(text.split())


def _parse_search_results(html: str, *, limit: int) -> list[dict[str, Any]]:
    parser = _DuckDuckGoHTMLParser(limit=limit)
    parser.feed(html)
    parser.close()
    return parser.results()


class _DuckDuckGoHTMLParser(HTMLParser):
    def __init__(self, *, limit: int) -> None:
        super().__init__(convert_charrefs=True)
        self._limit = limit
        self._results: list[dict[str, Any]] = []
        self._current: dict[str, Any] | None = None
        self._capture: str | None = None
        self._capture_tag: str | None = None
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if len(self._results) >= self._limit:
            return
        attr_map = {name.lower(): value or "" for name, value in attrs}
        classes = set(attr_map.get("class", "").split())
        if tag == "a" and "result__a" in classes:
            self._finish_current()
            self._current = {"url": _normalize_search_result_url(attr_map.get("href", ""))}
            self._capture = "title"
            self._capture_tag = tag
            self._buffer = []
            return
        if self._current is not None and "result__snippet" in classes:
            self._capture = "snippet"
            self._capture_tag = tag
            self._buffer = []

    def handle_endtag(self, tag: str) -> None:
        if self._capture and tag == self._capture_tag and self._current is not None:
            self._current[self._capture] = _clean_inline_text("".join(self._buffer))
            self._capture = None
            self._capture_tag = None
            self._buffer = []
            if "snippet" in self._current:
                self._finish_current()

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._buffer.append(data)

    def close(self) -> None:
        super().close()
        self._finish_current()

    def results(self) -> list[dict[str, Any]]:
        return self._results[: self._limit]

    def _finish_current(self) -> None:
        if self._current is None or len(self._results) >= self._limit:
            self._current = None
            return
        title = _clean_inline_text(str(self._current.get("title") or ""))
        url = _normalize_search_result_url(str(self._current.get("url") or ""))
        if title and _is_search_result_http_url(url):
            self._results.append(
                {
                    "position": len(self._results) + 1,
                    "title": title,
                    "url": url,
                    "snippet": _clean_inline_text(str(self._current.get("snippet") or "")),
                }
            )
        self._current = None


def _normalize_search_result_url(url: str) -> str:
    value = url.strip()
    if not value:
        return ""
    if value.startswith("//"):
        value = f"https:{value}"
    parsed = urlparse(value)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        uddg = parse_qs(parsed.query).get("uddg")
        if uddg:
            return unquote(uddg[0])
    return value


def _is_search_result_http_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    hostname = (parsed.hostname or "").strip().lower().rstrip(".")
    if not hostname or hostname in _BLOCKED_WEB_HOSTNAMES:
        return False
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        return True
    return not _is_blocked_web_ip(literal)


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


def _open_path_with_default_app(path: Path) -> None:
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    if os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
        return
    subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
