import { ExternalLink, Sparkles } from "lucide-react";

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
  const groups = groupSourceRefs(sources).slice(0, 8);
  return (
    <div className="ask-section">
      <h3>Sources</h3>
      <div className="ask-source-list">
        {groups.map((group) => (
          <div key={group.filePath} className="ask-source-group">
            <span>{group.filePath}</span>
            <div>
              {group.refs.map((source) =>
                source.source_url ? (
                  <a
                    key={`${source.file_path}:${source.start_line}:${source.end_line}`}
                    className="ask-chip"
                    href={source.source_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {source.citation_id ? `${source.citation_id} ` : ""}
                    L{source.start_line}-L{source.end_line}
                    <ExternalLink size={11} />
                  </a>
                ) : (
                  <span
                    key={`${source.file_path}:${source.start_line}:${source.end_line}`}
                    className="ask-chip"
                  >
                    {source.citation_id ? `${source.citation_id} ` : ""}
                    L{source.start_line}-L{source.end_line}
                  </span>
                )
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

type SourceGroup = {
  filePath: string;
  refs: SourceRef[];
};

function groupSourceRefs(sourceRefs: SourceRef[]): SourceGroup[] {
  const groups = new Map<string, SourceRef[]>();
  sourceRefs.forEach((sourceRef) => {
    const group = groups.get(sourceRef.file_path) ?? [];
    group.push(sourceRef);
    groups.set(sourceRef.file_path, group);
  });
  return Array.from(groups, ([filePath, refs]) => ({
    filePath,
    refs: refs
      .slice()
      .sort((left, right) => left.start_line - right.start_line || left.end_line - right.end_line)
  }));
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
