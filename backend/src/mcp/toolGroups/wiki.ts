import { resolveRepo } from "../../services/repoResolver.js";
import {
  catalogPayload,
  catalogResultPayload,
  pagePayload,
  pageResultPayload,
} from "../../wiki/payloads.js";
import {
  languageArg,
  maybeMap,
  objectSchema,
  optionalString,
  repoSelectorSchema,
  requiredString,
  tool,
  type ToolRuntime,
  type ToolSpec,
} from "../toolkit.js";

export function buildWikiTools({
  store,
  scanner,
  services,
}: ToolRuntime): ToolSpec[] {
  return [
    tool(
      "codewiki_wiki_catalog_generate",
      "Generate a wiki catalog for a repository and language.",
      objectSchema({
        repo: repoSelectorSchema(),
        language: { type: "string", default: "en" },
      }),
      async (args) =>
        catalogResultPayload(
          await services.wiki.generateCatalogWithLlmFallback(
            resolveRepo(store, scanner, optionalString(args, "repo")).id,
            languageArg(args),
          ),
        ),
    ),
    tool(
      "codewiki_wiki_pages_generate",
      "Generate all wiki pages for a repository and language.",
      objectSchema({
        repo: repoSelectorSchema(),
        language: { type: "string", default: "en" },
      }),
      async (args) => {
        const repo = resolveRepo(store, scanner, optionalString(args, "repo"));
        const pages = await services.wiki.generateAllPagesWithLlmFallback(
          repo.id,
          languageArg(args),
        );
        return {
          repo_id: repo.id,
          status: "generated",
          page_count: pages.length,
          pages: pages.map(pageResultPayload),
          llm_cache: services.wiki.llmCachePayload(repo.id, [
            "catalog",
            "page",
          ]),
        };
      },
    ),
    tool(
      "codewiki_wiki_pages_update",
      "Generate missing or stale wiki pages for a repository.",
      objectSchema({
        repo: repoSelectorSchema(),
        language: { type: "string", default: "en" },
      }),
      (args) =>
        services.wiki.updatePagesWithLlmFallback(
          resolveRepo(store, scanner, optionalString(args, "repo")).id,
          languageArg(args),
        ),
    ),
    tool(
      "codewiki_wiki_page_regenerate",
      "Regenerate a single wiki page by slug and language.",
      objectSchema(
        {
          repo: repoSelectorSchema(),
          slug: { type: "string", description: "Wiki page slug." },
          language: { type: "string", default: "en" },
        },
        ["slug"],
      ),
      (args) =>
        services.wiki
          .regeneratePageWithLlmFallback(
            resolveRepo(store, scanner, optionalString(args, "repo")).id,
            requiredString(args, "slug"),
            languageArg(args),
          )
          .then(pageResultPayload),
    ),
    tool(
      "codewiki_wiki_pages_list",
      "List generated wiki pages for a repository.",
      objectSchema({
        repo: repoSelectorSchema(),
        language: { type: "string", default: "en" },
      }),
      (args) => {
        const repo = resolveRepo(store, scanner, optionalString(args, "repo"));
        const language = languageArg(args);
        return {
          repo_id: repo.id,
          catalog: maybeMap(
            store.getLatestDocCatalog(repo.id, language),
            catalogPayload,
          ),
          pages: store.listDocPages(repo.id, language).map(pagePayload),
        };
      },
    ),
    tool(
      "codewiki_wiki_page_read",
      "Read a generated wiki page by slug.",
      objectSchema(
        {
          repo: repoSelectorSchema(),
          slug: { type: "string", description: "Wiki page slug." },
          language: { type: "string", default: "en" },
        },
        ["slug"],
      ),
      (args) => {
        const repo = resolveRepo(store, scanner, optionalString(args, "repo"));
        const slug = requiredString(args, "slug");
        const page = store.getDocPage(repo.id, slug, languageArg(args));
        if (!page) {
          throw new Error(`Wiki page not found: ${slug}`);
        }
        return pagePayload(page);
      },
    ),
    tool(
      "codewiki_wiki_translate",
      "Copy an existing wiki from one language to another.",
      objectSchema(
        {
          repo: repoSelectorSchema(),
          source_language: { type: "string", default: "en" },
          target_language: {
            type: "string",
            description: "Target language code.",
          },
        },
        ["target_language"],
      ),
      (args) =>
        services.wiki.translateWiki(
          resolveRepo(store, scanner, optionalString(args, "repo")).id,
          optionalString(args, "source_language") ?? "en",
          requiredString(args, "target_language"),
        ),
    ),
  ];
}
