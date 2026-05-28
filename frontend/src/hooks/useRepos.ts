import { useEffect, useMemo, useRef, useState } from "react";

import { getRepos } from "../api/repos";
import type { RepoSummary } from "../api/types";

export function useRepos({
  selectedRepoId,
  onRepoChange,
  autoSelect = true,
  enabled = true
}: {
  selectedRepoId: string;
  onRepoChange: (repoId: string) => void;
  autoSelect?: boolean;
  enabled?: boolean;
}) {
  const [repos, setRepos] = useState<RepoSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const selectedRepoIdRef = useRef(selectedRepoId);
  const onRepoChangeRef = useRef(onRepoChange);

  useEffect(() => {
    selectedRepoIdRef.current = selectedRepoId;
    onRepoChangeRef.current = onRepoChange;
  }, [onRepoChange, selectedRepoId]);

  useEffect(() => {
    if (!enabled) {
      setLoading(false);
      return;
    }

    let cancelled = false;

    setLoading(true);
    setError(null);
    getRepos()
      .then((repoList) => {
        if (cancelled) {
          return;
        }
        setRepos(repoList);
        if (autoSelect && !selectedRepoIdRef.current && repoList[0]) {
          onRepoChangeRef.current(repoList[0].id);
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
  }, [autoSelect, enabled, reloadToken]);

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
