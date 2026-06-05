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
