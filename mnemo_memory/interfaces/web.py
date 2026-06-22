from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import mimetypes
from pathlib import Path
import socketserver
import time
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from ..core.config import DEFAULT_STATE_DIR
from ..core.jsonutil import dumps
from ..core.log import configure_logging, get_logger, log_event
from ..sdk import MemoryClient, memory_api_schema
from .auto_dream import (
    AutoDreamScheduler,
    auto_dream_status,
    record_auto_dream_config_change,
    record_manual_dream_run,
    run_dream_with_lock,
)


_WEB_ASSETS_DIR = Path(__file__).with_name("web_assets")
_LOG = get_logger("web")


class _MemoryThreadingHTTPServer(ThreadingHTTPServer):
    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = int(port)


@dataclass(frozen=True)
class MemoryWebConfig:
    state_dir: str | Path = DEFAULT_STATE_DIR
    host: str = "127.0.0.1"
    port: int = 8765
    # Kept for CLI/config compatibility; HTTP API access is currently open.
    auth_token: str | None = None


def build_http_server(config: MemoryWebConfig) -> ThreadingHTTPServer:
    handler = _handler(config)
    return _MemoryThreadingHTTPServer((config.host, int(config.port)), handler)


def _is_loopback_host(host: str) -> bool:
    normalized = str(host or "").strip().lower()
    return normalized in {"127.0.0.1", "::1", "localhost"} or normalized.startswith("127.")


def insecure_bind_warning(host: str) -> str | None:
    """Operator warning when the unauthenticated API binds beyond loopback.

    Mnemo is single-tenant per state-dir and the HTTP API has no access control,
    so binding to anything other than loopback exposes every memory in the store.
    """
    if _is_loopback_host(host):
        return None
    return (
        f"mnemo-memory is serving an UNAUTHENTICATED HTTP API on host '{host or '0.0.0.0'}'. "
        "It has no access control and is single-tenant per state-dir; expose it only on "
        "trusted local networks, and use a separate --state-dir per user for isolation."
    )


def serve_http(config: MemoryWebConfig) -> None:
    configure_logging(state_dir=config.state_dir)
    warning = insecure_bind_warning(config.host)
    if warning:
        print(f"WARNING: {warning}")
        log_event(_LOG, "serve_insecure_bind", level=logging.WARNING, host=config.host)
    server = build_http_server(config)
    scheduler = AutoDreamScheduler(config.state_dir)
    scheduler.start()
    host, port = server.server_address
    log_event(_LOG, "serve_start", host=host, port=port, state_dir=str(config.state_dir))
    print(f"mnemo-memory API listening on http://{host}:{port}")
    try:
        server.serve_forever()
    finally:
        scheduler.stop()
        server.server_close()
        log_event(_LOG, "serve_stop", host=host, port=port)


