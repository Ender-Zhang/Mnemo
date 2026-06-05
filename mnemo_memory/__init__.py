from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["MemoryClient", "memory_api_schema", "__version__"]


def __getattr__(name: str):
    if name == "MemoryClient":
        from .sdk import MemoryClient

        return MemoryClient
    if name == "memory_api_schema":
        from .sdk import memory_api_schema

        return memory_api_schema
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
