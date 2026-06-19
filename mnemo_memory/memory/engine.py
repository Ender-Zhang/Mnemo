from __future__ import annotations

from typing import Any

from .base import MemoryStoreAccessMixin
from .constants import (
    DEFAULT_W0_CONFIDENCE,
    DREAM_LATEST_FILENAME,
    DREAM_REPORTS_DIRNAME,
    L1_SNAPSHOT_FILENAME,
    MEMORY_SEARCH_SCOPES,
    MIN_W0_CANDIDATE_CHARS,
    PRIVATE_DELETE_RULE,
    PRIVATE_DELETE_SUMMARY,
    PRIVATE_DELETE_TOMBSTONE_REASON,
    W0_MEMORY_RETENTION,
)
from .curation import MemoryCurationMixin
from .dream import MemoryDreamMixin
from .health import MemoryHealthMixin
from .learning import MemoryLearningMixin
from .plans import MemoryPlanMixin
from .recall import MemoryRecallMixin


class MemoryEngine(
    MemoryStoreAccessMixin,
    MemoryRecallMixin,
    MemoryLearningMixin,
    MemoryCurationMixin,
    MemoryPlanMixin,
    MemoryHealthMixin,
    MemoryDreamMixin,
):
    def __init__(self, store: Any, *, embedding_provider: Any | None = None):
        self.store = store
        self._embedding_provider = embedding_provider


__all__ = [
    "MemoryEngine",
    "DEFAULT_W0_CONFIDENCE",
    "DREAM_LATEST_FILENAME",
    "DREAM_REPORTS_DIRNAME",
    "L1_SNAPSHOT_FILENAME",
    "MEMORY_SEARCH_SCOPES",
    "MIN_W0_CANDIDATE_CHARS",
    "PRIVATE_DELETE_RULE",
    "PRIVATE_DELETE_SUMMARY",
    "PRIVATE_DELETE_TOMBSTONE_REASON",
    "W0_MEMORY_RETENTION",
]
