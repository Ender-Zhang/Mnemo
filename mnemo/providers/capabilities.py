from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping


PromptCacheStrategy = Literal["none", "automatic_prefix", "cache_control", "local_prefix"]
ToolCallFallbackMode = Literal["provider_native_tools", "text_only"]


@dataclass(frozen=True)
class ProviderCapabilities:
    provider: str
    adapter: str
    adapter_version: str
    model: str | None
    supports_streaming: bool
    supports_native_tools: bool
    supports_tool_bundle_epochs: bool
    prompt_cache_strategy: PromptCacheStrategy
    cache_control_surfaces: tuple[str, ...]
    supports_prompt_cache_key: bool
    tool_schema_cache_strategy: str
    context_window_tokens: int | None
    context_window_source: str
    fallback_modes: tuple[ToolCallFallbackMode, ...]
    notes: tuple[str, ...] = ()

    def metadata(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "adapter": self.adapter,
            "adapter_version": self.adapter_version,
            "model": self.model,
            "supports_streaming": self.supports_streaming,
            "supports_native_tools": self.supports_native_tools,
            "supports_tool_bundle_epochs": self.supports_tool_bundle_epochs,
            "prompt_cache_strategy": self.prompt_cache_strategy,
            "cache_control_surfaces": list(self.cache_control_surfaces),
            "supports_prompt_cache_key": self.supports_prompt_cache_key,
            "tool_schema_cache_strategy": self.tool_schema_cache_strategy,
            "context_window_tokens": self.context_window_tokens,
            "context_window_source": self.context_window_source,
            "fallback_modes": list(self.fallback_modes),
            "notes": list(self.notes),
        }

    def cache_plan(self, tool_bundle: Mapping[str, Any] | None = None) -> dict[str, Any]:
        plan: dict[str, Any] = {
            "strategy": self.prompt_cache_strategy,
            "cache_control_surfaces": list(self.cache_control_surfaces),
            "prompt_cache_key_supported": self.supports_prompt_cache_key,
            "tool_schema_cache_strategy": self.tool_schema_cache_strategy,
            "context_window_tokens": self.context_window_tokens,
            "context_window_source": self.context_window_source,
            "boundaries": _cache_boundaries(self.prompt_cache_strategy),
        }
        if tool_bundle:
            plan["tool_bundle"] = {
                "bundle_id": tool_bundle.get("bundle_id"),
                "epoch": tool_bundle.get("epoch"),
                "profile": tool_bundle.get("profile"),
                "provider_adapter_version": tool_bundle.get("provider_adapter_version"),
                "schema_serializer_version": tool_bundle.get("schema_serializer_version"),
                "cache_bust_reason": tool_bundle.get("cache_bust_reason"),
            }
        return plan


