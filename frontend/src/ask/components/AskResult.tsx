import { Sparkles } from "lucide-react";

import type { AskResponse, SourceRef } from "../../api/types";

export function AskResult({
  answer,
  relatedNodeIds,
  onHighlight
}: {
  answer: AskResponse;
  relatedNodeIds: string[];
  onHighlight: () => void;
}) {
  return (
    <div className="ask-result">
      <div className="ask-answer">{answer.answer}</div>

      <button
        className="ask-highlight-button"
        type="button"
        disabled={relatedNodeIds.length === 0}
        onClick={onHighlight}
      >
        <Sparkles size={14} />
        Highlight graph
      </button>

      <AskSources sources={answer.sources} />
      <AskRelatedNodes nodes={answer.related_nodes} />
    </div>
  );
}

function AskSources({ sources }: { sources: SourceRef[] }) {
  if (sources.length === 0) {
    return null;
  }
  return (
    <div className="ask-section">
      <h3>Sources</h3>
      <div className="ask-chip-list">
        {sources.slice(0, 8).map((source) => (
          <span key={`${source.file_path}:${source.start_line}:${source.end_line}`} className="ask-chip">
            {source.file_path}:L{source.start_line}-L{source.end_line}
          </span>
        ))}
      </div>
    </div>
  );
}

function AskRelatedNodes({ nodes }: { nodes: AskResponse["related_nodes"] }) {
  if (nodes.length === 0) {
    return null;
  }
  return (
    <div className="ask-section">
      <h3>Related nodes</h3>
      <div className="ask-node-list">
        {nodes.slice(0, 6).map((node) => (
          <div key={String(node.id)} className="ask-node-row">
            <span>{String(node.name ?? node.id)}</span>
            <strong>{String(node.type ?? "node")}</strong>
          </div>
        ))}
      </div>
    </div>
  );
}
