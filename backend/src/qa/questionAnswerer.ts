import { createHash, randomUUID } from "node:crypto";
import type { CodeWikiStoreApi } from "../db/types.js";
import { notFoundError, validationError } from "../errors.js";
import { buildRetrievalTrace } from "../graphrag/retrieval.js";
import {
  LlmCallError,
  type CachedLlmCompletion,
  type LlmOperation,
} from "../llm/cache.js";
import { dynamicJsonMessage, stableJsonMessage } from "../llm/messages.js";
import {
  sourceUrlBaseForRepo,
  sourceUrlForRange,
} from "../services/sourceUrls.js";
import { loadPrompt } from "../services/prompts.js";
import type { JsonObject, RepoDescriptor, RetrievalTrace } from "../types.js";

export type QuestionAnswerRequest = {
  question: string;
  max_hops?: number;
  include_sources?: boolean;
  include_graph?: boolean;
};

type QuestionAnswerLlm = {
  isConfigured(taskType: string): boolean;
  complete(
    repoId: string,
    operation: LlmOperation,
  ): Promise<CachedLlmCompletion>;
};

type SourceCitation = {
  citation_id: string;
  file_path: string;
  start_line: number;
  end_line: number;
  source_url: string | null;
};

type SourceSnippet = SourceCitation & {
  content: string;
};

type QuestionContext = {
  repo: RepoDescriptor;
  question: string;
  trace: RetrievalTrace;
  sources: SourceCitation[];
  sourceSnippets: SourceSnippet[];
  relatedNodes: JsonObject[];
  relatedEdges: JsonObject[];
  relatedCommunities: JsonObject[];
};

export class QuestionAnswerer {
  constructor(
    private readonly store: CodeWikiStoreApi,
    private readonly llm?: QuestionAnswerLlm,
  ) {}

  async answer(
    repoId: string,
    payload: QuestionAnswerRequest,
  ): Promise<Record<string, unknown>> {
    const context = await this.questionContext(repoId, payload);
    return this.localAnswer(payload, context);
  }

  async answerWithLlmFallback(
    repoId: string,
    payload: QuestionAnswerRequest,
  ): Promise<Record<string, unknown>> {
    const context = await this.questionContext(repoId, payload);
    const fallback = this.localAnswer(payload, context);
    if (!this.llm?.isConfigured("qa") || context.sourceSnippets.length === 0) {
      return fallback;
    }

    try {
      const completion = await this.llm.complete(repoId, {
        taskType: "qa",
        cacheKey: `qa:${context.trace.trace_id}:${questionHash(context.question)}`,
        modelAlias: "qa",
        promptVersion: "qa:v1",
        inputPayload: llmInputPayload(context),
        messages: qaMessages(context),
      });
      const answer = completion.result.content.trim();
      return {
        ...fallback,
        answer: answer || fallback.answer,
        llm: llmMetadata("success", completion),
      };
    } catch (error) {
      return {
        ...fallback,
        llm: {
          status: "fallback",
          error: error instanceof Error ? error.message : String(error),
          run_id: error instanceof LlmCallError ? error.runId : null,
        },
      };
    }
  }

  private async questionContext(
    repoId: string,
    payload: QuestionAnswerRequest,
  ): Promise<QuestionContext> {
    const repo = await this.store.getRepo(repoId);
    if (!repo) {
      throw notFoundError("Repository", repoId);
    }
    const question = payload.question.trim();
    if (!question) {
      throw validationError("Question must be a non-empty string.");
    }

    const trace = await this.store.saveRetrievalTrace(
      await buildRetrievalTrace(
        this.store,
        repoId,
        question,
        payload.max_hops === undefined ? {} : { maxHops: payload.max_hops },
      ),
    );
    const sourceUrlBase = sourceUrlBaseForRepo(repo);
    const sourceSnippets = sourceSnippetsFromTrace(trace, sourceUrlBase);
    return {
      repo,
      question,
      trace,
      sources: payload.include_sources === false ? [] : sourceSnippets,
      sourceSnippets: payload.include_sources === false ? [] : sourceSnippets,
      relatedNodes:
        payload.include_graph === false
          ? []
          : [...trace.seed_nodes, ...trace.expanded_nodes],
      relatedEdges: payload.include_graph === false ? [] : trace.related_edges,
      relatedCommunities:
        payload.include_graph === false ? [] : trace.community_summaries,
    };
  }

