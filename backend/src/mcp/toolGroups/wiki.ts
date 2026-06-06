import { resolveRepo } from "../../services/repoResolver.js";
import {
  catalogPayload,
  catalogResultPayload,
  pagePayload,
  pageResultPayload,
} from "../../wiki/payloads.js";
import {
  intArg,
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
      "codewiki_wiki_plan",
      "Plan agent-generated wiki pages without calling an external LLM.",
      objectSchema({
        repo: repoSelectorSchema(),
        language: { type: "string", default: "en" },
      }),
      async (args) => {
        const repo = await resolveRepo(
          store,
          scanner,
          optionalString(args, "repo"),
        );
        return services.wiki.agentWikiPlan(repo.id, languageArg(args));
      },
    ),
    tool(
      "codewiki_wiki_evidence",
      "Return bounded evidence for an agent-generated wiki page.",
      objectSchema(
        {
          repo: repoSelectorSchema(),
          slug: { type: "string", description: "Wiki page slug." },
          language: { type: "string", default: "en" },
          limit: { type: "integer", default: 12 },
        },
        ["slug"],
      ),
      async (args) => {
        const repo = await resolveRepo(
          store,
          scanner,
          optionalString(args, "repo"),
        );
        return services.wiki.agentWikiEvidence(
          repo.id,
          requiredString(args, "slug"),
          languageArg(args),
          { limit: intArg(args, "limit", 12) },
        );
      },
    ),
    tool(
      "codewiki_wiki_page_save",
      "Save agent-written Markdown for a wiki page.",
      objectSchema(
        {
          repo: repoSelectorSchema(),
          slug: { type: "string", description: "Wiki page slug." },
          markdown: { type: "string", description: "Markdown content." },
          language: { type: "string", default: "en" },
          title: { type: "string", description: "Optional page title." },
          parent_slug: {
            type: "string",
            description: "Optional parent page slug.",
          },
        },
        ["slug", "markdown"],
      ),
      async (args) => {
        const repo = await resolveRepo(
          store,
          scanner,
          optionalString(args, "repo"),
        );
        const saveOptions: { title?: string; parentSlug?: string | null } = {};
        const title = optionalString(args, "title");
        if (title) {
          saveOptions.title = title;
        }
        const parentSlug = optionalString(args, "parent_slug");
        if (parentSlug) {
          saveOptions.parentSlug = parentSlug;
        }
        return services.wiki.saveAgentWikiPage(
          repo.id,
          requiredString(args, "slug"),
          requiredString(args, "markdown"),
          languageArg(args),
          saveOptions,
        );
      },
    ),
    tool(
      "codewiki_wiki_page_validate",
      "Validate an agent-generated wiki page.",
      objectSchema(
        {
          repo: repoSelectorSchema(),
          slug: { type: "string", description: "Wiki page slug." },
          language: { type: "string", default: "en" },
        },
        ["slug"],
      ),
      async (args) => {
        const repo = await resolveRepo(
          store,
          scanner,
          optionalString(args, "repo"),
        );
        return services.wiki.validateAgentWikiPage(
          repo.id,
          requiredString(args, "slug"),
          languageArg(args),
        );
      },
    ),
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
            (await resolveRepo(store, scanner, optionalString(args, "repo")))
              .id,
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
        const repo = await resolveRepo(
          store,
          scanner,
          optionalString(args, "repo"),
        );
        const pages = await services.wiki.generateAllPagesWithLlmFallback(
          repo.id,
          languageArg(args),
        );
        const hasValidationErrors = pages.some(
          (page) => page.validation_errors.length > 0,
        );
        return {
          repo_id: repo.id,
          status: hasValidationErrors ? "partial" : "generated",
          page_count: pages.length,
          pages: pages.map(pageResultPayload),
          llm_cache: await services.wiki.llmCachePayload(repo.id, [
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
      async (args) =>
        services.wiki.updatePagesWithLlmFallback(
          (await resolveRepo(store, scanner, optionalString(args, "repo"))).id,
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
      async (args) =>
        pageResultPayload(
          await services.wiki.regeneratePageWithLlmFallback(
            (await resolveRepo(store, scanner, optionalString(args, "repo")))
              .id,
            requiredString(args, "slug"),
            languageArg(args),
          ),
        ),
    ),
    tool(
      "codewiki_wiki_pages_list",
      "List generated wiki pages for a repository.",
      objectSchema({
        repo: repoSelectorSchema(),
        language: { type: "string", default: "en" },
      }),
      async (args) => {
        const repo = await resolveRepo(
          store,
          scanner,
          optionalString(args, "repo"),
        );
        const language = languageArg(args);
        const catalog = await store.getLatestDocCatalog(repo.id, language);
        return {
          repo_id: repo.id,
          catalog: maybeMap(catalog, catalogPayload),
          pages: (await store.listDocPages(repo.id, language)).map(pagePayload),
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
      async (args) => {
        const repo = await resolveRepo(
          store,
          scanner,
          optionalString(args, "repo"),
        );
        const slug = requiredString(args, "slug");
        const page = await store.getDocPage(repo.id, slug, languageArg(args));
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
      async (args) =>
        services.wiki.translateWiki(
          (await resolveRepo(store, scanner, optionalString(args, "repo"))).id,
          optionalString(args, "source_language") ?? "en",
          requiredString(args, "target_language"),
        ),
    ),
  ];
}
