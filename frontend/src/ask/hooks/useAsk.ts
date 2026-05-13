import { useCallback, useMemo, useState, type FormEvent } from "react";

import { askRepo } from "../../api/ask";
import type { AskResponse } from "../../api/types";
import { getRelatedNodeIds, highlightRelatedNodes } from "../graphHighlight";

export function useAsk(selectedRepoId: string) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<AskResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const relatedNodeIds = useMemo(() => getRelatedNodeIds(answer), [answer]);

  const submitQuestion = useCallback(
    async (event: FormEvent) => {
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
    },
    [loading, question, selectedRepoId]
  );

  const highlightCurrentAnswer = useCallback(() => {
    if (answer && selectedRepoId) {
      highlightRelatedNodes(selectedRepoId, answer);
    }
  }, [answer, selectedRepoId]);

  return {
    question,
    setQuestion,
    answer,
    loading,
    error,
    relatedNodeIds,
    submitQuestion,
    highlightCurrentAnswer
  };
}
