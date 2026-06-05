import type { FastifyInstance } from "fastify";
import { testLlmConfiguration } from "../../llm/modelRouter.js";
import { llmModelsPayload } from "../../presenters/payloads.js";
import type { HttpRouteContext } from "../context.js";
import { objectBody, optionalString, routeError } from "../request.js";

export function registerSettingsRoutes(
  app: FastifyInstance,
  { settings }: HttpRouteContext,
): void {
  app.get("/api/health", async () => ({ status: "ok" }));

  app.get("/api/settings/llm/models", async () => llmModelsPayload(settings));

  app.post("/api/settings/llm/test", async (request, reply) => {
    const body = objectBody(request.body);
    try {
      return testLlmConfiguration(settings, {
        taskType: optionalString(body.task_type),
        model: optionalString(body.model),
      });
    } catch (error) {
      return routeError(reply, error);
    }
  });
}
