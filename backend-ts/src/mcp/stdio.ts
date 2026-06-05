#!/usr/bin/env node
import { realpathSync } from "node:fs";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
import { CodeWikiMCPServer } from "./server.js";
import { error, isJsonObject } from "./protocol.js";

export async function runStdio(
  server = new CodeWikiMCPServer(),
): Promise<void> {
  const lines = createInterface({ input: process.stdin, crlfDelay: Infinity });
  try {
    for await (const rawLine of lines) {
      const line = rawLine.trim();
      if (!line) {
        continue;
      }
      let response;
      try {
        const message = JSON.parse(line) as unknown;
        response = isJsonObject(message)
          ? await server.handleMessage(message)
          : error(null, -32600, "Invalid JSON-RPC request.");
      } catch (caught) {
        response = error(
          null,
          -32700,
          caught instanceof Error
            ? `Parse error: ${caught.message}`
            : "Parse error.",
        );
      }
      if (response) {
        process.stdout.write(`${JSON.stringify(response)}\n`);
      }
    }
  } finally {
    server.close();
  }
}

if (isDirectRun()) {
  try {
    await runStdio();
  } catch (caught) {
    process.stderr.write(
      `${caught instanceof Error ? caught.message : String(caught)}\n`,
    );
    process.exitCode = 1;
  }
}

function isDirectRun(): boolean {
  const entrypoint = process.argv[1];
  if (!entrypoint) {
    return false;
  }
  try {
    return realpathSync(entrypoint) === fileURLToPath(import.meta.url);
  } catch {
    return false;
  }
}
