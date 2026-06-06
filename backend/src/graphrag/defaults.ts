export type GraphRagRetrievalDefaults = {
  maxSourceChunks: number;
  contextTokenBudget: number;
};

export const DEFAULT_GRAPHRAG_MAX_SOURCE_CHUNKS = 20;
export const DEFAULT_GRAPHRAG_CONTEXT_TOKEN_BUDGET = 8000;

export const DEFAULT_GRAPHRAG_RETRIEVAL_DEFAULTS: GraphRagRetrievalDefaults = {
  maxSourceChunks: DEFAULT_GRAPHRAG_MAX_SOURCE_CHUNKS,
  contextTokenBudget: DEFAULT_GRAPHRAG_CONTEXT_TOKEN_BUDGET,
};

export function normalizeGraphRagRetrievalDefaults(
  defaults: Partial<GraphRagRetrievalDefaults> = {},
): GraphRagRetrievalDefaults {
  return {
    maxSourceChunks: positiveInt(
      defaults.maxSourceChunks,
      DEFAULT_GRAPHRAG_MAX_SOURCE_CHUNKS,
    ),
    contextTokenBudget: positiveInt(
      defaults.contextTokenBudget,
      DEFAULT_GRAPHRAG_CONTEXT_TOKEN_BUDGET,
    ),
  };
}

function positiveInt(value: number | undefined, fallback: number): number {
  return typeof value === "number" && Number.isInteger(value) && value > 0
    ? value
    : fallback;
}
