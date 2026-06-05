import { ChevronDown, ChevronRight, FileText } from "lucide-react";
import { useEffect, useMemo, useState, type CSSProperties } from "react";

import type { WikiCatalogItem, WikiPageRecord } from "../../api/types";
import {
  catalogItemTitle,
  catalogSlug,
  firstPageSlugFromItems,
  sortCatalogItems
} from "../catalog";

export function WikiCatalog({
  items,
  pageBySlug,
  selectedSlug,
  onSelect,
  depth = 0
}: {
  items: WikiCatalogItem[];
  pageBySlug: Map<string, WikiPageRecord>;
  selectedSlug: string | null;
  onSelect: (slug: string) => void;
  depth?: number;
}) {
  const orderedItems = useMemo(() => sortCatalogItems(items), [items]);
  return (
    <div className="wiki-catalog-level">
      {orderedItems.map((item) => {
        const slug = catalogSlug(item);
        const page = pageBySlug.get(slug);
        const children = item.children ?? [];
        const targetSlug = page?.slug ?? firstPageSlugFromItems(children, pageBySlug);
        const status = page?.status ?? (children.length > 0 ? "group" : "missing");
        return (
          <WikiCatalogNode
            key={slug}
            item={item}
            slug={slug}
            page={page}
            pageBySlug={pageBySlug}
            selectedSlug={selectedSlug}
            targetSlug={targetSlug}
            status={status}
            onSelect={onSelect}
            depth={depth}
          />
        );
      })}
    </div>
  );
}

function WikiCatalogNode({
  item,
  slug,
  page,
  pageBySlug,
  selectedSlug,
  targetSlug,
  status,
  onSelect,
  depth
}: {
  item: WikiCatalogItem;
  slug: string;
  page: WikiPageRecord | undefined;
  pageBySlug: Map<string, WikiPageRecord>;
  selectedSlug: string | null;
  targetSlug: string | null;
  status: string;
  onSelect: (slug: string) => void;
  depth: number;
}) {
  const children = useMemo(() => item.children ?? [], [item.children]);
  const title = catalogItemTitle(item);
  const hasChildren = children.length > 0;
  const containsSelectedSlug = useMemo(
    () => Boolean(selectedSlug && catalogItemContainsSlug(children, selectedSlug)),
    [children, selectedSlug]
  );
  const [expanded, setExpanded] = useState(true);

  useEffect(() => {
    if (containsSelectedSlug) {
      setExpanded(true);
    }
  }, [containsSelectedSlug]);

  return (
    <div className="wiki-catalog-group">
      <div className="wiki-catalog-row" style={{ "--wiki-catalog-depth": depth } as CSSProperties}>
        {hasChildren ? (
          <button
            className="wiki-catalog-toggle"
            type="button"
            aria-label={`${expanded ? "Collapse" : "Expand"} ${title}`}
            aria-expanded={expanded}
            onClick={() => setExpanded((current) => !current)}
          >
            {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </button>
        ) : (
          <span className="wiki-catalog-toggle-placeholder" aria-hidden="true" />
        )}
        <button
          className={`wiki-catalog-item${selectedSlug === slug ? " is-active" : ""}`}
          type="button"
          disabled={!targetSlug}
          onClick={() => {
            if (targetSlug) {
              onSelect(targetSlug);
            }
          }}
        >
          <FileText size={13} />
          <span>{title}</span>
          <strong className={page?.status === "generated" ? "is-generated" : "is-draft"}>{status}</strong>
        </button>
      </div>
      {hasChildren && expanded ? (
        <WikiCatalog
          items={children}
          pageBySlug={pageBySlug}
          selectedSlug={selectedSlug}
          onSelect={onSelect}
          depth={depth + 1}
        />
      ) : null}
    </div>
  );
}

function catalogItemContainsSlug(items: WikiCatalogItem[], slug: string): boolean {
  return items.some((item) => {
    if (catalogSlug(item) === slug) {
      return true;
    }
    return catalogItemContainsSlug(item.children ?? [], slug);
  });
}
