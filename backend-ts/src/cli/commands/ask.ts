import type { Command } from "commander";
import {
  firstRepo,
  resolveRegisteredRepo as resolveRepo,
} from "../../services/repoResolver.js";
import { output, runWithContextAsync, type CliRuntime } from "../runtime.js";

export function registerAskCommand(
  program: Command,
  runtime: CliRuntime,
): void {
  program
    .command("ask")
    .argument("<question>", "Question to answer")
    .argument("[repo]", "Repository id, id prefix, or name")
    .option("--json", "Print JSON output")
    .action(
      (
        question: string,
        selector: string | undefined,
        options: { json?: boolean },
      ) =>
        runWithContextAsync(runtime, async ({ store, services }) => {
          const repo = selector
            ? resolveRepo(store, selector)
            : firstRepo(store);
          const payload = await services.questionAnswerer.answerWithLlmFallback(
            repo.id,
            {
              question,
            },
          );
          output(options.json, payload, String(payload.answer));
        }),
    );
}
