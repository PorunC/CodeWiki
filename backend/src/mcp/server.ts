import type { CodeWikiSettings } from "../config.js";
import { getSettings } from "../config.js";
import { CodeWikiStore } from "../db/store.js";
import { RepoScanner } from "../scanner/scanner.js";
import {
  createBackendRuntime,
  type BackendServices,
} from "../services/backendServices.js";
import type { JsonObject } from "../types.js";
import { CODEWIKI_VERSION } from "../version.js";
import {
  DEFAULT_PROTOCOL_VERSION,
  error,
  isJsonObject,
  params,
  result,
  toolResponse,
} from "./protocol.js";
import { buildTools, type ToolSpec } from "./tools.js";

export type CodeWikiMCPServerOptions = {
  settings?: CodeWikiSettings;
  store?: CodeWikiStore;
  scanner?: RepoScanner;
  services?: BackendServices;
};

export class CodeWikiMCPServer {
  readonly settings: CodeWikiSettings;
  readonly store: CodeWikiStore;
  readonly scanner: RepoScanner;
  readonly services: BackendServices;
  readonly tools: Record<string, ToolSpec>;
  private readonly ownsStore: boolean;

  constructor(options: CodeWikiMCPServerOptions = {}) {
    this.settings = options.settings ?? getSettings();
    this.store = options.store ?? new CodeWikiStore(this.settings.databasePath);
    this.scanner =
      options.scanner ??
      new RepoScanner({ storageDir: this.settings.storageDir });
    this.services = createBackendRuntime(
      { settings: this.settings, store: this.store, scanner: this.scanner },
      options.services,
    ).services;
    this.ownsStore = !options.store;
    this.tools = buildTools({
      store: this.store,
      scanner: this.scanner,
      settings: this.settings,
      services: this.services,
    });
  }

  async handleMessage(message: JsonObject): Promise<JsonObject | null> {
    const method = typeof message.method === "string" ? message.method : "";
    const requestId = message.id;
    const isNotification = !Object.hasOwn(message, "id");
    try {
      if (method === "initialize") {
        return result(requestId, this.initializeResult(message.params));
      }
      if (method === "notifications/initialized" || method === "initialized") {
        return null;
      }
      if (method.startsWith("notifications/")) {
        return null;
      }
      if (method === "ping") {
        return result(requestId, {});
      }
      if (method === "tools/list") {
        return result(requestId, {
          tools: Object.values(this.tools).map((tool) => tool.payload()),
        });
      }
      if (method === "tools/call") {
        return result(requestId, await this.callTool(params(message)));
      }
      if (method === "resources/list") {
        return result(requestId, { resources: [] });
      }
      if (method === "prompts/list") {
        return result(requestId, { prompts: [] });
      }
      if (method === "logging/setLevel") {
        return result(requestId, {});
      }
      if (method === "shutdown" || method === "exit") {
        return isNotification ? null : result(requestId, {});
      }
    } catch (caught) {
      if (isNotification) {
        return null;
      }
      return error(
        requestId,
        -32603,
        caught instanceof Error ? caught.message : String(caught),
      );
    }
    if (isNotification) {
      return null;
    }
    return error(requestId, -32601, `Method not found: ${method}`);
  }

  close(): void {
    if (this.ownsStore) {
      this.store.close();
    }
  }

  private initializeResult(rawParams: unknown): JsonObject {
    let protocolVersion = DEFAULT_PROTOCOL_VERSION;
    if (
      isJsonObject(rawParams) &&
      typeof rawParams.protocolVersion === "string"
    ) {
      protocolVersion = rawParams.protocolVersion;
    }
    return {
      protocolVersion,
      capabilities: { tools: {} },
      serverInfo: {
        name: "codewiki",
        version: CODEWIKI_VERSION,
      },
    };
  }

  private async callTool(callParams: JsonObject): Promise<JsonObject> {
    const name = callParams.name;
    if (typeof name !== "string" || !name) {
      throw new Error("tools/call requires a tool name.");
    }
    const tool = this.tools[name];
    if (!tool) {
      throw new Error(`Unknown tool: ${name}`);
    }
    const args = callParams.arguments ?? {};
    if (!isJsonObject(args)) {
      throw new Error("Tool arguments must be an object.");
    }
    try {
      return toolResponse(await tool.handler(args));
    } catch (caught) {
      return toolResponse(
        { error: caught instanceof Error ? caught.message : String(caught) },
        { isError: true },
      );
    }
  }
}