def dispatch_memory_api(client: MemoryClient, method: str, body: dict[str, Any]) -> dict[str, Any]:
    if method == "context":
        return client.context(
            str(body.get("intent") or ""),
            limit=int(body.get("limit") or 8),
            scope=str(body.get("scope") or "memory"),
            uid=_optional(body.get("uid")),
        )
    if method == "recall":
        return client.recall(
            _required(body, "seed"),
            context=str(body.get("context") or ""),
            depth=int(body.get("depth") or 2),
            limit=int(body.get("limit") or 8),
            uid=_optional(body.get("uid")),
        )
    if method == "search":
        return client.search(
            _required(body, "query"),
            limit=int(body.get("limit") or 8),
            scope=str(body.get("scope") or "memory"),
            include_tombstoned=bool(body.get("include_tombstoned", False)),
            uid=_optional(body.get("uid")),
        )
    if method == "list":
        return client.list(
            kind=str(body.get("kind") or "all"),
            status=_optional(body.get("status")),
            limit=int(body.get("limit") or 50),
            include_tombstoned=bool(body.get("include_tombstoned", False)),
            uid=_optional(body.get("uid")),
        )
    if method in {"stable-create", "stable_create"}:
        return client.stable_create(
            title=_required(body, "title"),
            content=_required(body, "content"),
            scope=str(body.get("scope") or "global"),
            confidence=float(body.get("confidence") or 0.7),
            status=str(body.get("status") or "active"),
            metadata=_metadata(body, "metadata"),
            dimension=_optional(body.get("dimension")),
        )
    if method in {"stable-read", "stable_read"}:
        return client.stable_read(_required(body, "memory_id"))
    if method in {"stable-update", "stable_update"}:
        kwargs: dict[str, Any] = {}
        for key in ("title", "content", "scope", "confidence", "status", "dimension"):
            if key in body:
                kwargs[key] = body.get(key)
        if "metadata" in body:
            kwargs["metadata"] = _metadata(body, "metadata")
        return client.stable_update(_required(body, "memory_id"), **kwargs)
    if method in {"stable-search", "stable_search"}:
        return client.stable_search(
            str(body.get("query") or ""),
            limit=_optional_int(body.get("limit")),
            all_items=bool(body.get("all", False)),
            uid=_optional(body.get("uid")),
            status=_optional(body.get("status")) or "active",
            include_inactive=bool(body.get("include_inactive", False)),
        )
    if method in {"stable-delete", "stable_delete"}:
        return client.stable_delete(
            _required(body, "memory_id"),
            mode=str(body.get("mode") or "tombstone"),
            reason=str(body.get("reason") or "deleted"),
            delete_related=bool(body.get("delete_related", True)),
        )
    if method in {"plan-create", "plan_create"}:
        return client.plan_create(
            kind=str(body.get("kind") or "todo"),
            title=_required(body, "title"),
            detail=str(body.get("detail") or ""),
            scope=str(body.get("scope") or "global"),
            uid=_optional(body.get("uid")),
            parent_id=_optional(body.get("parent_id")),
            status=_optional(body.get("status")),
            priority=str(body.get("priority") or "normal"),
            due_at=body.get("due_at"),
            source=str(body.get("source") or "http"),
            source_event_id=_optional(body.get("source_event_id")),
            metadata=_metadata(body, "metadata"),
        )
    if method in {"plan-read", "plan_read"}:
        return client.plan_read(_required(body, "plan_id"))
    if method in {"plan-update", "plan_update"}:
        kwargs: dict[str, Any] = {}
        for key in ("kind", "title", "detail", "scope", "uid", "parent_id", "status", "priority", "due_at", "source", "source_event_id"):
            if key in body:
                kwargs[key] = body.get(key)
        if "metadata" in body:
            kwargs["metadata"] = _metadata(body, "metadata")
        return client.plan_update(_required(body, "plan_id"), **kwargs)
    if method in {"plan-list", "plan_list"}:
        return client.plan_list(
            kind=_optional(body.get("kind")),
            status=_status_filter(body.get("status")),
            scope=_optional(body.get("scope")),
            uid=_optional(body.get("uid")),
            query=str(body.get("query") or ""),
            limit=int(body.get("limit") or 50),
            include_archived=bool(body.get("include_archived", False)),
        )
    if method in {"plan-complete", "plan_complete"}:
        return client.plan_complete(_required(body, "plan_id"))
    if method in {"plan-cancel", "plan_cancel"}:
        return client.plan_cancel(
            _required(body, "plan_id"),
            reason=str(body.get("reason") or "cancelled"),
        )
    if method in {"plan-archive", "plan_archive"}:
        return client.plan_archive(_required(body, "plan_id"))
    if method in {"plan-proposals", "plan_proposals"}:
        status = _optional(body.get("status")) if "status" in body else "pending"
        return client.plan_proposals(
            status=status,
            scope=_optional(body.get("scope")),
            uid=_optional(body.get("uid")),
            limit=int(body.get("limit") or 50),
        )
    if method in {"user-goals", "user_goals"}:
        return client.user_goals(
            _required(body, "uid"),
            status=_status_filter(body.get("status")),
            include_archived=bool(body.get("include_archived", False)),
            include_proposals=body.get("include_proposals", True) is not False,
            limit=int(body.get("limit") or 100),
        )
    if method in {"apply-plan-proposal", "apply_plan_proposal"}:
        return client.apply_plan_proposal(_required(body, "proposal_id"))
    if method in {"reject-plan-proposal", "reject_plan_proposal"}:
        return client.reject_plan_proposal(
            _required(body, "proposal_id"),
            reason=str(body.get("reason") or "operator_rejected"),
        )
    if method == "update":
        return client.update(
            facts=body.get("facts") if isinstance(body.get("facts"), list) else [],
            observations=body.get("observations") if isinstance(body.get("observations"), list) else [],
            source=str(body.get("source") or "http"),
            run_id=_optional(body.get("run_id")),
            mission_id=_optional(body.get("mission_id")),
        )
    if method == "ingest-event":
        return client.ingest_event(
            text=_required(body, "text"),
            source=str(body.get("source") or "http"),
            actor=_optional(body.get("actor")),
            event_type=str(body.get("event_type") or "message"),
            context=body.get("context") if isinstance(body.get("context"), list) else [],
            run_id=_optional(body.get("run_id")),
            mission_id=_optional(body.get("mission_id")),
            conversation_id=_optional(body.get("conversation_id")),
            message_id=_optional(body.get("message_id")),
            agent_id=_optional(body.get("agent_id")),
            event_at=body.get("event_at"),
            observed_at=body.get("observed_at"),
            scope=_optional(body.get("scope")),
            auto_promote=bool(body.get("auto_promote", False)),
            min_confidence=float(body.get("min_confidence") or 0.7),
            use_provider=bool(body.get("use_provider", False)),
        )
    if method == "read":
        return client.read(_required(body, "memory_id"))
    if method == "links":
        return client.links(_required(body, "memory_id"), direction=str(body.get("direction") or "both"))
    if method == "provenance":
        return client.provenance(_required(body, "memory_id"))
    if method == "snapshot":
        return client.snapshot(compile=bool(body.get("compile", False)), limit=int(body.get("limit") or 50))
    if method == "health":
        return client.health(limit=int(body.get("limit") or 20))
    if method in {"provider-config", "provider_config"}:
        return client.provider_config()
    if method in {"embedding-config", "embedding_config"}:
        return client.embedding_config()
    if method in {"save-embedding-config", "save_embedding_config"}:
        return client.save_embedding_config(
            enabled=body.get("enabled"),
            base_url=_config_field(body, "base_url"),
            model=_config_field(body, "model"),
            api_key=body.get("api_key", ""),
            api_key_env=_config_field(body, "api_key_env"),
            clear_api_key=bool(body.get("clear_api_key", False)),
        )
    if method in {"embedding-status", "embedding_status"}:
        return client.embedding_status()
    if method in {"reindex-embeddings", "reindex_embeddings"}:
        return client.reindex_embeddings(limit=int(body.get("limit") or 10000))
    if method in {"save-provider-config", "save_provider_config"}:
        return client.save_provider_config(
            provider=_config_field(body, "provider"),
            base_url=_config_field(body, "base_url"),
            model=_config_field(body, "model"),
            api_key=body.get("api_key", ""),
            api_key_env=_config_field(body, "api_key_env"),
            timeout_s=body.get("timeout_s"),
            thinking_enabled=body.get("thinking_enabled"),
            clear_api_key=bool(body.get("clear_api_key", False)),
        )
    if method in {"auto-dream-status", "auto_dream_status"}:
        return auto_dream_status(client)
    if method in {"save-auto-dream-config", "save_auto_dream_config"}:
        client.save_auto_dream_config(
            enabled=body.get("enabled"),
            interval_minutes=body.get("interval_minutes"),
            limit=body.get("limit"),
            min_confidence=body.get("min_confidence"),
            local_fallback=body.get("local_fallback"),
        )
        return record_auto_dream_config_change(client)
    if method == "tombstones":
        return client.tombstones(
            target_id=_optional(body.get("target_id")),
            target_type=_optional(body.get("target_type")),
            limit=int(body.get("limit") or 50),
        )
    if method == "promote-candidate":
        raw_min = body.get("min_confidence")
        return client.promote_candidate(
            _required(body, "candidate_id"),
            min_confidence=float(raw_min) if raw_min not in (None, "") else None,
        )
    if method in {"effective-config", "effective_config"}:
        return client.effective_config()
    if method in {"test-provider", "test_provider"}:
        return client.test_provider()
    if method in {"test-embedding", "test_embedding"}:
        return client.test_embedding()
    if method in {"tuning-config", "tuning_config"}:
        return client.tuning_config()
    if method in {"save-tuning-config", "save_tuning_config"}:
        return client.save_tuning_config(
            quality_write_threshold=body.get("quality_write_threshold"),
            quality_draft_threshold=body.get("quality_draft_threshold"),
            promote_min_confidence=body.get("promote_min_confidence"),
        )
    if method == "force-promote-candidate":
        return client.force_promote_candidate(_required(body, "candidate_id"))
    if method == "reject-candidate":
        return client.reject_candidate(_required(body, "candidate_id"), _required(body, "reason"))
    if method == "tombstone":
        return client.tombstone(
            _required(body, "memory_id"),
            _required(body, "reason"),
            target_type=str(body.get("target_type") or "auto"),
            replacement_id=_optional(body.get("replacement_id")),
        )
    if method == "forget":
        return client.forget(
            _required(body, "memory_id"),
            reason=str(body.get("reason") or "private_delete"),
            target_type=str(body.get("target_type") or "auto"),
        )
    if method in {"hard-delete", "hard_delete"}:
        memory_id = _optional(body.get("memory_id"))
        tombstone_id = _optional(body.get("tombstone_id"))
        if not memory_id and not tombstone_id:
            raise ValueError("memory_id or tombstone_id is required")
        return client.hard_delete(
            memory_id,
            target_type=str(body.get("target_type") or "auto"),
            tombstone_id=tombstone_id,
            delete_related=bool(body.get("delete_related", True)),
        )
    if method == "dream-run":
        report = run_dream_with_lock(
            client,
            limit=int(body.get("limit") or 20),
            min_confidence=float(body.get("min_confidence") or 0.7),
            actions=body.get("actions") if isinstance(body.get("actions"), list) else None,
            use_provider=bool(body.get("use_provider", False)),
            advanced_dreaming=bool(body.get("advanced_dreaming", False)),
            execution_policy=str(body.get("execution_policy") or "semi_auto"),
        )
        record_manual_dream_run(client, report)
        return report
    if method == "dream-status":
        return client.dream_status(limit=int(body.get("limit") or 20))
    if method == "dream-report":
        report = client.dream_report(_optional(body.get("report_id")), latest=bool(body.get("latest", False)))
        return {"kind": "dream_report_lookup", "report": report}
    if method == "dream-proposals":
        status = _optional(body.get("status")) if "status" in body else "pending"
        return client.dream_proposals(
            status=status,
            limit=int(body.get("limit") or 50),
        )
    if method == "apply-dream-proposal":
        return client.apply_dream_proposal(_required(body, "proposal_id"))
    if method == "reject-dream-proposal":
        return client.reject_dream_proposal(
            _required(body, "proposal_id"),
            reason=str(body.get("reason") or "operator_rejected"),
        )
    if method in {"resolve-conflict", "resolve_conflict"}:
        return client.resolve_conflict(
            _required(body, "candidate_id"),
            resolution=_required(body, "resolution"),
        )
    if method == "versions":
        return client.versions(
            _required(body, "memory_id"),
            limit=int(body.get("limit") or 20),
        )
    if method == "profile":
        return client.profile(limit=int(body.get("limit") or 50))
    if method in {"memory-graph", "memory_graph"}:
        return client.memory_graph(limit=int(body.get("limit") or 200))
    raise KeyError(method)


