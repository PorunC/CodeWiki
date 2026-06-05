import type { FastifyInstance } from "fastify";
import type { HttpRouteContext } from "../context.js";
import { registerAskRoutes } from "./ask.js";
import { registerGraphRoutes } from "./graph.js";
import { registerGraphRagRoutes } from "./graphrag.js";
import { registerRepoRoutes } from "./repos.js";
import { registerRunRoutes } from "./runs.js";
import { registerSettingsRoutes } from "./settings.js";
import { registerWikiRoutes } from "./wiki.js";

export function registerApiRoutes(
  app: FastifyInstance,
  context: HttpRouteContext,
): void {
  registerSettingsRoutes(app, context);
  registerRepoRoutes(app, context);
  registerRunRoutes(app, context);
  registerGraphRoutes(app, context);
  registerGraphRagRoutes(app, context);
  registerAskRoutes(app, context);
  registerWikiRoutes(app, context);
}
