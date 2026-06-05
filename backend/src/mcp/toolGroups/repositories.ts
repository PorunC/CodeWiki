import {
  repoFilesPayload,
  repoPayload,
  repoScanPayload,
} from "../../presenters/payloads.js";
import {
  objectSchema,
  optionalString,
  repoSelectorSchema,
  requiredString,
  tool,
  type ToolRuntime,
  type ToolSpec,
} from "../toolkit.js";

export function buildRepositoryTools({ services }: ToolRuntime): ToolSpec[] {
  return [
    tool(
      "codewiki_repos_list",
      "List repositories registered in the local CodeWiki database.",
      objectSchema({}),
      () => services.repositories.list().map(repoPayload),
    ),
    tool(
      "codewiki_repo_add",
      "Register a local repository path or Git URL in CodeWiki.",
      objectSchema(
        {
          path: { type: "string", description: "Local path or Git URL." },
          name: { type: "string", description: "Optional display name." },
          source_type: {
            type: "string",
            description: "Repository source type.",
            default: "local",
          },
        },
        ["path"],
      ),
      (args) => {
        const name = optionalString(args, "name");
        return repoPayload(
          services.repositories.register(requiredString(args, "path"), {
            ...(name ? { name } : {}),
            sourceType: optionalString(args, "source_type") ?? "local",
          }),
        );
      },
    ),
    tool(
      "codewiki_repo_delete",
      "Delete a registered repository and its indexed data.",
      objectSchema({ repo: repoSelectorSchema() }, ["repo"]),
      (args) => {
        const { repo, deleted } = services.repositories.deleteBySelector(
          requiredString(args, "repo"),
        );
        return { repo_id: repo.id, deleted };
      },
    ),
    tool(
      "codewiki_repo_scan",
      "Scan a local repository path or Git URL without registering it.",
      objectSchema(
        {
          path: { type: "string", description: "Local path or Git URL." },
          name: { type: "string", description: "Optional display name." },
          source_type: {
            type: "string",
            description: "Repository source type.",
            default: "local",
          },
        },
        ["path"],
      ),
      (args) => {
        const name = optionalString(args, "name");
        const scan = services.repositories.scan(requiredString(args, "path"), {
          ...(name ? { name } : {}),
          sourceType: optionalString(args, "source_type") ?? "local",
        });
        return repoScanPayload(scan);
      },
    ),
    tool(
      "codewiki_files_tree",
      "Scan a registered repository and return its file tree and file list.",
      objectSchema({ repo: repoSelectorSchema() }),
      (args) => {
        const repo = services.repositories.resolve(
          optionalString(args, "repo"),
        );
        const scan = services.repositories.filesForRepo(repo);
        return repoFilesPayload(repo, scan);
      },
    ),
  ];
}
