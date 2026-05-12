import { Send, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";

import {
  askRepo,
  getRepos,
  type AskResponse,
  type RepoSummary,
  type SourceRef
} from "../api/client";

export function AskPage({
  selectedRepoId,
  onRepoChange
}: {
  selectedRepoId: string;
  onRepoChange: (repoId: string) => void;
}) {
  const [repos, setRepos] = useState<RepoSummary[]>([]);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<AskResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getRepos()
      .then((repoList) => {
        if (cancelled) {
          return;
        }
        setRepos(repoList);
        if (!selectedRepoId && repoList[0]) {
          onRepoChange(repoList[0].id);
        }
      })
      .catch((apiError: unknown) => {
        if (!cancelled) {
          setError(apiError instanceof Error ? apiError.message : "Failed to load repositories");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [onRepoChange, selectedRepoId]);

  const selectedRepo = useMemo(
    () => repos.find((repo) => repo.id === selectedRepoId) ?? null,
    [repos, selectedRepoId]
  );

  const relatedNodeIds = useMemo(
    () =>
      answer?.related_nodes
        .map((node) => node.id)
        .filter((nodeId): nodeId is string => typeof nodeId === "string") ?? [],
    [answer?.related_nodes]
  );

  const submitQuestion = async (event: FormEvent) => {
    event.preventDefault();
    const trimmedQuestion = question.trim();
    if (!selectedRepoId || !trimmedQuestion || loading) {
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const response = await askRepo(selectedRepoId, trimmedQuestion);
      setAnswer(response);
      highlightRelatedNodes(selectedRepoId, response);
    } catch (apiError) {
      setAnswer(null);
      setError(apiError instanceof Error ? apiError.message : "Ask failed");
    } finally {
      setLoading(false);
    }
  };

  const highlightCurrentAnswer = () => {
    if (answer && selectedRepoId) {
      highlightRelatedNodes(selectedRepoId, answer);
    }
  };

  return (
    <section id="ask" className="side-panel ask-panel">
      <header>
        <span className="eyebrow">Ask</span>
        <h2>GraphRAG</h2>
      </header>

      <form className="ask-form" onSubmit={submitQuestion}>
        <select
          value={selectedRepoId}
          onChange={(event) => onRepoChange(event.target.value)}
          aria-label="Repository for question"
        >
          {repos.length === 0 ? <option value="">No repositories</option> : null}
          {repos.map((repo) => (
            <option key={repo.id} value={repo.id}>
              {repo.name}
            </option>
          ))}
        </select>
        <input
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Ask about this repository"
          aria-label="Ask about this repository"
        />
        <button type="submit" disabled={!selectedRepoId || !question.trim() || loading}>
          <Send size={14} />
          {loading ? "Asking" : "Ask"}
        </button>
      </form>

      {selectedRepo ? <div className="ask-repo-path">{selectedRepo.path}</div> : null}
      {error ? <div className="ask-error">{error}</div> : null}

      {answer ? (
        <div className="ask-result">
          <div className="ask-answer">{answer.answer}</div>

          <button
            className="ask-highlight-button"
            type="button"
            disabled={relatedNodeIds.length === 0}
            onClick={highlightCurrentAnswer}
          >
            <Sparkles size={14} />
            Highlight graph
          </button>

          <AskSources sources={answer.sources} />
          <AskRelatedNodes nodes={answer.related_nodes} />
        </div>
      ) : null}
    </section>
  );
}

function AskSources({ sources }: { sources: SourceRef[] }) {
  if (sources.length === 0) {
    return null;
  }
  return (
    <div className="ask-section">
      <h3>Sources</h3>
      <div className="ask-chip-list">
        {sources.slice(0, 8).map((source) => (
          <span key={`${source.file_path}:${source.start_line}:${source.end_line}`} className="ask-chip">
            {source.file_path}:L{source.start_line}-L{source.end_line}
          </span>
        ))}
      </div>
    </div>
  );
}

function AskRelatedNodes({ nodes }: { nodes: AskResponse["related_nodes"] }) {
  if (nodes.length === 0) {
    return null;
  }
  return (
    <div className="ask-section">
      <h3>Related nodes</h3>
      <div className="ask-node-list">
        {nodes.slice(0, 6).map((node) => (
          <div key={String(node.id)} className="ask-node-row">
            <span>{String(node.name ?? node.id)}</span>
            <strong>{String(node.type ?? "node")}</strong>
          </div>
        ))}
      </div>
    </div>
  );
}

function highlightRelatedNodes(repoId: string, response: AskResponse) {
  const nodeIds = response.related_nodes
    .map((node) => node.id)
    .filter((nodeId): nodeId is string => typeof nodeId === "string");
  window.dispatchEvent(
    new CustomEvent("codewiki:highlight-related-nodes", {
      detail: { repoId, nodeIds }
    })
  );
}
