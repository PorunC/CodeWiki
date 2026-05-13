import { useEffect, useMemo, useState } from "react";

import { getRepos } from "../api/repos";
import type { RepoSummary } from "../api/types";

export function useRepos({
  selectedRepoId,
  onRepoChange,
  autoSelect = true
}: {
  selectedRepoId: string;
  onRepoChange: (repoId: string) => void;
  autoSelect?: boolean;
}) {
  const [repos, setRepos] = useState<RepoSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;

    setLoading(true);
    setError(null);
    getRepos()
      .then((repoList) => {
        if (cancelled) {
          return;
        }
        setRepos(repoList);
        if (autoSelect && !selectedRepoId && repoList[0]) {
          onRepoChange(repoList[0].id);
        }
      })
      .catch((apiError: unknown) => {
        if (!cancelled) {
          setError(apiError instanceof Error ? apiError.message : "Failed to load repositories");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [autoSelect, onRepoChange, reloadToken, selectedRepoId]);

  const selectedRepo = useMemo(
    () => repos.find((repo) => repo.id === selectedRepoId) ?? null,
    [repos, selectedRepoId]
  );

  return {
    repos,
    selectedRepo,
    loading,
    error,
    refresh: () => setReloadToken((value) => value + 1)
  };
}
