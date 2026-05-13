import { AskForm } from "../ask/components/AskForm";
import { AskResult } from "../ask/components/AskResult";
import { useAsk } from "../ask/hooks/useAsk";
import { useRepos } from "../hooks/useRepos";

export function AskPage({
  selectedRepoId,
  onRepoChange,
  isActiveSection
}: {
  selectedRepoId: string;
  onRepoChange: (repoId: string) => void;
  isActiveSection: boolean;
}) {
  const { repos, selectedRepo, error: repoError } = useRepos({ selectedRepoId, onRepoChange });
  const {
    question,
    setQuestion,
    answer,
    loading,
    error: askError,
    relatedNodeIds,
    submitQuestion,
    highlightCurrentAnswer
  } = useAsk(selectedRepoId);

  return (
    <section id="ask" className={`side-panel ask-panel${isActiveSection ? " is-nav-target" : ""}`}>
      <header>
        <span className="eyebrow">Ask</span>
        <h2>GraphRAG</h2>
      </header>

      <AskForm
        repos={repos}
        selectedRepoId={selectedRepoId}
        question={question}
        loading={loading}
        onRepoChange={onRepoChange}
        onQuestionChange={setQuestion}
        onSubmit={submitQuestion}
      />

      {selectedRepo ? <div className="ask-repo-path">{selectedRepo.path}</div> : null}
      {repoError || askError ? <div className="ask-error">{repoError ?? askError}</div> : null}

      {answer ? (
        <AskResult answer={answer} relatedNodeIds={relatedNodeIds} onHighlight={highlightCurrentAnswer} />
      ) : null}
    </section>
  );
}
