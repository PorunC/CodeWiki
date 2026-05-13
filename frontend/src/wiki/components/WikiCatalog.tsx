import { FileText } from "lucide-react";
import { useMemo } from "react";

import type { WikiCatalogItem, WikiPageRecord } from "../../api/types";
import { firstPageSlugFromItems, sortCatalogItems } from "../catalog";

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
        const page = pageBySlug.get(item.slug);
        const children = item.children ?? [];
        const targetSlug = page?.slug ?? firstPageSlugFromItems(children, pageBySlug);
        const status = page?.status ?? (children.length > 0 ? "group" : "missing");
        return (
          <div key={item.slug} className="wiki-catalog-group">
            <button
              className={`wiki-catalog-item${selectedSlug === item.slug ? " is-active" : ""}`}
              style={{ paddingLeft: 8 + depth * 14 }}
              type="button"
              disabled={!targetSlug}
              onClick={() => {
                if (targetSlug) {
                  onSelect(targetSlug);
                }
              }}
            >
              <FileText size={13} />
              <span>{item.title}</span>
              <strong className={page?.status === "generated" ? "is-generated" : "is-draft"}>
                {status}
              </strong>
            </button>
            {children.length > 0 ? (
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
      })}
    </div>
  );
}
