from __future__ import annotations

import re
from typing import Any

from .utils import _bounded_confidence, _normalize_space


QUALITY_WRITE_THRESHOLD = 0.68
QUALITY_DRAFT_THRESHOLD = 0.5


def score_memory_quality(
    claim: str,
    evidence: list[dict[str, Any]] | None = None,
    *,
    write_threshold: float | None = None,
    draft_threshold: float | None = None,
) -> dict[str, Any]:
    text = _normalize_space(claim)
    evidence_items = [item for item in evidence or [] if isinstance(item, dict)]
    scores = {
        "specificity": _specificity_score(text),
        "personalization": _personalization_score(text),
        "persistence": _persistence_score(text),
        "actionability": _actionability_score(text),
        "verifiability": _verifiability_score(evidence_items),
    }
    weighted_avg = round(
        (
            scores["specificity"] * 0.22
            + scores["personalization"] * 0.18
            + scores["persistence"] * 0.2
            + scores["actionability"] * 0.25
            + scores["verifiability"] * 0.15
        ),
        3,
    )
    return {
        "kind": "memory_quality",
        "scores": {key: round(value, 3) for key, value in scores.items()},
        "weighted_avg": weighted_avg,
        "recommendation": _quality_recommendation(weighted_avg, write_threshold, draft_threshold),
        "reason": _quality_reason(scores, weighted_avg),
    }


def append_quality_evidence(evidence: list[dict[str, Any]], quality: dict[str, Any]) -> list[dict[str, Any]]:
    return [*evidence, quality]


def compact_quality_signal(quality: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(quality, dict):
        return None
    return {
        "weighted_avg": quality.get("weighted_avg"),
        "recommendation": quality.get("recommendation"),
        "scores": quality.get("scores", {}),
        "reason": quality.get("reason"),
    }


def candidate_quality_signal(candidate: dict[str, Any]) -> dict[str, Any] | None:
    evidence = candidate.get("evidence")
    if not isinstance(evidence, list):
        return None
    for item in reversed(evidence):
        if isinstance(item, dict) and item.get("kind") == "memory_quality":
            return item
    return None


def low_quality_status(quality: dict[str, Any] | None) -> str | None:
    if not isinstance(quality, dict):
        return None
    recommendation = str(quality.get("recommendation") or "")
    if recommendation == "discard":
        return "rejected"
    if recommendation == "draft":
        return "needs_review"
    return None


def _quality_recommendation(
    weighted_avg: float,
    write_threshold: float | None = None,
    draft_threshold: float | None = None,
) -> str:
    write_at = QUALITY_WRITE_THRESHOLD if write_threshold is None else write_threshold
    draft_at = QUALITY_DRAFT_THRESHOLD if draft_threshold is None else draft_threshold
    if weighted_avg >= write_at:
        return "write"
    if weighted_avg >= draft_at:
        return "draft"
    return "discard"


def _quality_reason(scores: dict[str, float], weighted_avg: float) -> str:
    weak = [
        key
        for key, value in sorted(scores.items(), key=lambda item: item[1])
        if value < 0.55
    ][:2]
    if not weak:
        return "specific and actionable enough for model-led memory consolidation"
    return f"weak {', '.join(weak)}; quality={weighted_avg:.2f}"


def _specificity_score(text: str) -> float:
    if not text:
        return 0.0
    # CJK has no word delimiters, so the latin tokenizer collapses a whole
    # sentence into one "term" and scores a concrete fact (e.g. 老家是安徽安庆)
    # as if it were a single vague word. Count distinct CJK characters as
    # term-equivalents (~2 chars per word) so specificity is language-fair.
    latin_terms = [term for term in _terms(text) if not _is_all_cjk(term)]
    cjk_units = len(set(_cjk_chars(text))) / 2.0
    diversity = len(set(latin_terms)) + cjk_units
    score = min(1.0, 0.22 + (diversity / 8.0))
    if _has_specific_marker(text):
        score += 0.18
    if _has_generic_marker(text):
        score -= 0.25
    return _bounded_confidence(score, 0.0)


def _personalization_score(text: str) -> float:
    lowered = f" {text.casefold()} "
    score = 0.35
    if any(marker in lowered for marker in _PERSONAL_MARKERS):
        score += 0.35
    if _has_profile_marker(text):
        score += 0.25
    if any(marker in lowered for marker in _PREFERENCE_MARKERS | _GOAL_MARKERS | _BOUNDARY_MARKERS):
        score += 0.15
    if any(marker in lowered for marker in _COMMON_KNOWLEDGE_MARKERS):
        score -= 0.35
    return _bounded_confidence(score, 0.0)


def _persistence_score(text: str) -> float:
    lowered = f" {text.casefold()} "
    score = 0.48
    if any(marker in lowered for marker in _STABLE_MARKERS | _PREFERENCE_MARKERS | _GOAL_MARKERS | _BOUNDARY_MARKERS) or _has_profile_marker(text):
        score += 0.3
    if any(marker in lowered for marker in _EPHEMERAL_MARKERS):
        score -= 0.35
    if _has_generic_marker(text):
        score -= 0.25
    if " may " in lowered or " might " in lowered or "可能" in lowered:
        score -= 0.18
    return _bounded_confidence(score, 0.0)


def _actionability_score(text: str) -> float:
    lowered = f" {text.casefold()} "
    score = 0.3
    if any(marker in lowered for marker in _ACTION_MARKERS | _PREFERENCE_MARKERS | _GOAL_MARKERS | _BOUNDARY_MARKERS) or _has_profile_marker(text):
        score += 0.38
    if _has_domain_marker(text):
        score += 0.15
    if _has_generic_marker(text):
        score -= 0.25
    return _bounded_confidence(score, 0.0)


def _verifiability_score(evidence: list[dict[str, Any]]) -> float:
    if not evidence:
        return 0.42
    score = 0.55
    for item in evidence[:6]:
        if any(str(item.get(key) or "").strip() for key in ("text", "quote", "snippet", "content", "summary")):
            score += 0.22
            break
    if any(str(item.get(key) or "").strip() for item in evidence[:6] for key in ("run_id", "message_id", "id", "url", "path")):
        score += 0.16
    return _bounded_confidence(score, 0.0)


def _terms(text: str) -> list[str]:
    return [
        token.casefold()
        for token in re.findall(r"[\w][\w.-]*", text, flags=re.UNICODE)
        if len(token) >= 2 and token.casefold() not in _QUALITY_STOPWORDS
    ]


def _is_cjk(ch: str) -> bool:
    return (
        "一" <= ch <= "鿿"  # CJK Unified Ideographs
        or "぀" <= ch <= "ヿ"  # Hiragana + Katakana
        or "가" <= ch <= "힯"  # Hangul syllables
    )


def _cjk_chars(text: str) -> list[str]:
    return [ch for ch in text if _is_cjk(ch)]


def _is_all_cjk(token: str) -> bool:
    return bool(token) and all(_is_cjk(ch) for ch in token)


def _has_specific_marker(text: str) -> bool:
    return bool(re.search(r"\b[A-Z][A-Za-z0-9_.-]{1,}\b|\b\d+\b", text))


def _has_domain_marker(text: str) -> bool:
    lowered = text.casefold()
    return any(marker in lowered for marker in _DOMAIN_MARKERS)


def _has_generic_marker(text: str) -> bool:
    lowered = f" {text.casefold()} "
    return any(marker in lowered for marker in _GENERIC_MARKERS)


def _has_profile_marker(text: str) -> bool:
    lowered = text.casefold()
    return any(marker in lowered for marker in _PROFILE_MARKERS)


_QUALITY_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "user",
    "this",
    "that",
    "thing",
    "things",
    "stuff",
    "mentioned",
}

