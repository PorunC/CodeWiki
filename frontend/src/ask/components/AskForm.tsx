import { Send } from "lucide-react";
import type { FormEvent } from "react";

import type { RepoSummary } from "../../api/types";

export function AskForm({
  repos,
  selectedRepoId,
  question,
  loading,
  onRepoChange,
  onQuestionChange,
  onSubmit
}: {
  repos: RepoSummary[];
  selectedRepoId: string;
  question: string;
  loading: boolean;
  onRepoChange: (repoId: string) => void;
  onQuestionChange: (question: string) => void;
  onSubmit: (event: FormEvent) => void;
}) {
  return (
    <form className="ask-form" onSubmit={onSubmit}>
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
        onChange={(event) => onQuestionChange(event.target.value)}
        placeholder="Ask about this repository"
        aria-label="Ask about this repository"
      />
      <button type="submit" disabled={!selectedRepoId || !question.trim() || loading}>
        <Send size={14} />
        {loading ? "Asking" : "Ask"}
      </button>
    </form>
  );
}
