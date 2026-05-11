import { Background, Controls, ReactFlow, type Edge, type Node } from "@xyflow/react";

const nodes: Node[] = [
  {
    id: "repo",
    position: { x: 80, y: 80 },
    data: { label: "Repository" },
    type: "input"
  },
  {
    id: "graph-rag",
    position: { x: 330, y: 80 },
    data: { label: "GraphRAG" }
  },
  {
    id: "wiki",
    position: { x: 580, y: 80 },
    data: { label: "Wiki" },
    type: "output"
  }
];

const edges: Edge[] = [
  { id: "repo-graph-rag", source: "repo", target: "graph-rag" },
  { id: "graph-rag-wiki", source: "graph-rag", target: "wiki" }
];

export function GraphPage() {
  return (
    <section id="graph" className="panel graph-panel">
      <header>
        <span className="eyebrow">Graph</span>
        <h2>Code Structure</h2>
      </header>
      <div className="flow-frame">
        <ReactFlow nodes={nodes} edges={edges} fitView>
          <Background />
          <Controls />
        </ReactFlow>
      </div>
    </section>
  );
}
