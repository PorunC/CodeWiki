import { useEffect, useMemo, useState } from "react";

import type { WikiResponse } from "../../api/types";
import { getRepoWiki } from "../../api/wiki";
import { firstPageSlugFromItems } from "../catalog";

export function useWikiData(selectedRepoId: string) {
  const [wiki, setWiki] = useState<WikiResponse | null>(null);
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshNonce, setRefreshNonce] = useState(0);

  useEffect(() => {
    if (!selectedRepoId) {
      setWiki(null);
      setSelectedSlug(null);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);
    getRepoWiki(selectedRepoId)
      .then((response) => {
        if (cancelled) {
          return;
        }
        setWiki(response);
        setSelectedSlug((current) => {
          if (current && response.pages.some((page) => page.slug === current)) {
            return current;
          }
          const pageBySlug = new Map(response.pages.map((page) => [page.slug, page]));
          return firstPageSlugFromItems(response.items, pageBySlug) ?? response.pages[0]?.slug ?? null;
        });
      })
      .catch((apiError: unknown) => {
        if (!cancelled) {
          setWiki(null);
          setSelectedSlug(null);
          setError(apiError instanceof Error ? apiError.message : "Failed to load wiki");
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
  }, [refreshNonce, selectedRepoId]);

  const pageBySlug = useMemo(
    () => new Map((wiki?.pages ?? []).map((page) => [page.slug, page])),
    [wiki?.pages]
  );
  const selectedPage = selectedSlug ? pageBySlug.get(selectedSlug) ?? null : null;

  return {
    wiki,
    selectedSlug,
    selectedPage,
    pageBySlug,
    loading,
    error,
    refresh: () => setRefreshNonce((nonce) => nonce + 1),
    setSelectedSlug
  };
}
