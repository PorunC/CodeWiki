import type { FastifyInstance } from "fastify";
import {
  catalogPayload,
  catalogResultPayload,
  pagePayload,
  pageResultPayload,
} from "../../wiki/payloads.js";
import { notFoundError } from "../../errors.js";
import type { HttpRouteContext } from "../context.js";
import {
  objectBody,
  optionalString,
  params,
  queryObject,
  stringField,
  withRepo,
} from "../request.js";

export function registerWikiRoutes(
  app: FastifyInstance,
  { store, services }: HttpRouteContext,
): void {
  app.post("/api/repos/:repoId/wiki/catalog", async (request, reply) => {
    const { repoId } = params(request.params);
    return withRepo(reply, store, repoId, async () => {
      const language =
        optionalString(queryObject(request.query).language) ?? "en";
      return catalogResultPayload(
        await services.wiki.generateCatalogWithLlmFallback(repoId, language),
      );
    });
  });

  app.post("/api/repos/:repoId/wiki/pages/generate", async (request, reply) => {
    const { repoId } = params(request.params);
    return withRepo(reply, store, repoId, async () => {
      const language =
        optionalString(queryObject(request.query).language) ?? "en";
      const results = await services.wiki.generateAllPagesWithLlmFallback(
        repoId,
        language,
      );
      return {
        repo_id: repoId,
        status: "generated",
        page_count: results.length,
        pages: results.map(pageResultPayload),
        llm_cache: services.wiki.llmCachePayload(repoId, ["catalog", "page"]),
      };
    });
  });

  app.post("/api/repos/:repoId/wiki/pages/update", async (request, reply) => {
    const { repoId } = params(request.params);
    return withRepo(reply, store, repoId, async () => {
      const language =
        optionalString(queryObject(request.query).language) ?? "en";
      return services.wiki.updatePagesWithLlmFallback(repoId, language);
    });
  });

  app.post(
    "/api/repos/:repoId/wiki/pages/:slug/regenerate",
    async (request, reply) => {
      const { repoId, slug } = params(request.params);
      return withRepo(reply, store, repoId, async () => {
        const language =
          optionalString(queryObject(request.query).language) ?? "en";
        return pageResultPayload(
          await services.wiki.regeneratePageWithLlmFallback(
            repoId,
            slug,
            language,
          ),
        );
      });
    },
  );

  app.post("/api/repos/:repoId/wiki/translate", async (request, reply) => {
    const { repoId } = params(request.params);
    return withRepo(reply, store, repoId, () => {
      const body = objectBody(request.body);
      const sourceLanguage = optionalString(body.source_language) ?? "en";
      const targetLanguage = stringField(body, "target_language");
      return services.wiki.translateWiki(
        repoId,
        sourceLanguage,
        targetLanguage,
      );
    });
  });

  app.get("/api/repos/:repoId/wiki", async (request, reply) => {
    const { repoId } = params(request.params);
    return withRepo(reply, store, repoId, () => {
      const language =
        optionalString(queryObject(request.query).language) ?? "en";
      const catalog = store.getLatestDocCatalog(repoId, language);
      return {
        repo_id: repoId,
        catalog: catalog ? catalogPayload(catalog) : null,
        items: Array.isArray(catalog?.structure.items)
          ? catalog.structure.items
          : [],
        pages: store.listDocPages(repoId, language).map(pagePayload),
        llm_cache: services.wiki.llmCachePayload(repoId, [
          "catalog",
          "page",
          "translation",
        ]),
      };
    });
  });

  app.get("/api/repos/:repoId/wiki/pages/:slug", async (request, reply) => {
    const { repoId, slug } = params(request.params);
    return withRepo(reply, store, repoId, () => {
      const language =
        optionalString(queryObject(request.query).language) ?? "en";
      const page = store.getDocPage(repoId, slug, language);
      if (!page) {
        throw notFoundError("Wiki page", slug);
      }
      return pagePayload(page);
    });
  });
}
