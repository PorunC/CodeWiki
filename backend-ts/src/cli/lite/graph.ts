import type { Command } from "commander";
import {
  liteContext,
  liteImpact,
  liteNode,
  liteQuery,
  liteRelationships,
  liteTrace,
} from "../../lite/operations.js";
import { output, parseLimit, runCli, type JsonOption } from "../runtime.js";

export function registerLiteGraphCommands(lite: Command): void {
  lite
    .command("query")
    .argument("[search]", "Search query", "")
    .argument("[path]", "Repository path", ".")
    .option("--type <type>", "Filter by graph node type")
    .option("--language <language>", "Filter by language")
    .option("--limit <limit>", "Maximum results", "20")
    .option("--json", "Print JSON output")
    .action(
      (
        search: string,
        path: string,
        options: {
          type?: string;
          language?: string;
          limit: string;
        } & JsonOption,
      ) => {
        runCli(() => {
          const filters: { type?: string; language?: string; limit: number } = {
            limit: parseLimit(options.limit),
          };
          if (options.type) {
            filters.type = options.type;
          }
          if (options.language) {
            filters.language = options.language;
          }
          const payload = liteQuery(path, search, filters);
          output(
            options.json,
            payload,
            payload.results
              .map(
                (hit) =>
                  `${hit.score.toFixed(2)}  ${hit.node.name} (${hit.node.type})  ${hit.node.file_path}`,
              )
              .join("\n"),
          );
        });
      },
    );

  lite
    .command("callers")
    .argument("<symbol>", "Symbol name or graph node id")
    .argument("[path]", "Repository path", ".")
    .option("--limit <limit>", "Maximum relationships", "20")
    .option("--json", "Print JSON output")
    .action(
      (
        symbol: string,
        path: string,
        options: { limit: string } & JsonOption,
      ) => {
        runCli(() => {
          const payload = liteRelationships(
            path,
            symbol,
            "callers",
            parseLimit(options.limit),
          );
          output(
            options.json,
            payload,
            formatRelationships(payload.relationships),
          );
        });
      },
    );

  lite
    .command("callees")
    .argument("<symbol>", "Symbol name or graph node id")
    .argument("[path]", "Repository path", ".")
    .option("--limit <limit>", "Maximum relationships", "20")
    .option("--json", "Print JSON output")
    .action(
      (
        symbol: string,
        path: string,
        options: { limit: string } & JsonOption,
      ) => {
        runCli(() => {
          const payload = liteRelationships(
            path,
            symbol,
            "callees",
            parseLimit(options.limit),
          );
          output(
            options.json,
            payload,
            formatRelationships(payload.relationships),
          );
        });
      },
    );

  lite
    .command("impact")
    .argument("<symbol>", "Symbol name or graph node id")
    .argument("[path]", "Repository path", ".")
    .option("--depth <depth>", "Traversal depth", "2")
    .option("--json", "Print JSON output")
    .action(
      (
        symbol: string,
        path: string,
        options: { depth: string } & JsonOption,
      ) => {
        runCli(() => {
          const payload = liteImpact(path, symbol, parseLimit(options.depth));
          output(
            options.json,
            payload,
            `Impact: ${payload.nodes.length} nodes, ${payload.edges.length} edges`,
          );
        });
      },
    );

  lite
    .command("context")
    .argument("<task>", "Task, question, or code terms")
    .argument("[path]", "Repository path", ".")
    .option("--max-files <maxFiles>", "Maximum source sections", "12")
    .option("--max-nodes <maxNodes>", "Maximum graph nodes", "160")
    .option("--json", "Print JSON output")
    .action(
      (
        task: string,
        path: string,
        options: { maxFiles: string; maxNodes: string } & JsonOption,
      ) => {
        runCli(() => {
          const payload = liteContext(
            path,
            task,
            parseLimit(options.maxFiles),
            parseLimit(options.maxNodes),
          );
          output(options.json, payload, payload.text);
        });
      },
    );

  lite
    .command("trace")
    .argument("<fromSymbol>", "Starting symbol name or node id")
    .argument("<toSymbol>", "Target symbol name or node id")
    .argument("[path]", "Repository path", ".")
    .option("--max-depth <maxDepth>", "Maximum graph traversal depth", "8")
    .option("--json", "Print JSON output")
    .action(
      (
        fromSymbol: string,
        toSymbol: string,
        path: string,
        options: { maxDepth: string } & JsonOption,
      ) => {
        runCli(() => {
          const payload = liteTrace(
            path,
            fromSymbol,
            toSymbol,
            parseLimit(options.maxDepth),
          );
          output(options.json, payload, payload.text);
        });
      },
    );

  lite
    .command("node")
    .argument("<symbol>", "Symbol name or graph node id")
    .argument("[path]", "Repository path", ".")
    .option("--no-code", "Omit source snippets")
    .option("--json", "Print JSON output")
    .action(
      (
        symbol: string,
        path: string,
        options: { code?: boolean } & JsonOption,
      ) => {
        runCli(() => {
          const payload = liteNode(path, symbol, options.code !== false);
          output(options.json, payload, payload.text);
        });
      },
    );
}

function formatRelationships(
  relationships: Array<{
    source: { id: string; name: string; type: string };
    target: { id: string; name: string; type: string };
    edge: { type: string };
  }>,
): string {
  return relationships
    .map((relationship) => {
      const source = relationship.source.name || relationship.source.id;
      const target = relationship.target.name || relationship.target.id;
      return `${source} (${relationship.source.type}) -[${relationship.edge.type}]-> ${target} (${relationship.target.type})`;
    })
    .join("\n");
}
