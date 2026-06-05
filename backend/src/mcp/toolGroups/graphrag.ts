import { retrievalTracePayload } from "../../graphrag/payloads.js";
import { resolveRepo } from "../../services/repoResolver.js";
import {
  boolArg,
  intArg,
  objectSchema,
  optionalString,
  repoSelectorSchema,
  requiredString,
  tool,
  type ToolRuntime,
  type ToolSpec,
} from "../toolkit.js";

export function buildGraphRagTools({
  store,
  scanner,
  services,
}: ToolRuntime): ToolSpec[] {
  return [
    tool(
      "codewiki_graphrag_build",
      "Build GraphRAG source chunks for a repository.",
      objectSchema({
        repo: repoSelectorSchema(),
        embeddings: { type: "boolean", default: false },
      }),
      (args) => {
        const repo = resolveRepo(store, scanner, optionalString(args, "repo"));
        return services.graphRag.buildIndex(repo.id, {
          includeEmbeddings: boolArg(args, "embeddings", false),
        });
      },
    ),
    tool(
      "codewiki_retrieve_context",
      "Retrieve source context for a repository question without calling an LLM.",
      objectSchema(
        {
          repo: repoSelectorSchema(),
          query: {
            type: "string",
            description: "Question or topic to retrieve.",
          },
          limit: { type: "integer", default: 10 },
          max_hops: { type: "integer", default: 2 },
          include_embeddings: { type: "boolean", default: false },
        },
        ["query"],
      ),
      async (args) => {
        const repo = resolveRepo(store, scanner, optionalString(args, "repo"));
        const query = requiredString(args, "query");
        const trace = await services.graphRag.retrieve(repo.id, query, {
          limit: intArg(args, "limit", 10),
          maxHops: intArg(args, "max_hops", 2),
          includeEmbeddings: boolArg(args, "include_embeddings", false),
        });
        return retrievalTracePayload(trace);
      },
    ),
    tool(
      "codewiki_ask",
      "Ask a source-grounded local question about a repository.",
      objectSchema(
        {
          repo: repoSelectorSchema(),
          question: { type: "string", description: "Question to answer." },
        },
        ["question"],
      ),
      (args) =>
        services.questionAnswerer.answerWithLlmFallback(
          resolveRepo(store, scanner, optionalString(args, "repo")).id,
          {
            question: requiredString(args, "question"),
            max_hops: intArg(args, "max_hops", 2),
            include_sources: true,
            include_graph: true,
          },
        ),
    ),
  ];
}
