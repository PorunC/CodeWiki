import type { NodeReference } from "./model";

export function ReferenceSection({
  title,
  references,
  onNavigateToNode
}: {
  title: string;
  references: NodeReference[];
  onNavigateToNode: (nodeId: string, edgeType?: string) => void;
}) {
  return (
    <section className="metadata-section">
      <div className="filter-title">{title}</div>
      {references.length > 0 ? (
        <div className="metadata-chips">
          {references.slice(0, 16).map((reference) => (
            <button
              className="metadata-chip"
              disabled={!reference.nodeId}
              key={reference.id}
              onClick={() => {
                if (reference.nodeId) {
                  onNavigateToNode(reference.nodeId, reference.edgeType);
                }
              }}
              title={reference.nodeId ? `Open ${reference.label}` : reference.meta}
              type="button"
            >
              {reference.label}
            </button>
          ))}
          {references.length > 16 ? <span className="metadata-chip">+{references.length - 16}</span> : null}
        </div>
      ) : (
        <span className="muted small-text">None</span>
      )}
    </section>
  );
}
