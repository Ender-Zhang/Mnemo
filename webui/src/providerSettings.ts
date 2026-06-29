export type ProviderConfigResult = {
  kind?: "memory_provider_config";
  configured?: boolean;
  api_key_configured?: boolean;
  save_path?: string;
  config?: {
    provider?: string | null;
    base_url?: string | null;
    model?: string | null;
    api_key?: string | null;
    api_key_env?: string | null;
    timeout_s?: number | string | null;
    thinking_enabled?: boolean | number | string | null;
    config_path?: string | null;
  };
};

export type ProviderFormState = {
  provider: string;
  baseUrl: string;
  model: string;
  apiKey: string;
  apiKeyEnv: string;
  timeoutS: string;
  thinkingEnabled: boolean;
};

export type AutoDreamStatusResult = {
  kind?: "memory_auto_dream_status";
  enabled?: boolean;
  interval_minutes?: number | string | null;
  limit?: number | string | null;
  min_confidence?: number | string | null;
  local_fallback?: boolean;
  save_path?: string;
  status_path?: string;
  running?: boolean;
  last_outcome?: string | null;
  last_run_source?: string | null;
  last_run_mode?: string | null;
  last_checked_at?: number | null;
  last_config_updated_at?: number | null;
  last_started_at?: number | null;
  last_run_at?: number | null;
  last_finished_at?: number | null;
  last_duration_s?: number | null;
  next_run_at?: number | null;
  last_error?: string | null;
  last_result?: Record<string, unknown> | null;
  last_backlog?: Record<string, unknown> | null;
};

export type AutoDreamFormState = {
  enabled: boolean;
  intervalMinutes: string;
  localFallback: boolean;
};

export function emptyProviderForm(): ProviderFormState {
  return {
    provider: "openai-compatible",
    baseUrl: "",
    model: "memory-maintainer",
    apiKey: "",
    apiKeyEnv: "",
    timeoutS: "30",
    thinkingEnabled: false
  };
}

export function providerFormFromConfig(result: ProviderConfigResult | null): ProviderFormState {
  const config = result?.config || {};
  return {
    provider: String(config.provider || "openai-compatible"),
    baseUrl: String(config.base_url || ""),
    model: String(config.model || "memory-maintainer"),
    apiKey: "",
    apiKeyEnv: String(config.api_key_env || ""),
    timeoutS: String(config.timeout_s || "30"),
    thinkingEnabled: providerBool(config.thinking_enabled)
  };
}

export function providerSavePayload(form: ProviderFormState) {
  const payload: Record<string, unknown> = {
    provider: form.provider.trim() || "openai-compatible",
    base_url: form.baseUrl.trim(),
    model: form.model.trim(),
    api_key_env: form.apiKeyEnv.trim(),
    thinking_enabled: form.thinkingEnabled
  };
  const cleanKey = form.apiKey.trim();
  if (cleanKey && cleanKey !== "***") {
    payload.api_key = cleanKey;
  }
  const timeoutS = Number(form.timeoutS);
  if (Number.isFinite(timeoutS) && timeoutS > 0) {
    payload.timeout_s = timeoutS;
  }
  return payload;
}

export function providerStatusText(result: ProviderConfigResult | null) {
  if (!result) return "未加载";
  if (!result.configured) return "未配置";
  return result.api_key_configured ? "已配置 Key" : "已配置";
}

export function emptyAutoDreamForm(): AutoDreamFormState {
  return {
    enabled: true,
    intervalMinutes: "180",
    localFallback: false
  };
}

export function autoDreamFormFromStatus(result: AutoDreamStatusResult | null): AutoDreamFormState {
  return {
    enabled: result?.enabled !== false,
    intervalMinutes: String(result?.interval_minutes || "180"),
    localFallback: result?.local_fallback === true
  };
}

export function autoDreamSavePayload(form: AutoDreamFormState) {
  const intervalMinutes = Number(form.intervalMinutes);
  return {
    enabled: form.enabled,
    interval_minutes: Number.isFinite(intervalMinutes) && intervalMinutes > 0 ? intervalMinutes : 180,
    local_fallback: form.localFallback
  };
}

export type EmbeddingConfigResult = {
  kind?: string;
  enabled?: boolean;
  configured?: boolean;
  api_key_configured?: boolean;
  base_url?: string | null;
  model?: string | null;
  api_key_env?: string | null;
  save_path?: string;
};

