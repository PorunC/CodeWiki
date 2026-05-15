import { ChevronRight, FileCode2, Focus, FolderOpen, Network } from "lucide-react";
import type { ReactNode } from "react";

import type { CodeNode, GraphResponse, RepoSummary } from "../api/types";
import {
  compactFilePath,
  fileDisplayName,
  graphTypeLabel,
  isFileLikeNode,
  type DrilldownContainerSelection,
  type GraphViewMode,
  type VisualNodeData
} from "./graphModel";

type BreadcrumbItem = {
  id: string;
  icon: ReactNode;
  label: string;
  meta?: string;
  title?: string;
  active?: boolean;
  onClick?: () => void;
};

export function GraphBreadcrumbs({
  selectedRepo,
  graph,
  viewMode,
  drilldownContainer,
  selectedFileId,
  selectedNode,
  selectedVisualData,
  onModeSelect,
  onOverviewSelect
}: {
  selectedRepo: RepoSummary | null;
  graph: GraphResponse | null;
  viewMode: GraphViewMode;
  drilldownContainer: DrilldownContainerSelection | null;
  selectedFileId: string | null;
  selectedNode: CodeNode | null;
  selectedVisualData: VisualNodeData | null;
  onModeSelect: (mode: GraphViewMode) => void;
  onOverviewSelect: () => void;
}) {
  const selectedFile = selectedFileId ? graph?.nodes.find((node) => node.id === selectedFileId) ?? null : null;
  const overviewSelection = viewMode === "overview" ? selectedVisualData ?? selectedNode : null;
  const items: BreadcrumbItem[] = [
    {
      id: "overview",
      icon: <Network size={14} />,
      label: "Overview",
      meta: selectedRepo?.name,
      active: viewMode === "overview" && !overviewSelection,
      onClick: viewMode === "overview" && !overviewSelection ? undefined : onOverviewSelect
    }
  ];

  if (overviewSelection) {
    items.push(selectionBreadcrumb(overviewSelection));
  } else {
    if (drilldownContainer && viewMode !== "overview") {
      items.push({
        id: "drilldown",
        icon: <FolderOpen size={14} />,
        label: drilldownContainer.title,
        meta: `${graphTypeLabel(drilldownContainer.containerType)} detail`,
        title: drilldownContainer.pathLabel,
        active: viewMode === "drilldown",
        onClick: viewMode === "drilldown" ? undefined : () => onModeSelect("drilldown")
      });
    }

    if (selectedFile && (viewMode === "file" || viewMode === "focus")) {
      items.push({
        id: "file",
        icon: <FileCode2 size={14} />,
        label: fileDisplayName(selectedFile),
        meta: compactFilePath(selectedFile.file_path ?? selectedFile.name),
        title: selectedFile.file_path ?? selectedFile.name,
        active: viewMode === "file",
        onClick: viewMode === "file" ? undefined : () => onModeSelect("file")
      });
    }

    if (viewMode === "focus" && selectedNode) {
      items.push({
        id: "focus",
        icon: <Focus size={14} />,
        label: focusLabel(selectedNode),
        meta: `${graphTypeLabel(selectedNode.type)} focus`,
        title: selectedNode.file_path ?? selectedNode.name,
        active: true
      });
    }
  }

  return (
    <nav className="graph-breadcrumbs" aria-label="Graph breadcrumb">
      <ol>
        {items.map((item, index) => (
          <li key={item.id} className="graph-breadcrumb-item">
            {index > 0 ? (
              <ChevronRight className="graph-breadcrumb-separator" size={14} aria-hidden="true" />
            ) : null}
            {item.onClick ? (
              <button
                className="graph-breadcrumb-button"
                type="button"
                title={item.title ?? item.label}
                onClick={item.onClick}
              >
                {item.icon}
                <BreadcrumbText item={item} />
              </button>
            ) : (
              <span
                className={`graph-breadcrumb-current${item.active ? " is-active" : ""}`}
                title={item.title ?? item.label}
                aria-current={item.active ? "page" : undefined}
              >
                {item.icon}
                <BreadcrumbText item={item} />
              </span>
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}

function BreadcrumbText({ item }: { item: BreadcrumbItem }) {
  return (
    <span className="graph-breadcrumb-text">
      <span className="graph-breadcrumb-label">{item.label}</span>
      {item.meta ? <span className="graph-breadcrumb-meta">{item.meta}</span> : null}
    </span>
  );
}

function selectionBreadcrumb(selection: VisualNodeData | CodeNode): BreadcrumbItem {
  if ("kind" in selection) {
    if (selection.kind === "container") {
      return {
        id: `selection:${selection.containerType}:${selection.title}`,
        icon: <FolderOpen size={14} />,
        label: selection.title,
        meta: `${graphTypeLabel(selection.containerType)} detail`,
        title: selection.pathLabel,
        active: true
      };
    }
    return {
      id: `selection:${selection.nodeType}:${selection.label}`,
      icon: isFileLikeNode(selection.codeNode) ? <FileCode2 size={14} /> : <Focus size={14} />,
      label: isFileLikeNode(selection.codeNode) ? fileDisplayName(selection.codeNode) : selection.label,
      meta: `${graphTypeLabel(selection.nodeType)} detail`,
      title: selection.pathLabel,
      active: true
    };
  }

  return {
    id: `selection:${selection.id}`,
    icon: isFileLikeNode(selection) ? <FileCode2 size={14} /> : <Focus size={14} />,
    label: isFileLikeNode(selection) ? fileDisplayName(selection) : focusLabel(selection),
    meta: `${graphTypeLabel(selection.type)} detail`,
    title: selection.file_path ?? selection.name,
    active: true
  };
}

function focusLabel(node: CodeNode): string {
  if (isFileLikeNode(node)) {
    return fileDisplayName(node);
  }
  return node.name || node.symbol_id || "Selected node";
}