def _handler(config: MemoryWebConfig):
    client = MemoryClient(state_dir=config.state_dir)

    class MemoryHandler(BaseHTTPRequestHandler):
        server_version = "MnemoMemory/0.1"

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/api/health":
                self._send({"ok": True, "service": "mnemo-memory"})
                return
            if not parsed.path.startswith("/api/"):
                self._send_static(parsed.path)
                return
            if parsed.path == "/api/schema":
                self._send({"api_schema": memory_api_schema()})
                return
            if parsed.path == "/api/memory/read":
                query = parse_qs(parsed.query)
                memory_id = (query.get("memory_id") or [""])[0]
                self._dispatch("read", {"memory_id": memory_id})
                return
            self._send({"error": "not found"}, status=HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            prefix = "/api/memory/"
            if not parsed.path.startswith(prefix):
                self._send({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self._dispatch(parsed.path.removeprefix(prefix), self._read_json())

        def _dispatch(self, method: str, body: dict[str, Any]) -> None:
            started = time.perf_counter()
            status = HTTPStatus.OK
            try:
                result = dispatch_memory_api(client, method, body)
            except KeyError:
                status = HTTPStatus.NOT_FOUND
                self._send({"error": f"unknown method: {method}"}, status=status)
            except (TypeError, ValueError) as exc:
                status = HTTPStatus.BAD_REQUEST
                self._send({"error": str(exc)}, status=status)
            else:
                self._send({"method": method, "result": result})
            finally:
                log_event(
                    _LOG,
                    "http_request",
                    level=logging.DEBUG if status == HTTPStatus.OK else logging.WARNING,
                    method=method,
                    status=int(status),
                    ms=round((time.perf_counter() - started) * 1000, 1),
                )

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or "0")
            if length <= 0:
                return {}
            parsed = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(parsed, dict):
                raise ValueError("request body must be a JSON object")
            return parsed

        def _send(self, payload: dict[str, Any], *, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = dumps(payload).encode("utf-8")
            self.send_response(int(status))
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_static(self, raw_path: str) -> None:
            static_path = _resolve_static_path(raw_path)
            if static_path is None:
                self._send({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
                return
            body = static_path.read_bytes()
            content_type = mimetypes.guess_type(static_path.name)[0] or "application/octet-stream"
            if static_path.name == "index.html":
                content_type = "text/html; charset=utf-8"
            elif content_type.startswith("text/") or content_type == "application/javascript":
                content_type = f"{content_type}; charset=utf-8"
            self.send_response(int(HTTPStatus.OK))
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            return

    return MemoryHandler


def _required(body: dict[str, Any], key: str) -> str:
    value = str(body.get(key) or "").strip()
    if not value:
        raise ValueError(f"{key} is required")
    return value


def _optional(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _status_filter(value: Any) -> str | list[str] | None:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return _optional(value)


def _metadata(body: dict[str, Any], key: str) -> dict[str, Any] | None:
    if key not in body or body.get(key) is None:
        return None
    value = body.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be a JSON object")
    return value


def _config_field(body: dict[str, Any], key: str) -> str | None:
    if key not in body:
        return None
    return str(body.get(key) or "")


def _resolve_static_path(raw_path: str) -> Path | None:
    path = unquote(raw_path or "/")
    if "\\" in path:
        return None
    try:
        assets_root = _WEB_ASSETS_DIR.resolve(strict=False)
    except OSError:
        return None

    if path in {"", "/"}:
        return _existing_index(assets_root)

    if path.startswith("/assets/"):
        candidate = (assets_root / "assets" / path.removeprefix("/assets/")).resolve(strict=False)
        if not _is_relative_to(candidate, assets_root) or not candidate.is_file():
            return None
        return candidate

    if "." in Path(path).name:
        return None
    return _existing_index(assets_root)


def _existing_index(assets_root: Path) -> Path | None:
    index = assets_root / "index.html"
    return index if index.is_file() else None


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
