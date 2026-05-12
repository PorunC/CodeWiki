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
  const isFileNode = data.nodeType === "file";
  const symbolCountLabel = formatSymbolCount(data.countLabel);
  const className = [
    "code-node-card",
    isFileNode ? "is-file" : "",
    data.isFocusMode ? "is-focus-mode" : "",
    data.isContained ? "is-contained" : "",
    data.isExternal ? "is-external" : "",
    data.isSelected ? "is-selected" : "",
    data.isNeighbor ? "is-neighbor" : "",
    data.isAskRelated ? "is-ask-related" : "",
    data.isFaded ? "is-faded" : ""
  ]
    .filter(Boolean)
    .join(" ");
  const title = isFileNode ? `${data.label}\n${data.summary}\n${symbolCountLabel}` : data.label;

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
    <div className={className} title={title} onDoubleClick={handleDoubleClick}>
      <div className="code-node-accent" style={{ background: data.accentColor }} />
      <Handle id={TARGET_HANDLE_ID} type="target" position={Position.Left} className="code-node-handle" />
      <Handle id={SOURCE_HANDLE_ID} type="source" position={Position.Right} className="code-node-handle" />
      <div className="code-node-body">
        {!isFileNode ? (
          <div className="code-node-topline">
            <span className="code-node-type" style={{ color: data.accentColor }}>
              {data.nodeType}
            </span>
            {data.countLabel ? <span className="code-node-count">{data.countLabel}</span> : null}
          </div>
        ) : null}
        <div className="code-node-title">{data.label}</div>
        <div className="code-node-summary">{data.summary}</div>
        {isFileNode ? (
          <div className="code-node-file-symbols">{symbolCountLabel}</div>
        ) : (
          <div className="code-node-meta">
            <span>{data.pathLabel}</span>
            <span>{data.lineLabel}</span>
          </div>
        )}
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

function formatSymbolCount(value?: string): string {
  if (!value) {
    return "0 symbols";
  }
  return value.includes("symbol") ? value : `${value} symbols`;
}

function ContainerFlowNode({ id, data, width, height }: NodeProps<Node<ContainerVisualData, "container">>) {
  const className = [
    "code-container-node",
    data.containerType === "directory" ? "is-directory" : "",
    data.containerType === "file" ? "is-file-container" : "",
    data.isCompact ? "is-compact" : "",
    data.containerType === "dependency" ? "is-dependency" : "",
    data.isSelected ? "is-selected" : "",
    data.isNeighbor ? "is-neighbor" : "",
    data.isAskRelated ? "is-ask-related" : "",
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
