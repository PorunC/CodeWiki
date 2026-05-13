import { useEffect, useState } from "react";

import { getRepoGraph } from "../../api/graph";
import type { GraphResponse } from "../../api/types";

export function useRepoGraph({
  selectedRepoId,
  onGraphLoaded,
  onGraphReset,
  onGraphError
}: {
  selectedRepoId: string;
  onGraphLoaded: (graph: GraphResponse) => void;
  onGraphReset: () => void;
  onGraphError: (message: string) => void;
}) {
  const [graph, setGraph] = useState<GraphResponse | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!selectedRepoId) {
      setGraph(null);
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
  }, [onGraphError, onGraphLoaded, onGraphReset, selectedRepoId]);

  return { graph, loading };
}
