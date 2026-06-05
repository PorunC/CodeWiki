import type { Command } from "commander";
import { startServer } from "../../http/server.js";
import { createLiteMcpServer } from "../../lite.js";
import { runStdio } from "../../mcp/stdio.js";
import type { CliRuntime } from "../runtime.js";

export function registerSystemCommands(
  program: Command,
  runtime: CliRuntime,
): void {
  program
    .command("serve")
    .description("Start the CodeWiki HTTP API and static frontend server")
    .option("--host <host>", "Host to bind", "127.0.0.1")
    .option("--port <port>", "Port to bind", "8000")
    .option(
      "--static-dir <path>",
      "Directory containing the built frontend index.html",
    )
    .action(
      async (options: { host: string; port: string; staticDir?: string }) => {
        runtime.withDatabaseOverride();
        process.env.BACKEND_HOST = options.host;
        process.env.BACKEND_PORT = options.port;
        if (options.staticDir) {
          process.env.CODEWIKI_STATIC_DIR = options.staticDir;
        }
        await startServer();
      },
    );

  program
    .command("mcp")
    .description("Start the CodeWiki MCP server over stdio")
    .option("--lite", "Use a project-local .codewiki database")
    .option("--path <path>", "Project path to use with --lite", ".")
    .option("--no-sync", "Skip lite startup sync")
    .action(
      async (options: { lite?: boolean; path: string; noSync?: boolean }) => {
        runtime.withDatabaseOverride();
        if (options.lite) {
          await runStdio(
            await createLiteMcpServer({
              path: options.path,
              sync: !options.noSync,
            }),
          );
          return;
        }
        await runStdio();
      },
    );
}
