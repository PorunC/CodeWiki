import type { FastifyInstance } from "fastify";
import {
  repoFilesPayload,
  repoPayload,
  repoScanPayload,
} from "../../presenters/payloads.js";
import type { HttpRouteContext } from "../context.js";
import {
  objectBody,
  optionalString,
  params,
  routeError,
  stringField,
} from "../request.js";

export function registerRepoRoutes(
  app: FastifyInstance,
  { services }: HttpRouteContext,
): void {
  app.post("/api/repos", async (request, reply) => {
    const body = objectBody(request.body);
    try {
      const repo = services.repositories.register(stringField(body, "path"), {
        name: optionalString(body.name),
        sourceType: optionalString(body.source_type) ?? "local",
      });
      return repoPayload(repo);
    } catch (error) {
      return routeError(reply, error);
    }
  });

  app.post("/api/repos/scan", async (request, reply) => {
    const body = objectBody(request.body);
    try {
      const scan = services.repositories.scan(stringField(body, "path"), {
        name: optionalString(body.name),
        sourceType: optionalString(body.source_type) ?? "local",
      });
      return repoScanPayload(scan);
    } catch (error) {
      return routeError(reply, error);
    }
  });

  app.get("/api/repos", async () =>
    services.repositories.list().map(repoPayload),
  );

  app.get("/api/repos/:repoId", async (request, reply) => {
    const { repoId } = params(request.params);
    try {
      return repoPayload(services.repositories.get(repoId));
    } catch (error) {
      return routeError(reply, error);
    }
  });

  app.delete("/api/repos/:repoId", async (request, reply) => {
    const { repoId } = params(request.params);
    try {
      services.repositories.delete(repoId);
      return reply.status(204).send();
    } catch (error) {
      return routeError(reply, error);
    }
  });

  app.get("/api/repos/:repoId/files", async (request, reply) => {
    const { repoId } = params(request.params);
    try {
      const { repo, scan } = services.repositories.filesForId(repoId);
      return repoFilesPayload(repo, scan);
    } catch (error) {
      return routeError(reply, error);
    }
  });
}
