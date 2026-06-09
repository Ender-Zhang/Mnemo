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
};

export function emptyProviderForm(): ProviderFormState {
  return {
    provider: "openai-compatible",
    baseUrl: "",
    model: "memory-maintainer",
    apiKey: "",
    apiKeyEnv: "",
    timeoutS: "30"
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
    timeoutS: String(config.timeout_s || "30")
  };
}

export function providerSavePayload(form: ProviderFormState) {
  const payload: Record<string, unknown> = {
    provider: form.provider.trim() || "openai-compatible",
    base_url: form.baseUrl.trim(),
    model: form.model.trim(),
    api_key_env: form.apiKeyEnv.trim()
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
