from __future__ import annotations

L1_SNAPSHOT_FILENAME = "l1-memory-snapshot.json"
DREAM_REPORTS_DIRNAME = "dream-reports"
DREAM_LATEST_FILENAME = "latest.json"
W0_MEMORY_RETENTION = "memory_candidate"
DEFAULT_W0_CONFIDENCE = 0.62
MIN_W0_CANDIDATE_CHARS = 12
MEMORY_SEARCH_SCOPES = {"memory", "stable", "sessions", "all"}
PRIVATE_DELETE_SUMMARY = "[private memory deleted]"
PRIVATE_DELETE_TOMBSTONE_REASON = "private_delete"
PRIVATE_DELETE_RULE = (
    "Private delete: do not recreate this memory from historical context unless the user explicitly restates it."
)

_POSITIVE_MARKERS = (
    " prefer ",
    " prefers ",
    " like ",
    " likes ",
    " want ",
    " wants ",
    " use ",
    " uses ",
)
_NEGATIVE_MARKERS = (
    " dislike ",
    " dislikes ",
    " avoid ",
    " avoids ",
    " do not ",
    " does not ",
    " don't ",
    " never ",
    " hate ",
    " hates ",
)
_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "user",
    "prefers",
    "prefer",
    "likes",
    "like",
    "dislikes",
    "dislike",
    "wants",
    "want",
    "uses",
    "use",
    "does",
    "not",
    "dont",
    "never",
}
