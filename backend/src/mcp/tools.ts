import { buildAnalysisTools } from "./toolGroups/analysis.js";
import { buildCoreTools } from "./toolGroups/core.js";
import { buildGraphTools } from "./toolGroups/graph.js";
import { buildGraphRagTools } from "./toolGroups/graphrag.js";
import { buildRepositoryTools } from "./toolGroups/repositories.js";
import { buildWikiTools } from "./toolGroups/wiki.js";
import { type ToolBuildOptions, type ToolSpec } from "./toolkit.js";

export { ToolSpec, type ToolHandler } from "./toolkit.js";

export function buildTools(
  runtime: ToolBuildOptions,
): Record<string, ToolSpec> {
  const tools = [
    ...buildCoreTools(runtime),
    ...buildRepositoryTools(runtime),
    ...buildAnalysisTools(runtime),
    ...buildGraphTools(runtime),
    ...buildGraphRagTools(runtime),
    ...buildWikiTools(runtime),
  ];
  return Object.fromEntries(tools.map((tool) => [tool.name, tool]));
}
