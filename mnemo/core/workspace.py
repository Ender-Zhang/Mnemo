from __future__ import annotations

from pathlib import Path

from .config import DEFAULT_STATE_DIR


def default_workspace_root(state_dir: str | Path = DEFAULT_STATE_DIR) -> Path:
    return Path(state_dir).expanduser().resolve() / "workspace"


def resolve_workspace_root(workspace_root: str | Path | None, state_dir: str | Path = DEFAULT_STATE_DIR) -> Path:
    if workspace_root is not None:
        return Path(workspace_root).expanduser().resolve()
    return default_workspace_root(state_dir)