_PERSONAL_MARKERS = {
    " user ",
    " i ",
    " my ",
    " me ",
    " 用户",
    " 我",
}

_PREFERENCE_MARKERS = {
    " prefer ",
    " prefers ",
    " preference ",
    " likes ",
    " like ",
    " wants ",
    " want ",
    " values ",
    " value ",
    " 偏好",
    " 喜欢",
}

_GOAL_MARKERS = {
    " goal ",
    " goals ",
    " plan ",
    " plans ",
    " learning ",
    " building ",
    " working on ",
    " 目标",
    " 计划",
    " 学习",
}

_BOUNDARY_MARKERS = {
    " avoid ",
    " avoids ",
    " dislike ",
    " dislikes ",
    " never ",
    " do not ",
    " don't ",
    " boundary ",
    " constraint ",
    " 避免",
    " 不要",
}

_STABLE_MARKERS = {
    " name ",
    " timezone ",
    " role ",
    " works ",
    " uses ",
    " usually ",
    " always ",
    " often ",
    " tends ",
    " style ",
    " habit ",
    " 名字",
    " 时区",
    " 通常",
    " 习惯",
}

_PROFILE_MARKERS = {
    "address",
    "home address",
    "mailing address",
    "private address",
    "email",
    "e-mail",
    "phone",
    "phone number",
    "mobile",
    "birthday",
    "birth date",
    "date of birth",
    "legal name",
    "real name",
    "passport",
    "ssn",
    "hometown",
    "birthplace",
    "born in",
    "grew up in",
    "地址",
    "住址",
    "家庭住址",
    "邮箱",
    "邮件",
    "电话",
    "手机",
    "生日",
    "出生日期",
    "真实姓名",
    "身份证",
    "护照",
    "老家",
    "家乡",
    "籍贯",
    "祖籍",
    "出生地",
    "出生于",
}

_ACTION_MARKERS = {
    " update ",
    " updates ",
    " communicate ",
    " communication ",
    " code ",
    " coding ",
    " test ",
    " tests ",
    " design ",
    " docs ",
    " deployment ",
    " review ",
    " tool ",
    " tools ",
    " 输出",
    " 代码",
    " 测试",
    " 设计",
}

_EPHEMERAL_MARKERS = {
    " today ",
    " tomorrow ",
    " yesterday ",
    " now ",
    " temporary ",
    " scratchpad ",
    " mood ",
    " just ",
    " 今天",
    " 明天",
    " 临时",
    " 刚刚",
}

_GENERIC_MARKERS = {
    " likes things ",
    " likes stuff ",
    " prefers things ",
    " prefers stuff ",
    " good things ",
    " bad things ",
    " mentioned something ",
}

_COMMON_KNOWLEDGE_MARKERS = {
    " python is ",
    " rust is ",
    " javascript is ",
    " llm is ",
    " ai is ",
}

_DOMAIN_MARKERS = {
    "python",
    "rust",
    "typescript",
    "react",
    "openai",
    "anthropic",
    "mnemo",
    "trellis",
    "pytest",
    "markdown",
    "api",
    "cli",
    "frontend",
    "backend",
}
