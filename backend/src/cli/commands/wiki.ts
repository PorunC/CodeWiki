import type { Command } from "commander";
import {
  catalogPayload,
  catalogResultPayload,
  pagePayload,
  pageResultPayload,
} from "../../wiki/payloads.js";
import {
  resolveRegisteredRepo as resolveRepo,
  selectedRepo,
} from "../../services/repoResolver.js";
import {
  displayNumber,
  displayString,
  output,
  parseLimit,
  readStdinText,
  runWithContextAsync,
  type CliRuntime,
} from "../runtime.js";

export function registerWikiCommands(
  program: Command,
  runtime: CliRuntime,
): void {
  const wiki = program
    .command("wiki")
    .description("Read and generate wiki pages");

  wiki
    .command("catalog-evidence")
    .argument("<repo>", "Repository id, id prefix, or name")
    .option("--language <language>", "Language code", "en")
    .option("--json", "Print JSON output")
    .action((selector: string, options: { language: string; json?: boolean }) =>
      runWithContextAsync(runtime, async ({ store, services }) => {
        const repo = await resolveRepo(store, selector);
        const payload = await services.wiki.agentWikiCatalogEvidence(
          repo.id,
          options.language,
        );
        output(
          options.json,
          payload,
          `Prepared catalog evidence for ${displayString(repo.name)}`,
        );
      }),
    );

  wiki
    .command("catalog-save")
    .argument("<repo>", "Repository id, id prefix, or name")
    .option("--language <language>", "Language code", "en")
    .option("--stdin", "Read catalog JSON from stdin")
    .option("--json", "Print JSON output")
    .action(
      (
        selector: string,
        options: { language: string; stdin?: boolean; json?: boolean },
      ) =>
        runWithContextAsync(runtime, async ({ store, services }) => {
          if (!options.stdin) {
            throw new Error("Use --stdin to provide catalog JSON.");
          }
          const repo = await resolveRepo(store, selector);
          const payload = await services.wiki.saveAgentWikiCatalog(
            repo.id,
            readStdinText(),
            options.language,
          );
          output(
            options.json,
            payload,
            `Saved agent wiki catalog for ${displayString(repo.name)}`,
          );
        }),
    );

  wiki
    .command("catalog-validate")
    .argument("<repo>", "Repository id, id prefix, or name")
    .option("--language <language>", "Language code", "en")
    .option(
      "--stdin",
      "Validate catalog JSON from stdin instead of saved catalog",
    )
    .option("--json", "Print JSON output")
    .action(
      (
        selector: string,
        options: { language: string; stdin?: boolean; json?: boolean },
      ) =>
        runWithContextAsync(runtime, async ({ store, services }) => {
          const repo = await resolveRepo(store, selector);
          const payload = await services.wiki.validateAgentWikiCatalog(
            repo.id,
            options.language,
            options.stdin ? readStdinText() : undefined,
          );
          const status =
            typeof payload.status === "string" ? payload.status : "";
          output(
            options.json,
            payload,
            `Wiki catalog is ${displayString(status)}`,
          );
        }),
    );

  wiki
    .command("plan")
    .argument("<repo>", "Repository id, id prefix, or name")
    .option("--language <language>", "Language code", "en")
    .option("--json", "Print JSON output")
    .action((selector: string, options: { language: string; json?: boolean }) =>
      runWithContextAsync(runtime, async ({ store, services }) => {
        const repo = await resolveRepo(store, selector);
        const payload = await services.wiki.agentWikiPlan(
          repo.id,
          options.language,
        );
        output(
          options.json,
          payload,
          `Planned ${displayNumber(Array.isArray(payload.pages) ? payload.pages.length : 0)} wiki pages`,
        );
      }),
    );

  wiki
    .command("evidence")
    .argument("<slug>", "Page slug")
    .argument("<repo>", "Repository id, id prefix, or name")
    .option("--language <language>", "Language code", "en")
    .option("--limit <limit>", "Maximum source chunks", parseLimit, 12)
    .option("--json", "Print JSON output")
    .action(
      (
        slug: string,
        selector: string,
        options: { language: string; limit: number; json?: boolean },
      ) =>
        runWithContextAsync(runtime, async ({ store, services }) => {
          const repo = await resolveRepo(store, selector);
          const payload = await services.wiki.agentWikiEvidence(
            repo.id,
            slug,
            options.language,
            { limit: options.limit },
          );
          output(
            options.json,
            payload,
            `Prepared evidence for ${displayString(slug)}`,
          );
        }),
    );

  wiki
    .command("save")
    .argument("<slug>", "Page slug")
    .argument("<repo>", "Repository id, id prefix, or name")
    .option("--language <language>", "Language code", "en")
    .option("--title <title>", "Page title")
    .option("--parent-slug <parentSlug>", "Parent page slug")
    .option("--stdin", "Read Markdown from stdin")
    .option("--json", "Print JSON output")
    .action(
      (
        slug: string,
        selector: string,
        options: {
          language: string;
          title?: string;
          parentSlug?: string;
          stdin?: boolean;
          json?: boolean;
        },
      ) =>
        runWithContextAsync(runtime, async ({ store, services }) => {
          if (!options.stdin) {
            throw new Error("Use --stdin to provide Markdown content.");
          }
          const repo = await resolveRepo(store, selector);
          const saveOptions: { title?: string; parentSlug?: string | null } =
            {};
          if (options.title) {
            saveOptions.title = options.title;
          }
          if (options.parentSlug) {
            saveOptions.parentSlug = options.parentSlug;
          }
          const payload = await services.wiki.saveAgentWikiPage(
            repo.id,
            slug,
            readStdinText(),
            options.language,
            saveOptions,
          );
          output(
            options.json,
            payload,
            `Saved ${displayString(slug)} as ${displayString(payload.status)}`,
          );
        }),
    );

  wiki
    .command("validate")
    .argument("<slug>", "Page slug")
    .argument("<repo>", "Repository id, id prefix, or name")
    .option("--language <language>", "Language code", "en")
    .option("--json", "Print JSON output")
    .action(
      (
        slug: string,
        selector: string,
        options: { language: string; json?: boolean },
      ) =>
        runWithContextAsync(runtime, async ({ store, services }) => {
          const repo = await resolveRepo(store, selector);
          const payload = await services.wiki.validateAgentWikiPage(
            repo.id,
            slug,
            options.language,
          );
          output(
            options.json,
            payload,
            `Wiki page ${displayString(slug)} is ${displayString(payload.status)}`,
          );
        }),
    );

  wiki
    .command("catalog")
    .argument("<repo>", "Repository id, id prefix, or name")
    .option("--language <language>", "Language code", "en")
    .option("--json", "Print JSON output")
    .action((selector: string, options: { language: string; json?: boolean }) =>
      runWithContextAsync(runtime, async ({ store, services }) => {
        const repo = await resolveRepo(store, selector);
        const result = await services.wiki.generateCatalogWithLlmFallback(
          repo.id,
          options.language,
        );
        output(
          options.json,
          catalogResultPayload(result),
          `Generated catalog ${result.catalog.title}`,
        );
      }),
    );

  wiki
    .command("pages")
    .argument("<repo>", "Repository id, id prefix, or name")
    .option("--language <language>", "Language code", "en")
    .option("--json", "Print JSON output")
    .action((selector: string, options: { language: string; json?: boolean }) =>
      runWithContextAsync(runtime, async ({ store, services }) => {
        const repo = await resolveRepo(store, selector);
        const results = await services.wiki.generateAllPagesWithLlmFallback(
          repo.id,
          options.language,
        );
        const payload = {
          repo_id: repo.id,
          status: "generated",
          page_count: results.length,
          pages: results.map(pageResultPayload),
          llm_cache: await services.wiki.llmCachePayload(repo.id, [
            "catalog",
            "page",
          ]),
        };
        output(options.json, payload, `Generated ${results.length} wiki pages`);
      }),
    );

  wiki
    .command("update")
    .argument("[repo]", "Repository id, id prefix, or name")
    .option("--repo <repo>", "Repository id, name, path, or Git URL")
    .option("--language <language>", "Language code", "en")
    .option("--json", "Print JSON output")
    .action(
      (
        selector: string | undefined,
        options: { repo?: string; language: string; json?: boolean },
      ) =>
        runWithContextAsync(runtime, async ({ store, services }) => {
          const repo = await selectedRepo(store, options.repo ?? selector);
          const payload = await services.wiki.updatePagesWithLlmFallback(
            repo.id,
            options.language,
          );
          output(
            options.json,
            payload,
            `Wiki update: ${displayNumber(payload.generated_count)} generated, ${displayNumber(payload.reused_count)} reused (${options.language})`,
          );
        }),
    );

  wiki
    .command("page")
    .argument("<slug>", "Page slug")
    .argument("[repo]", "Repository id, id prefix, or name")
    .option("--repo <repo>", "Repository id, name, path, or Git URL")
    .option("--language <language>", "Language code", "en")
    .option("--json", "Print JSON output")
    .action(
      (
        slug: string,
        selector: string | undefined,
        options: { repo?: string; language: string; json?: boolean },
      ) =>
        runWithContextAsync(runtime, async ({ store, services }) => {
          const repo = await selectedRepo(store, options.repo ?? selector);
          const result = await services.wiki.regeneratePageWithLlmFallback(
            repo.id,
            slug,
            options.language,
          );
          output(
            options.json,
            pageResultPayload(result),
            `Page ${result.page.status}: ${result.page.slug}`,
          );
        }),
    );

  wiki
    .command("list")
    .argument("<repo>", "Repository id, id prefix, or name")
    .option("--language <language>", "Language code", "en")
    .option("--json", "Print JSON output")
    .action((selector: string, options: { language: string; json?: boolean }) =>
      runWithContextAsync(runtime, async ({ store }) => {
        const repo = await resolveRepo(store, selector);
        const catalog = await store.getLatestDocCatalog(
          repo.id,
          options.language,
        );
        const pages = await store.listDocPages(repo.id, options.language);
        const payload = {
          repo_id: repo.id,
          catalog: catalog ? catalogPayload(catalog) : null,
          pages: pages.map(pagePayload),
        };
        output(
          options.json,
          payload,
          pages.map((page) => `${page.slug}\t${page.title}`).join("\n"),
        );
      }),
    );

  wiki
    .command("read")
    .argument("<slug>", "Page slug")
    .argument("<repo>", "Repository id, id prefix, or name")
    .option("--language <language>", "Language code", "en")
    .option("--json", "Print JSON output")
    .action(
      (
        slug: string,
        selector: string,
        options: { language: string; json?: boolean },
      ) =>
        runWithContextAsync(runtime, async ({ store }) => {
          const repo = await resolveRepo(store, selector);
          const page = await store.getDocPage(repo.id, slug, options.language);
          if (!page) {
            throw new Error(`Wiki page not found: ${slug}`);
          }
          output(options.json, pagePayload(page), `${page.markdown}\n`);
        }),
    );

  wiki
    .command("translate")
    .argument("<targetLanguage>", "Target language code")
    .argument("[repo]", "Repository id, id prefix, or name")
    .option("--repo <repo>", "Repository id, name, path, or Git URL")
    .option("--source-language <sourceLanguage>", "Source language code", "en")
    .option("--json", "Print JSON output")
    .action(
      (
        targetLanguage: string,
        selector: string | undefined,
        options: { repo?: string; sourceLanguage: string; json?: boolean },
      ) =>
        runWithContextAsync(runtime, async ({ store, services }) => {
          const repo = await selectedRepo(store, options.repo ?? selector);
          const payload = await services.wiki.translateWiki(
            repo.id,
            options.sourceLanguage,
            targetLanguage,
          );
          output(
            options.json,
            payload,
            `Translated ${displayNumber(payload.page_count)} pages from ${displayString(payload.source_language)} to ${displayString(
              payload.target_language,
            )}`,
          );
        }),
    );
}
