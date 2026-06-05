import type { Command } from "commander";
import {
  graphAffected,
  graphExplore,
  graphImpact,
  graphRelationships,
  graphSearch,
  graphStatus,
} from "../../graph/operations.js";
import {
  firstRepo,
  resolveRegisteredRepo as resolveRepo,
} from "../../services/repoResolver.js";
import {
  formatAffectedFiles,
  formatGraphStatus,
  formatImpact,
  formatRelationships,
  formatSearchResults,
} from "../formatters.js";
import {
  displayString,
  output,
  parseLimit,
  readStdinLines,
  runWithContext,
  type CliRuntime,
} from "../runtime.js";

export function registerGraphCommands(
  program: Command,
  runtime: CliRuntime,
): void {
  const graph = program
    .command("graph")
    .description("Inspect indexed graph data");

  graph
    .command("status")
    .argument("[repo]", "Repository id, id prefix, or name")
    .option("--json", "Print JSON output")
    .action((selector: string | undefined, options: { json?: boolean }) => {
      runWithContext(runtime, ({ store }) => {
        const repo = selector ? resolveRepo(store, selector) : firstRepo(store);
        const payload = graphStatus(store, repo.id);
        output(options.json, payload, formatGraphStatus(payload));
      });
    });

  graph
    .command("search")
    .argument("<query>", "Search query")
    .argument("[repo]", "Repository id, id prefix, or name")
    .option("--type <type>", "Filter by node type")
    .option("--language <language>", "Filter by language")
    .option("--path <path>", "Filter by file path substring")
    .option("--name <name>", "Filter by node name substring")
    .option("--limit <limit>", "Maximum results", "20")
    .option("--json", "Print JSON output")
    .action(
      (
        query: string,
        selector: string | undefined,
        options: {
          type?: string;
          language?: string;
          path?: string;
          name?: string;
          limit: string;
          json?: boolean;
        },
      ) => {
        runWithContext(runtime, ({ store }) => {
          const repo = selector
            ? resolveRepo(store, selector)
            : firstRepo(store);
          const payload = graphSearch(store, repo.id, query, {
            ...cliSearchFilters(options),
            limit: parseLimit(options.limit),
          });
          output(options.json, payload, formatSearchResults(payload));
        });
      },
    );

  graph
    .command("callers")
    .argument("<symbol>", "Symbol name or node id")
    .argument("[repo]", "Repository id, id prefix, or name")
    .option("--limit <limit>", "Maximum relationships", "20")
    .option("--json", "Print JSON output")
    .action(
      (
        symbol: string,
        selector: string | undefined,
        options: { limit: string; json?: boolean },
      ) => {
        runWithContext(runtime, ({ store }) => {
          const repo = selector
            ? resolveRepo(store, selector)
            : firstRepo(store);
          const payload = graphRelationships(
            store,
            repo.id,
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

  graph
    .command("callees")
    .argument("<symbol>", "Symbol name or node id")
    .argument("[repo]", "Repository id, id prefix, or name")
    .option("--limit <limit>", "Maximum relationships", "20")
    .option("--json", "Print JSON output")
    .action(
      (
        symbol: string,
        selector: string | undefined,
        options: { limit: string; json?: boolean },
      ) => {
        runWithContext(runtime, ({ store }) => {
          const repo = selector
            ? resolveRepo(store, selector)
            : firstRepo(store);
          const payload = graphRelationships(
            store,
            repo.id,
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

  graph
    .command("impact")
    .argument("<symbol>", "Symbol name or node id")
    .argument("[repo]", "Repository id, id prefix, or name")
    .option("--json", "Print JSON output")
    .action(
      (
        symbol: string,
        selector: string | undefined,
        options: { json?: boolean },
      ) => {
        runWithContext(runtime, ({ store }) => {
          const repo = selector
            ? resolveRepo(store, selector)
            : firstRepo(store);
          const payload = graphImpact(store, repo.id, symbol);
          output(options.json, payload, formatImpact(payload));
        });
      },
    );

  graph
    .command("explore")
    .argument("<query>", "Search query")
    .argument("[repo]", "Repository id, id prefix, or name")
    .option("--max-nodes <maxNodes>", "Maximum graph nodes", "160")
    .option("--json", "Print JSON output")
    .action(
      (
        query: string,
        selector: string | undefined,
        options: { maxNodes: string; json?: boolean },
      ) => {
        runWithContext(runtime, ({ store }) => {
          const repo = selector
            ? resolveRepo(store, selector)
            : firstRepo(store);
          const payload = graphExplore(
            store,
            repo.id,
            query,
            parseLimit(options.maxNodes),
          );
          output(options.json, payload, displayString(payload.text));
        });
      },
    );

  graph
    .command("affected")
    .argument("<repo>", "Repository id, id prefix, or name")
    .argument("[files...]", "Changed files")
    .option("--stdin", "Read changed files from stdin")
    .option("--json", "Print JSON output")
    .action(
      (
        selector: string,
        files: string[],
        options: { stdin?: boolean; json?: boolean },
      ) => {
        runWithContext(runtime, ({ store }) => {
          const repo = resolveRepo(store, selector);
          const changedFiles = options.stdin ? readStdinLines() : files;
          const payload = graphAffected(store, repo.id, changedFiles);
          output(options.json, payload, formatAffectedFiles(payload));
        });
      },
    );
}

function cliSearchFilters(options: {
  type?: string;
  language?: string;
  path?: string;
  name?: string;
}): {
  types?: string[];
  languages?: string[];
  pathFilters?: string[];
  nameFilters?: string[];
} {
  const filters: {
    types?: string[];
    languages?: string[];
    pathFilters?: string[];
    nameFilters?: string[];
  } = {};
  if (options.type) {
    filters.types = [options.type];
  }
  if (options.language) {
    filters.languages = [options.language];
  }
  if (options.path) {
    filters.pathFilters = [options.path];
  }
  if (options.name) {
    filters.nameFilters = [options.name];
  }
  return filters;
}
