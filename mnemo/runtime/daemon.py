from __future__ import annotations

from collections.abc import Callable
import os
import time
from pathlib import Path
from typing import Any

from ..core.errors import DaemonLockError
from ..core.ids import new_id
from ..core.jsonutil import dumps, loads
from ..core.models import RunRequest, RunResult
from ..storage import StateStore


RunExecutor = Callable[[RunRequest], RunResult]


class DaemonLock:
    def __init__(self, state_dir: str | Path, name: str = "daemon") -> None:
        self.state_dir = Path(state_dir).expanduser().resolve()
        self.lock_path = self.state_dir / "locks" / f"{name}.lock"
        self._token = new_id("lock")
        self._held = False

    def __enter__(self) -> DaemonLock:
        self.acquire()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.release()

    def acquire(self) -> None:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"pid": os.getpid(), "token": self._token, "created_at": time.time()}
        try:
            self._write_lock(payload)
        except FileExistsError:
            owner = self.status()
            if owner.get("locked") and not owner.get("stale"):
                raise DaemonLockError(f"daemon already running for state dir: {self.state_dir}") from None
            self._unlink_stale_lock()
            self._write_lock(payload)
        self._held = True

    def release(self) -> None:
        if not self._held:
            return
        owner = self._read_owner()
        if owner.get("token") == self._token:
            try:
                self.lock_path.unlink()
            except FileNotFoundError:
                pass
        self._held = False

    def status(self) -> dict[str, Any]:
        owner = self._read_owner()
        if not owner.get("locked"):
            return owner
        return {
            "locked": True,
            "pid": owner.get("pid"),
            "created_at": owner.get("created_at"),
            "stale": owner.get("stale", False),
        }

    def _read_owner(self) -> dict[str, Any]:
        try:
            payload = loads(self.lock_path.read_text(encoding="utf-8"), {})
        except FileNotFoundError:
            return {"locked": False}
        except OSError:
            return {"locked": True, "pid": None, "created_at": None, "token": None, "stale": False}
        if not isinstance(payload, dict):
            return {"locked": True, "pid": None, "created_at": None, "token": None, "stale": False}
        pid = payload.get("pid")
        running = isinstance(pid, int) and _pid_is_running(pid)
        return {
            "locked": True,
            "pid": pid,
            "created_at": payload.get("created_at"),
            "token": payload.get("token"),
            "stale": not running,
        }

    def _write_lock(self, payload: dict[str, Any]) -> None:
        fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(dumps(payload))

    def _unlink_stale_lock(self) -> None:
        try:
            self.lock_path.unlink()
        except FileNotFoundError:
            pass


class DaemonRunner:
    def __init__(self, state_dir: str | Path) -> None:
        self.store = StateStore(state_dir)

    def enqueue(
        self,
        message: str,
        *,
        conversation_id: str | None = None,
        mission_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        self.store.initialize()
        return self.store.enqueue_run_request(
            message,
            conversation_id=conversation_id,
            mission_id=mission_id,
            metadata=metadata,
        )

    def status(self) -> dict[str, Any]:
        self.store.initialize()
        return {
            "queue": self.store.queue_stats(),
            "lock": DaemonLock(self.store.state_dir).status(),
        }

    def recover(self, *, stale_after_s: float = 900.0) -> dict[str, Any]:
        self.store.initialize()
        recovered = self.store.recover_stale_queue_items(stale_after_s=stale_after_s)
        return {"recovered": recovered, "stats": self.store.queue_stats()}

    def drain(
        self,
        executor: RunExecutor,
        *,
        limit: int = 1,
        stale_after_s: float = 900.0,
        worker_id: str | None = None,
    ) -> dict[str, Any]:
        self.store.initialize()
        worker = worker_id or f"worker:{os.getpid()}"
        processed: list[dict[str, Any]] = []
        with DaemonLock(self.store.state_dir):
            recovered = self.store.recover_stale_queue_items(stale_after_s=stale_after_s)
            for _ in range(max(0, int(limit))):
                item = self.store.claim_next_queue_item(worker)
                if not item:
                    break
                processed.append(self._execute_item(item, executor))
        return {
            "processed": processed,
            "recovered": recovered,
            "stats": self.store.queue_stats(),
        }

    def _execute_item(self, item: dict[str, Any], executor: RunExecutor) -> dict[str, Any]:
        queue_id = str(item["id"])
        try:
            result = executor(
                RunRequest(
                    message=str(item["message"]),
                    state_dir=str(self.store.state_dir),
                    conversation_id=item.get("conversation_id"),
                    mission_id=item.get("mission_id"),
                )
            )
        except Exception as exc:
            self.store.complete_queue_item(queue_id, "failed", error=str(exc))
            return {"id": queue_id, "status": "failed", "error": str(exc)}
        self.store.complete_queue_item(queue_id, "completed", run_id=result.run_id)
        return {"id": queue_id, "status": "completed", "run_id": result.run_id}


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
