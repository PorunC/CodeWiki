import type { CodeWikiStore } from "../db/store.js";
import { notFoundError, validationError } from "../errors.js";
import {
  LlmCallError,
  type CachedLlmCompletion,
  type LlmOperation,
} from "../llm/cache.js";
import type { JsonObject } from "../types.js";

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
  source_url: null;
};

type SourceSnippet = SourceCitation & {
  content: string;
};

type QuestionContext = {
  repoName: string;
  question: string;
  sources: SourceCitation[];
  promptSources: SourceCitation[];
  sourceSnippets: SourceSnippet[];
  relatedNodes: JsonObject[];
};

export class QuestionAnswerer {
  constructor(
    private readonly store: CodeWikiStore,
    private readonly llm?: QuestionAnswerLlm,
  ) {}

  answer(
    repoId: string,
    payload: QuestionAnswerRequest,
  ): Record<string, unknown> {
    const context = this.questionContext(repoId, payload);
    return this.localAnswer(payload, context);
  }

  async answerWithLlmFallback(
    repoId: string,
    payload: QuestionAnswerRequest,
  ): Promise<Record<string, unknown>> {
    const context = this.questionContext(repoId, payload);
    const fallback = this.localAnswer(payload, context);
    if (!this.llm?.isConfigured("qa") || context.sourceSnippets.length === 0) {
      return fallback;
    }

    try {
      const completion = await this.llm.complete(repoId, {
        taskType: "qa",
        cacheKey: `qa:${context.question}`,
        modelAlias: "qa",
        promptVersion: "ts-qa-v1",
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

  private questionContext(
    repoId: string,
    payload: QuestionAnswerRequest,
  ): QuestionContext {
    const repo = this.store.getRepo(repoId);
    if (!repo) {
      throw notFoundError("Repository", repoId);
    }
    const question = payload.question.trim();
    if (!question) {
      throw validationError("Question must be a non-empty string.");
    }

    const hits = this.store.searchCodeChunks(repoId, question, 8);
    const graphHits = this.store.searchCodeNodes(repoId, question, {
      limit: 10,
    });
    const promptSources = hits.map((hit, index) => ({
      citation_id: `S${index + 1}`,
      file_path: hit.chunk.file_path,
      start_line: hit.chunk.start_line,
      end_line: hit.chunk.end_line,
      source_url: null,
    }));
    return {
      repoName: repo.name,
      question,
      promptSources,
      sources: payload.include_sources === false ? [] : promptSources,
      sourceSnippets: hits.slice(0, 8).map((hit, index) => ({
        citation_id: `S${index + 1}`,
        file_path: hit.chunk.file_path,
        start_line: hit.chunk.start_line,
        end_line: hit.chunk.end_line,
        source_url: null,
        content: hit.chunk.content,
      })),
      relatedNodes:
        payload.include_graph === false
          ? []
          : graphHits.map((hit) => graphNodePayload(hit.node)),
    };
  }

  private localAnswer(
    payload: QuestionAnswerRequest,
    context: QuestionContext,
  ): Record<string, unknown> {
    const answer = context.sourceSnippets.length
      ? [
          `I found ${context.promptSources.length} relevant source section${context.promptSources.length === 1 ? "" : "s"} in ${context.repoName}.`,
          "",
          ...context.sourceSnippets.slice(0, 4).map((source) => {
            const preview = String(source.content)
              .trim()
              .replace(/\s+/g, " ")
              .slice(0, 240);
            return `[${source.citation_id}] ${source.file_path}:${source.start_line} - ${preview}`;
          }),
        ].join("\n")
      : `I could not find indexed source context for that question in ${context.repoName}. Run analysis first, then ask again.`;

    return {
      answer,
      sources: context.sources,
      related_nodes:
        payload.include_graph === false ? [] : context.relatedNodes,
      related_edges: [],
      related_communities: [],
      trace_id: crypto.randomUUID(),
    };
  }
}

function graphNodePayload(node: {
  id: string;
  type: string;
  name: string;
  file_path: string;
  start_line: number | null;
  end_line: number | null;
  language: string | null;
  symbol_id: string | null;
  metadata: JsonObject;
}): JsonObject {
  return {
    id: node.id,
    type: node.type,
    name: node.name,
    file_path: node.file_path,
    start_line: node.start_line,
    end_line: node.end_line,
    language: node.language,
    symbol_id: node.symbol_id,
    metadata: node.metadata,
  };
}

function qaMessages(context: QuestionContext): LlmOperation["messages"] {
  return [
    {
      role: "system",
      content: [
        "You answer questions about a source repository using only the provided CodeWiki context.",
        "Cite source snippets with bracketed citation ids such as [S1].",
        "If the context is insufficient, say what is missing instead of guessing.",
      ].join(" "),
    },
    {
      role: "user",
      content: `Question and source context:\n${JSON.stringify(llmInputPayload(context))}`,
    },
  ];
}

function llmInputPayload(context: QuestionContext): JsonObject {
  return {
    repo_name: context.repoName,
    question: context.question,
    sources: context.sourceSnippets,
    related_nodes: context.relatedNodes,
  };
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
