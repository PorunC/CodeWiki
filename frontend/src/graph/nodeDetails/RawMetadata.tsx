import { formatUnknown } from "../graphModel";
import { DetailItem } from "./DetailItem";

export function RawMetadata({ metadata }: { metadata: Record<string, unknown> }) {
  const entries = Object.entries(metadata).filter(
    ([key]) => key !== "calls" && key !== "imports" && key !== "absolute_path"
  );
  if (entries.length === 0) {
    return null;
  }

  return (
    <section className="metadata-section">
      <div className="filter-title">Metadata</div>
      <dl className="metadata-list">
        {entries.slice(0, 10).map(([key, value]) => (
          <DetailItem key={key} label={key} value={formatUnknown(value)} />
        ))}
      </dl>
    </section>
  );
}
