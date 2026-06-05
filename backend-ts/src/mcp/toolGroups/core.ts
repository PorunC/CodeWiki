import { llmModelsPayload } from "../../presenters/payloads.js";
import {
  objectSchema,
  tool,
  type ToolRuntime,
  type ToolSpec,
} from "../toolkit.js";

export function buildCoreTools({ settings }: ToolRuntime): ToolSpec[] {
  return [
    tool(
      "codewiki_health",
      "Check that the CodeWiki MCP server is reachable.",
      objectSchema({}),
      () => ({
        status: "ok",
      }),
    ),
    tool(
      "codewiki_llm_models",
      "Show configured LLM routing profiles and model settings.",
      objectSchema({}),
      () => llmModelsPayload(settings),
    ),
  ];
}
