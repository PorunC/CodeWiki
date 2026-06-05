import type { Command } from "commander";
import {
  repoFilesPayload,
  repoPayload,
  repoScanPayload,
} from "../../presenters/payloads.js";
import { formatFileTree } from "../../presenters/fileTree.js";
import {
  displayNumber,
  displayString,
  output,
  runWithContext,
  type CliRuntime,
} from "../runtime.js";

export function registerRepoCommands(
  program: Command,
  runtime: CliRuntime,
): void {
  const repos = program
    .command("repos")
    .description("Register and inspect repositories");

  repos
    .command("add")
    .argument("<path>", "Repository path or Git URL")
    .option("--name <name>", "Repository display name")
    .option("--source-type <sourceType>", "Repository source type", "local")
    .option("--json", "Print JSON output")
    .action(
      (
        path: string,
        options: { name?: string; sourceType: string; json?: boolean },
      ) => {
        return runWithContext(runtime, async ({ services }) => {
          const repo = await services.repositories.register(path, {
            name: options.name,
            sourceType: options.sourceType,
          });
          output(
            options.json,
            repoPayload(repo),
            `Registered ${repo.name} (${repo.id})\n${repo.path}`,
          );
        });
      },
    );

  repos
    .command("list")
    .option("--json", "Print JSON output")
    .action((options: { json?: boolean }) => {
      return runWithContext(runtime, async ({ services }) => {
        const payload = (await services.repositories.list()).map(repoPayload);
        output(
          options.json,
          payload,
          payload.length
            ? payload
                .map(
                  (repo) =>
                    `${repo.id}\t${repo.name}\t${repo.source_type}\t${repo.path}`,
                )
                .join("\n")
            : "No repositories registered.",
        );
      });
    });

  repos
    .command("delete")
    .argument("<repo>", "Repository id, id prefix, or name")
    .option("--json", "Print JSON output")
    .action((selector: string, options: { json?: boolean }) => {
      return runWithContext(runtime, async ({ services }) => {
        const { repo, deleted } =
          await services.repositories.deleteBySelector(selector);
        output(
          options.json,
          { repo_id: repo.id, deleted },
          `Deleted ${repo.name} (${repo.id})`,
        );
      });
    });

  repos
    .command("scan")
    .argument("<path>", "Repository path or Git URL")
    .option("--name <name>", "Repository display name")
    .option("--source-type <sourceType>", "Repository source type", "local")
    .option("--json", "Print JSON output")
    .action(
      (
        path: string,
        options: { name?: string; sourceType: string; json?: boolean },
      ) => {
        return runWithContext(runtime, ({ services }) => {
          const scan = services.repositories.scan(path, {
            name: options.name,
            sourceType: options.sourceType,
          });
          const payload = repoScanPayload(scan);
          output(
            options.json,
            payload,
            `Repo: ${scan.repo.name} (${scan.repo.id})\nScanned: ${scan.scanned_count}\nIgnored: ${scan.ignored_count}\nSkipped: ${scan.skipped_count}`,
          );
        });
      },
    );

  const files = program
    .command("files")
    .description("Inspect repository files");

  files
    .command("tree")
    .argument("[repo]", "Repository id, id prefix, or name")
    .option("--repo <repo>", "Repository id, name, path, or Git URL")
    .option("--json", "Print JSON output")
    .action(
      (
        selector: string | undefined,
        options: { repo?: string; json?: boolean },
      ) => {
        return runWithContext(runtime, async ({ services }) => {
          const { repo, scan } = await services.repositories.filesForSelector(
            options.repo ?? selector,
          );
          const payload = repoFilesPayload(repo, scan);
          output(options.json, payload, formatFileTree(payload.root));
        });
      },
    );

  files
    .command("list")
    .argument("[repo]", "Repository id, id prefix, or name")
    .option("--repo <repo>", "Repository id, name, path, or Git URL")
    .option("--source-only", "Only show source files")
    .option("--json", "Print JSON output")
    .action(
      (
        selector: string | undefined,
        options: { repo?: string; sourceOnly?: boolean; json?: boolean },
      ) => {
        return runWithContext(runtime, async ({ services }) => {
          const { repo, scan } = await services.repositories.filesForSelector(
            options.repo ?? selector,
          );
          const payload = repoFilesPayload(repo, scan, {
            sourceOnly: Boolean(options.sourceOnly),
          });
          output(
            options.json,
            payload,
            payload.files
              .map(
                (file) =>
                  `${displayString(file.path)}  ${displayString(file.language, "text")}  ${displayNumber(file.size_bytes)} bytes`,
              )
              .join("\n"),
          );
        });
      },
    );
}
