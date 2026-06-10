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
  save_path?: string;
  status_path?: string;
  running?: boolean;
  last_outcome?: string | null;
  last_run_source?: string | null;
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
    intervalMinutes: "180"
  };
}

export function autoDreamFormFromStatus(result: AutoDreamStatusResult | null): AutoDreamFormState {
  return {
    enabled: result?.enabled !== false,
    intervalMinutes: String(result?.interval_minutes || "180")
  };
}

export function autoDreamSavePayload(form: AutoDreamFormState) {
  const intervalMinutes = Number(form.intervalMinutes);
  return {
    enabled: form.enabled,
    interval_minutes: Number.isFinite(intervalMinutes) && intervalMinutes > 0 ? intervalMinutes : 180
  };
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
