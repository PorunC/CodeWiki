import cors from "@fastify/cors";
import fastifyStatic from "@fastify/static";
import Fastify, { type FastifyInstance } from "fastify";
import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { getSettings, type CodeWikiSettings } from "../config.js";
import { createCodeWikiStore } from "../db/factory.js";
import type { CodeWikiStoreApi } from "../db/types.js";
import { RepoScanner } from "../scanner/scanner.js";
import {
  createBackendRuntime,
  type BackendServices,
} from "../services/backendServices.js";
import {
  fastifyLoggingOptions,
  registerHttpRequestLogging,
} from "./logging.js";
import { registerApiRoutes } from "./routes/index.js";

type ServerOptions = {
  settings?: CodeWikiSettings;
  store?: CodeWikiStoreApi;
  scanner?: RepoScanner;
  services?: BackendServices;
  logger?: boolean;
};

export async function createServer(
  options: ServerOptions = {},
): Promise<FastifyInstance> {
  const settings = options.settings ?? getSettings();
  const ownsStore = options.store === undefined;
  const store = options.store ?? createCodeWikiStore(settings.databaseUrl);
  const scanner =
    options.scanner ?? new RepoScanner({ storageDir: settings.storageDir });
  const runtime = createBackendRuntime(
    { settings, store, scanner },
    options.services,
  );
  const loggerEnabled = options.logger ?? false;
  const app = Fastify(fastifyLoggingOptions(settings, loggerEnabled));
  if (loggerEnabled) {
    registerHttpRequestLogging(app);
  }

  await app.register(cors, {
    origin: ["http://localhost:5173", "http://127.0.0.1:5173"],
    credentials: true,
  });

  registerApiRoutes(app, runtime);
  registerStatic(app, settings);

  if (ownsStore) {
    app.addHook("onClose", async () => {
      await store.close();
    });
  }
  return app;
}

export async function startServer(
  options: ServerOptions = {},
): Promise<FastifyInstance> {
  const settings = options.settings ?? getSettings();
  const app = await createServer({
    ...options,
    settings,
    logger: options.logger ?? true,
  });
  await app.listen({ host: settings.host, port: settings.port });
  return app;
}

function registerStatic(
  app: FastifyInstance,
  settings: CodeWikiSettings,
): void {
  const staticDir =
    settings.staticDir ?? resolve(import.meta.dirname, "../../static");
  if (!existsSync(resolve(staticDir, "index.html"))) {
    return;
  }
  void app.register(fastifyStatic, {
    root: staticDir,
    wildcard: false,
  });
  app.setNotFoundHandler((request, reply) => {
    if (request.url.startsWith("/api/")) {
      return reply.status(404).send({ detail: "Not found" });
    }
    return reply.sendFile("index.html");
  });
}
