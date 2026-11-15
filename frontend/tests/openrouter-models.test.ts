import { test } from "node:test";
import assert from "node:assert/strict";
import { GET } from "../src/app/api/openrouter/models/route";
import { formatTemplateTemperature, readExpertTemplates } from "../src/lib/expert-templates";

test("model catalog includes text models regardless of temperature support", async () => {
  const originalFetch = globalThis.fetch;
  let requestUrl = "";
  globalThis.fetch = (async (url) => {
    requestUrl = String(url);
    return Response.json({ data: [
      { id: "openai/gpt-6-luna", name: "GPT-6 Luna", context_length: 1000, supported_parameters: ["response_format"] },
      { id: "other/model", name: "Other model", context_length: 2000, supported_parameters: ["temperature"] },
      { id: "other/unknown", name: "Unknown", context_length: 3000 },
    ] });
  }) as typeof fetch;
  try {
    const response = await GET();
    const { models } = await response.json();
    assert.equal(new URL(requestUrl).searchParams.get("output_modalities"), "text");
    assert.equal(new URL(requestUrl).searchParams.has("supported_parameters"), false);
    assert.deepEqual(models.map((model: { supportsTemperature: boolean | null }) => model.supportsTemperature), [false, true, null]);
    assert.equal(models[0].id, "openai/gpt-6-luna");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("saved templates retain numeric and provider-default temperature settings", () => {
  const oldWindow = globalThis.window;
  const template = { id: "one", agent: "tutor", name: "Test", prompts: { analysis: "a", lesson: "b", questions: "c" }, model: "configured", temperature: 0.2 };
  const localStorage = { getItem: () => JSON.stringify([template, { ...template, id: "two", temperature: null }]) };
  Object.assign(globalThis, { window: { localStorage } });
  try {
    const templates = readExpertTemplates();
    assert.deepEqual(templates.map((item) => item.temperature), [0.2, null]);
    assert.deepEqual(templates.map((item) => formatTemplateTemperature(item.temperature)), ["0.2", "Provider default"]);
  } finally {
    Object.assign(globalThis, { window: oldWindow });
  }
});
