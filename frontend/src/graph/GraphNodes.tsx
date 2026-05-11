import { Handle, Position, type Node, type NodeProps, type NodeTypes } from "@xyflow/react";
import { EyeOff } from "lucide-react";
import { memo, type MouseEvent } from "react";

import {
  SOURCE_HANDLE_ID,
  TARGET_HANDLE_ID,
  type CodeVisualData,
  type ContainerVisualData
} from "./graphModel";

export const flowNodeTypes: NodeTypes = {
  code: memo(CodeFlowNode),
  container: memo(ContainerFlowNode)
};

function CodeFlowNode({ id, data }: NodeProps<Node<CodeVisualData, "code">>) {
  const className = [
    "code-node-card",
    data.isContained ? "is-contained" : "",
    data.isExternal ? "is-external" : "",
    data.isSelected ? "is-selected" : "",
    data.isNeighbor ? "is-neighbor" : "",
    data.isFaded ? "is-faded" : ""
  ]
    .filter(Boolean)
    .join(" ");

  const handleDoubleClick = (event: MouseEvent<HTMLDivElement>) => {
    if (data.nodeType !== "file" || !data.fileId) {
      return;
    }
    event.stopPropagation();
    window.dispatchEvent(
      new CustomEvent("codewiki:open-file-detail", {
        detail: { fileId: data.fileId }
      })
    );
  };

  const handleHideClick = (event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    window.dispatchEvent(
      new CustomEvent("codewiki:hide-visual-node", {
        detail: { nodeId: id }
      })
    );
  };

  return (
    <div className={className} title={data.label} onDoubleClick={handleDoubleClick}>
      <div className="code-node-accent" style={{ background: data.accentColor }} />
      <Handle id={TARGET_HANDLE_ID} type="target" position={Position.Left} className="code-node-handle" />
      <Handle id={SOURCE_HANDLE_ID} type="source" position={Position.Right} className="code-node-handle" />
      <div className="code-node-body">
        <div className="code-node-topline">
          <span className="code-node-type" style={{ color: data.accentColor }}>
            {data.nodeType}
          </span>
          {data.countLabel ? <span className="code-node-count">{data.countLabel}</span> : null}
        </div>
        <div className="code-node-title">{data.label}</div>
        <div className="code-node-summary">{data.summary}</div>
        <div className="code-node-meta">
          <span>{data.pathLabel}</span>
          <span>{data.lineLabel}</span>
        </div>
      </div>
      <div className="code-node-stats">
        <span>{data.statsLabel || "No visible edges"}</span>
      </div>
      <button
        className="node-hide-button nodrag nopan"
        type="button"
        title="Hide node"
        aria-label={`Hide ${data.label}`}
        onPointerDown={(event) => event.stopPropagation()}
        onClick={handleHideClick}
      >
        <EyeOff size={12} />
      </button>
    </div>
  );
}

function ContainerFlowNode({ id, data, width, height }: NodeProps<Node<ContainerVisualData, "container">>) {
  const className = [
    "code-container-node",
    data.isCompact ? "is-compact" : "",
    data.containerType === "dependency" ? "is-dependency" : "",
    data.isSelected ? "is-selected" : "",
    data.isNeighbor ? "is-neighbor" : "",
    data.isFaded ? "is-faded" : "",
    data.isFocusedViaChild ? "is-focused-via-child" : ""
  ]
    .filter(Boolean)
    .join(" ");

  const handleHideClick = (event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    window.dispatchEvent(
      new CustomEvent("codewiki:hide-visual-node", {
        detail: { nodeId: id }
      })
    );
  };

  return (
    <div className={className} style={{ borderColor: data.accentColor, width, height }}>
      <Handle id={TARGET_HANDLE_ID} type="target" position={Position.Left} className="code-node-handle" />
      <Handle id={SOURCE_HANDLE_ID} type="source" position={Position.Right} className="code-node-handle" />
      <div className="code-container-header">
        <div>
          <span className="code-container-kind" style={{ color: data.accentColor }}>
            {data.subtitle}
          </span>
          <div className="code-container-title">{data.title}</div>
        </div>
        <span className="code-container-count">{data.countLabel}</span>
      </div>
      <div className="code-container-path">{data.pathLabel}</div>
      <div className="code-container-body">
        <span>{data.statsLabel}</span>
      </div>
      <button
        className="node-hide-button nodrag nopan"
        type="button"
        title="Hide node"
        aria-label={`Hide ${data.title}`}
        onPointerDown={(event) => event.stopPropagation()}
        onClick={handleHideClick}
      >
        <EyeOff size={12} />
      </button>
    </div>
  );
}
