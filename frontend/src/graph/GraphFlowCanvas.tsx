import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlow
} from "@xyflow/react";
import type { MouseEvent } from "react";

import { flowNodeTypes } from "./GraphNodes";
import { miniMapColor, type FlowEdge, type FlowNode } from "./graphModel";

export function GraphFlowCanvas({
  isLoading,
  graphLoaded,
  nodes,
  edges,
  flowKey,
  onNodeClick,
  onNodeDoubleClick
}: {
  isLoading: boolean;
  graphLoaded: boolean;
  nodes: FlowNode[];
  edges: FlowEdge[];
  flowKey: string;
  onNodeClick: (event: MouseEvent, node: FlowNode) => void;
  onNodeDoubleClick: (event: MouseEvent, node: FlowNode) => void;
}) {
  const showGraph = !isLoading && graphLoaded && nodes.length > 0;

  return (
    <div className="flow-frame">
      {isLoading ? <div className="flow-state">Loading graph...</div> : null}
      {!isLoading && graphLoaded && nodes.length === 0 ? (
        <div className="flow-state">No nodes match the current filters.</div>
      ) : null}
      {showGraph ? (
        <ReactFlow
          key={flowKey}
          nodes={nodes}
          edges={edges}
          nodeTypes={flowNodeTypes}
          fitView
          fitViewOptions={{ padding: 0.18 }}
          minZoom={0.04}
          maxZoom={2}
          nodesDraggable={false}
          onNodeClick={onNodeClick}
          onNodeDoubleClick={onNodeDoubleClick}
          zoomOnDoubleClick={false}
          proOptions={{ hideAttribution: true }}
        >
          <Background
            variant={BackgroundVariant.Dots}
            gap={22}
            size={1}
            color="rgba(212, 165, 116, 0.14)"
          />
          <Controls />
          <MiniMap
            maskColor="rgba(8, 9, 10, 0.72)"
            nodeColor={(node) => miniMapColor(node as FlowNode)}
            pannable
            zoomable
          />
        </ReactFlow>
      ) : null}
    </div>
  );
}
