import { useEffect, useState } from "react";

import { getRepoGraph } from "../../api/graph";
import type { GraphResponse } from "../../api/types";

export function useRepoGraph({
  selectedRepoId,
  enabled = true,
  reloadToken,
  onGraphLoaded,
  onGraphReset,
  onGraphError
}: {
  selectedRepoId: string;
  enabled?: boolean;
  reloadToken?: number;
  onGraphLoaded: (graph: GraphResponse) => void;
  onGraphReset: () => void;
  onGraphError: (message: string) => void;
}) {
  const [graph, setGraph] = useState<GraphResponse | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!enabled || !selectedRepoId) {
      setGraph(null);
      setLoading(false);
      onGraphReset();
      return;
    }

    let cancelled = false;
    setLoading(true);
    getRepoGraph(selectedRepoId)
      .then((repoGraph) => {
        if (cancelled) {
          return;
        }
        setGraph(repoGraph);
        onGraphLoaded(repoGraph);
      })
      .catch((apiError: unknown) => {
        if (!cancelled) {
          setGraph(null);
          onGraphReset();
          onGraphError(apiError instanceof Error ? apiError.message : "Failed to load repository graph");
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
  }, [enabled, onGraphError, onGraphLoaded, onGraphReset, reloadToken, selectedRepoId]);

  return { graph, loading };
}
