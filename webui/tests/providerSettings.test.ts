import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { providerFormFromConfig, providerSavePayload, providerStatusText } from "../src/providerSettings.ts";

describe("provider settings form", () => {
  it("loads a redacted provider config without putting the secret into the input", () => {
    const form = providerFormFromConfig({
      configured: true,
      api_key_configured: true,
      config: {
        provider: "openai-compatible",
        base_url: "http://localhost:8000/v1",
        model: "memory-maintainer",
        api_key: "***",
        timeout_s: 12
      }
    });

    assert.equal(form.baseUrl, "http://localhost:8000/v1");
    assert.equal(form.model, "memory-maintainer");
    assert.equal(form.apiKey, "");
    assert.equal(form.timeoutS, "12");
  });

  it("omits a blank API key so saving does not clear the existing key", () => {
    const payload = providerSavePayload({
      provider: "openai-compatible",
      baseUrl: " http://localhost:8000/v1 ",
      model: " memory-maintainer ",
      apiKey: "",
      apiKeyEnv: "",
      timeoutS: "30"
    });

    assert.equal(payload.base_url, "http://localhost:8000/v1");
    assert.equal(payload.model, "memory-maintainer");
    assert.equal(payload.timeout_s, 30);
    assert.equal("api_key" in payload, false);
  });

  it("reports whether the effective config has an API key", () => {
    assert.equal(providerStatusText(null), "未加载");
    assert.equal(providerStatusText({ configured: false }), "未配置");
    assert.equal(providerStatusText({ configured: true, api_key_configured: true }), "已配置 Key");
  });
});