  private localAnswer(
    payload: QuestionAnswerRequest,
    context: QuestionContext,
  ): Record<string, unknown> {
    const answer = context.sourceSnippets.length
      ? [
          `I found ${context.sourceSnippets.length} relevant source section${context.sourceSnippets.length === 1 ? "" : "s"} in ${context.repo.name}.`,
          "",
          ...context.sourceSnippets.slice(0, 4).map((source) => {
            const preview = String(source.content)
              .trim()
              .replace(/\s+/g, " ")
              .slice(0, 240);
            return `[${source.citation_id}] ${source.file_path}:${source.start_line} - ${preview}`;
          }),
        ].join("\n")
      : `I could not find indexed source context for that question in ${context.repo.name}. Run analysis first, then ask again.`;

    return {
      answer,
      sources: context.sources,
      related_nodes:
        payload.include_graph === false ? [] : context.relatedNodes,
      related_edges:
        payload.include_graph === false ? [] : context.relatedEdges,
      related_communities:
        payload.include_graph === false ? [] : context.relatedCommunities,
      trace_id: context.trace.trace_id || randomUUID(),
    };
  }
}

function sourceSnippetsFromTrace(
  trace: RetrievalTrace,
  sourceUrlBase: string | null,
): SourceSnippet[] {
  const snippets: SourceSnippet[] = [];
  const seen = new Set<string>();
  trace.source_chunks.forEach((chunk, index) => {
    const filePath = stringValue(chunk.file_path);
    const startLine = numberValue(chunk.start_line);
    const endLine = numberValue(chunk.end_line);
    const content = stringValue(chunk.content);
    if (!filePath || !startLine || !endLine || !content) {
      return;
    }
    const key = `${filePath}:${startLine}:${endLine}`;
    if (seen.has(key)) {
      return;
    }
    seen.add(key);
    snippets.push({
      ...sourceCitation(
        stringValue(chunk.citation_id) ?? `S${index + 1}`,
        filePath,
        startLine,
        endLine,
        sourceUrlBase,
      ),
      content,
    });
  });
  return snippets;
}

function sourceCitation(
  citationId: string,
  filePath: string,
  startLine: number,
  endLine: number,
  sourceUrlBase: string | null,
): SourceCitation {
  return {
    citation_id: citationId,
    file_path: filePath,
    start_line: startLine,
    end_line: endLine,
    source_url: sourceUrlBase
      ? sourceUrlForRange(sourceUrlBase, filePath, startLine, endLine)
      : null,
  };
}

function qaMessages(context: QuestionContext): LlmOperation["messages"] {
  return [
    {
      role: "system",
      content: loadPrompt("qa.md"),
    },
    {
      role: "user",
      content: stableJsonMessage("Stable QA contract", {
        instructions:
          "Use only this GraphRAG context. Cite files and lines from sources when making code claims.",
      }),
    },
    {
      role: "user",
      content: dynamicJsonMessage(
        "GraphRAG QA payload",
        llmInputPayload(context),
      ),
    },
  ];
}

function llmInputPayload(context: QuestionContext): JsonObject {
  return {
    question: context.question,
    context_pack: context.trace.context_pack,
    source_chunks: context.sourceSnippets.map((source) => ({
      citation_id: source.citation_id,
      file_path: source.file_path,
      start_line: source.start_line,
      end_line: source.end_line,
      source_url: source.source_url,
      content: source.content,
    })),
    related_nodes: context.relatedNodes,
    related_edges: context.relatedEdges,
    community_summaries: context.relatedCommunities,
  };
}

function questionHash(question: string): string {
  return createHash("sha256").update(question).digest("hex").slice(0, 16);
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) ? value : null;
}

function llmMetadata(
  status: "success",
  completion: CachedLlmCompletion,
): JsonObject {
  return {
    status,
    cache_hit: completion.cacheHit,
    run_id: completion.run.id,
    model: completion.result.model,
    provider: completion.result.provider,
  };
}
