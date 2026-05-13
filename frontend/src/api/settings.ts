import { API_BASE, readJson } from "./http";
import type { LlmModelsResponse } from "./types";

export async function getLlmModels(): Promise<LlmModelsResponse> {
  const response = await fetch(`${API_BASE}/settings/llm/models`);
  return readJson(response, "LLM settings");
}