export type EmbeddingStatusResult = {
  kind?: string;
  enabled?: boolean;
  configured?: boolean;
  active_count?: number;
  indexed_count?: number;
  stale_count?: number;
  reindexed?: number;
};

export type EmbeddingFormState = {
  enabled: boolean;
  baseUrl: string;
  model: string;
  apiKey: string;
  apiKeyEnv: string;
};

export function emptyEmbeddingForm(): EmbeddingFormState {
  return { enabled: false, baseUrl: "", model: "", apiKey: "", apiKeyEnv: "" };
}

export function embeddingFormFromConfig(result: EmbeddingConfigResult | null): EmbeddingFormState {
  return {
    enabled: result?.enabled === true,
    baseUrl: String(result?.base_url || ""),
    model: String(result?.model || ""),
    apiKey: "",
    apiKeyEnv: String(result?.api_key_env || "")
  };
}

export function embeddingSavePayload(form: EmbeddingFormState) {
  const payload: Record<string, unknown> = {
    enabled: form.enabled,
    base_url: form.baseUrl.trim(),
    model: form.model.trim(),
    api_key_env: form.apiKeyEnv.trim()
  };
  const cleanKey = form.apiKey.trim();
  if (cleanKey && cleanKey !== "***") {
    payload.api_key = cleanKey;
  }
  return payload;
}

export function embeddingStatusText(status: EmbeddingStatusResult | null) {
  if (!status) return "未加载";
  if (!status.enabled) return "未启用";
  if (!status.configured) return "未配置";
  return `${status.indexed_count ?? 0}/${status.active_count ?? 0} 已索引`;
}

export type TuningConfigResult = {
  kind?: string;
  quality_write_threshold?: number;
  quality_draft_threshold?: number;
  promote_min_confidence?: number;
  consolidate_lossy_summary?: boolean;
  require_user_scope?: boolean;
  save_path?: string;
};

export type TuningFormState = {
  writeThreshold: string;
  draftThreshold: string;
  minConfidence: string;
  lossySummary: boolean;
  requireUserScope: boolean;
};

export function emptyTuningForm(): TuningFormState {
  return { writeThreshold: "0.68", draftThreshold: "0.5", minConfidence: "0.7", lossySummary: false, requireUserScope: false };
}

export function tuningFormFromConfig(result: TuningConfigResult | null): TuningFormState {
  return {
    writeThreshold: String(result?.quality_write_threshold ?? "0.68"),
    draftThreshold: String(result?.quality_draft_threshold ?? "0.5"),
    minConfidence: String(result?.promote_min_confidence ?? "0.7"),
    lossySummary: Boolean(result?.consolidate_lossy_summary ?? false),
    requireUserScope: Boolean(result?.require_user_scope ?? false)
  };
}

export function tuningSavePayload(form: TuningFormState) {
  const payload: Record<string, unknown> = {};
  const fields: Array<[keyof TuningFormState, string]> = [
    ["writeThreshold", "quality_write_threshold"],
    ["draftThreshold", "quality_draft_threshold"],
    ["minConfidence", "promote_min_confidence"]
  ];
  for (const [formKey, apiKey] of fields) {
    const value = Number(form[formKey]);
    if (Number.isFinite(value)) {
      payload[apiKey] = Math.max(0, Math.min(1, value));
    }
  }
  payload.consolidate_lossy_summary = form.lossySummary;
  payload.require_user_scope = form.requireUserScope;
  return payload;
}

export function autoDreamStatusText(result: AutoDreamStatusResult | null) {
  if (!result) return "未加载";
  if (result.running) return "运行中";
  if (!result.enabled) return "已关闭";
  if (result.last_error) return "错误";
  if (result.last_outcome === "provider_required") return "等待 Provider";
  if (result.last_outcome === "no_backlog") return "无 backlog";
  if (result.last_outcome === "ran" || result.last_outcome === "manual_run") return "已运行";
  return `每 ${result.interval_minutes || 180} 分钟`;
}

function providerBool(value: unknown) {
  if (value === true) return true;
  if (typeof value === "number") return value !== 0;
  if (typeof value === "string") {
    return ["1", "true", "yes", "y", "on", "enabled", "enable"].includes(value.trim().toLowerCase());
  }
  return false;
}
