import {
  graphAffected,
  graphCommunitiesList,
  graphExplore,
  graphImpact,
  graphNodeContext,
  graphNodeRead,
  graphRelationships,
  graphResponse,
  graphSearch,
  graphStatus,
  graphTrace,
} from "../../graph/operations.js";
import { resolveRepo } from "../../services/repoResolver.js";
import {
  intArg,
  objectSchema,
  optionalString,
  repoSelectorSchema,
  requiredString,
  searchFilters,
  stringListArg,
  symbolSchema,
  tool,
  type ToolRuntime,
  type ToolSpec,
} from "../toolkit.js";

export function buildGraphTools({
  store,
  scanner,
  services,
}: ToolRuntime): ToolSpec[] {
  return [
    tool(
      "codewiki_graph_dump",
      "Return the full stored graph nodes, edges, communities, and community edges.",
      objectSchema({ repo: repoSelectorSchema() }),
      async (args) => {
        const repo = await resolveRepo(
          store,
          scanner,
          optionalString(args, "repo"),
        );
        return graphResponse(store, repo.id);
      },
    ),
    tool(
      "codewiki_graph_status",
      "Show graph index statistics for a repository.",
      objectSchema({ repo: repoSelectorSchema() }),
      async (args) => {
        const repo = await resolveRepo(
          store,
          scanner,
          optionalString(args, "repo"),
        );
        return graphStatus(store, repo.id);
      },
    ),
    tool(
      "codewiki_graph_search",
      "Search indexed code graph symbols by name, path, summary, or language.",
      objectSchema({
        repo: repoSelectorSchema(),
        query: { type: "string", description: "Search query." },
        type: { type: "string", description: "Optional node type filter." },
        language: { type: "string", description: "Optional language filter." },
        path: { type: "string", description: "Optional path substring." },
        name: { type: "string", description: "Optional name substring." },
        limit: { type: "integer", default: 20 },
      }),
      async (args) => {
        const repo = await resolveRepo(
          store,
          scanner,
          optionalString(args, "repo"),
        );
        const query = optionalString(args, "query") ?? "";
        return graphSearch(store, repo.id, query, searchFilters(args));
      },
    ),
    tool(
      "codewiki_graph_callers",
      "List graph nodes that call or reference a symbol.",
      objectSchema(
        {
          repo: repoSelectorSchema(),
          symbol: symbolSchema(),
          limit: { type: "integer", default: 20 },
        },
        ["symbol"],
      ),
      async (args) => {
        const repo = await resolveRepo(
          store,
          scanner,
          optionalString(args, "repo"),
        );
        return graphRelationships(
          store,
          repo.id,
          requiredString(args, "symbol"),
          "callers",
          intArg(args, "limit", 20),
        );
      },
    ),
    tool(
      "codewiki_graph_callees",
      "List graph nodes called or referenced by a symbol.",
      objectSchema(
        {
          repo: repoSelectorSchema(),
          symbol: symbolSchema(),
          limit: { type: "integer", default: 20 },
        },
        ["symbol"],
      ),
      async (args) => {
        const repo = await resolveRepo(
          store,
          scanner,
          optionalString(args, "repo"),
        );
        return graphRelationships(
          store,
          repo.id,
          requiredString(args, "symbol"),
          "callees",
          intArg(args, "limit", 20),
        );
      },
    ),
    tool(
      "codewiki_graph_impact",
      "Return the impact subgraph for changing a symbol.",
      objectSchema(
        {
          repo: repoSelectorSchema(),
          symbol: symbolSchema(),
          depth: { type: "integer", default: 2 },
        },
        ["symbol"],
      ),
      async (args) => {
        const repo = await resolveRepo(
          store,
          scanner,
          optionalString(args, "repo"),
        );
        return graphImpact(
          store,
          repo.id,
          requiredString(args, "symbol"),
          intArg(args, "depth", 2),
        );
      },
    ),
    tool(
      "codewiki_graph_explore",
      "Build source-section exploration context for a query.",
      objectSchema(
        {
          repo: repoSelectorSchema(),
          query: { type: "string", description: "Exploration query." },
          max_files: { type: "integer", default: 12 },
          max_nodes: { type: "integer", default: 160 },
        },
        ["query"],
      ),
      async (args) => {
        const repo = await resolveRepo(
          store,
          scanner,
          optionalString(args, "repo"),
        );
        return graphExplore(
          store,
          repo.id,
          requiredString(args, "query"),
          intArg(args, "max_nodes", 160),
          intArg(args, "max_files", 12),
        );
      },
    ),
    tool(
      "codewiki_graph_affected",
      "Find files and graph nodes affected by changed files.",
      objectSchema(
        {
          repo: repoSelectorSchema(),
          file_paths: {
            type: "array",
            items: { type: "string" },
            description: "Changed file paths relative to the repo.",
          },
        },
        ["file_paths"],
      ),
      async (args) => {
        const repo = await resolveRepo(
          store,
          scanner,
          optionalString(args, "repo"),
        );
        return graphAffected(store, repo.id, stringListArg(args, "file_paths"));
      },
    ),
    tool(
      "codewiki_context",
      "Build relevant source context for a task in one call.",
      objectSchema(
        {
          repo: repoSelectorSchema(),
          task: {
            type: "string",
            description: "Task, question, or code terms.",
          },
        },
        ["task"],
      ),
      async (args) => {
        const repo = await resolveRepo(
          store,
          scanner,
          optionalString(args, "repo"),
        );
        const task = requiredString(args, "task");
        const context = await graphExplore(
          store,
          repo.id,
          task,
          intArg(args, "max_nodes", 160),
          intArg(args, "max_files", 12),
        );
        return {
          ...context,
          task,
        };
      },
    ),
    tool(
      "codewiki_trace",
      "Trace a static call/reference path between two symbols.",
      objectSchema(
        {
          repo: repoSelectorSchema(),
          from_symbol: { type: "string", description: "Starting symbol." },
          to_symbol: { type: "string", description: "Destination symbol." },
          max_depth: { type: "integer", default: 8 },
        },
        ["from_symbol", "to_symbol"],
      ),
      async (args) => {
        const repo = await resolveRepo(
          store,
          scanner,
          optionalString(args, "repo"),
        );
        return graphTrace(
          store,
          repo.id,
          requiredString(args, "from_symbol"),
          requiredString(args, "to_symbol"),
          intArg(args, "max_depth", 8),
        );
      },
    ),
    tool(
      "codewiki_node",
      "Read one symbol plus callers and callees.",
      objectSchema({ repo: repoSelectorSchema(), symbol: symbolSchema() }, [
        "symbol",
      ]),
      async (args) => {
        const repo = await resolveRepo(
          store,
          scanner,
          optionalString(args, "repo"),
        );
        return graphNodeContext(store, repo.id, requiredString(args, "symbol"));
      },
    ),
    tool(
      "codewiki_graph_node_read",
      "Read a graph node and its adjacent edges by node id.",
      objectSchema(
        {
          repo: repoSelectorSchema(),
          node_id: { type: "string", description: "Graph node id." },
        },
        ["node_id"],
      ),
      async (args) => {
        const repo = await resolveRepo(
          store,
          scanner,
          optionalString(args, "repo"),
        );
        return graphNodeRead(store, repo.id, requiredString(args, "node_id"));
      },
    ),
    tool(
      "codewiki_communities_list",
      "List detected graph communities for a repository.",
      objectSchema({ repo: repoSelectorSchema() }),
      async (args) => {
        const repo = await resolveRepo(
          store,
          scanner,
          optionalString(args, "repo"),
        );
        return graphCommunitiesList(store, repo.id);
      },
    ),
    tool(
      "codewiki_communities_name",
      "Generate deterministic names and summaries for graph communities.",
      objectSchema({
        repo: repoSelectorSchema(),
        max_communities: { type: "integer", default: 40 },
      }),
      async (args) => {
        const repo = await resolveRepo(
          store,
          scanner,
          optionalString(args, "repo"),
        );
        return services.communityNaming.nameCommunities(repo.id, {
          maxCommunities: intArg(args, "max_communities", 40),
        });
      },
    ),
  ];
}