def provider_capabilities(provider: str, *, model: str | None = None) -> ProviderCapabilities:
    normalized = _normalize_provider(provider)
    if normalized == "openai-compatible":
        return ProviderCapabilities(
            provider="openai-compatible",
            adapter="openai",
            adapter_version="openai.v1",
            model=model,
            supports_streaming=True,
            supports_native_tools=True,
            supports_tool_bundle_epochs=True,
            prompt_cache_strategy="automatic_prefix",
            cache_control_surfaces=(),
            supports_prompt_cache_key=False,
            tool_schema_cache_strategy="stable_tool_bundle",
            context_window_tokens=_model_context_window("openai-compatible", model),
            context_window_source=_model_context_source("openai-compatible", model),
            fallback_modes=("provider_native_tools", "text_only"),
            notes=(
                "OpenAI-compatible endpoints vary by deployment; unknown model limits stay unset.",
            ),
        )
    if normalized == "anthropic":
        return ProviderCapabilities(
            provider="anthropic",
            adapter="anthropic",
            adapter_version="anthropic.v1",
            model=model,
            supports_streaming=True,
            supports_native_tools=True,
            supports_tool_bundle_epochs=True,
            prompt_cache_strategy="cache_control",
            cache_control_surfaces=("system", "tools", "messages"),
            supports_prompt_cache_key=False,
            tool_schema_cache_strategy="cache_control",
            context_window_tokens=_model_context_window("anthropic", model),
            context_window_source=_model_context_source("anthropic", model),
            fallback_modes=("provider_native_tools", "text_only"),
            notes=(
                "Cache-control injection is a provider-adapter concern; registry only exposes the plan.",
            ),
        )
    if normalized == "local":
        return ProviderCapabilities(
            provider="local",
            adapter="local",
            adapter_version="local.v1",
            model=model,
            supports_streaming=True,
            supports_native_tools=True,
            supports_tool_bundle_epochs=True,
            prompt_cache_strategy="local_prefix",
            cache_control_surfaces=(),
            supports_prompt_cache_key=False,
            tool_schema_cache_strategy="stable_tool_bundle",
            context_window_tokens=None,
            context_window_source="not_applicable",
            fallback_modes=("provider_native_tools", "text_only"),
        )
    adapter = _safe_identifier(normalized)
    return ProviderCapabilities(
        provider=adapter,
        adapter=adapter,
        adapter_version=f"{adapter}.v1",
        model=model,
        supports_streaming=True,
        supports_native_tools=True,
        supports_tool_bundle_epochs=True,
        prompt_cache_strategy="none",
        cache_control_surfaces=(),
        supports_prompt_cache_key=False,
        tool_schema_cache_strategy="stable_tool_bundle",
        context_window_tokens=None,
        context_window_source="unknown_model" if model else "unknown",
        fallback_modes=("provider_native_tools", "text_only"),
        notes=("Unknown provider; capability metadata is conservative.",),
    )


def provider_capabilities_for_adapter(adapter: Any) -> ProviderCapabilities:
    config = getattr(adapter, "config", None)
    model = getattr(config, "model", None)
    if not isinstance(model, str):
        model = None
    return provider_capabilities(str(getattr(adapter, "name", "unknown")), model=model)


def usage_cache_metrics(provider: str, usage: Mapping[str, Any]) -> dict[str, int]:
    metrics: dict[str, int] = {}
    normalized = _normalize_provider(provider)
    if normalized == "openai-compatible":
        cached = _nested_int(usage, "prompt_tokens_details", "cached_tokens")
        if cached is None:
            cached = _nested_int(usage, "input_tokens_details", "cached_tokens")
        if cached is not None:
            metrics["cached_input_tokens"] = cached
    elif normalized == "anthropic":
        cache_read = _optional_int(usage.get("cache_read_input_tokens"))
        cache_creation = _optional_int(usage.get("cache_creation_input_tokens"))
        if cache_read is not None:
            metrics["cached_input_tokens"] = cache_read
        if cache_creation is not None:
            metrics["cache_creation_input_tokens"] = cache_creation
    return metrics


def _normalize_provider(provider: str) -> str:
    value = (provider or "unknown").strip().lower().replace("_", "-")
    if value in {"openai", "openai-compatible", "openai-compatible-chat"}:
        return "openai-compatible"
    return value or "unknown"


def _safe_identifier(value: str) -> str:
    identifier = "".join(
        char if char.isalnum() or char in {"-", "."} else "-"
        for char in value.strip().lower()
    )
    return identifier.strip("-.") or "unknown"


def _cache_boundaries(strategy: PromptCacheStrategy) -> list[str]:
    if strategy in {"automatic_prefix", "cache_control", "local_prefix"}:
        return ["core", "user_profile", "tool_bundle", "daily_context"]
    return []


def _model_context_window(provider: str, model: str | None) -> int | None:
    normalized_model = (model or "").lower()
    if provider == "anthropic" and normalized_model.startswith("claude-"):
        return 200_000
    return None


def _model_context_source(provider: str, model: str | None) -> str:
    if _model_context_window(provider, model) is not None:
        return "provider_family_default"
    if model:
        return "unknown_model"
    return "unknown"


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _nested_int(usage: Mapping[str, Any], key: str, nested_key: str) -> int | None:
    nested = usage.get(key)
    if not isinstance(nested, Mapping):
        return None
    return _optional_int(nested.get(nested_key))
