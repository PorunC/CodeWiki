import { ChevronRight, FileCode2, Focus, FolderOpen, Layers2, Network } from "lucide-react";
import type { ReactNode } from "react";

import type { CodeNode, GraphCommunity, GraphResponse, RepoSummary } from "../api/types";
import {
  compactFilePath,
  fileDisplayName,
  graphTypeLabel,
  isFileLikeNode,
  type CommunityLevelMode,
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
  communityLevelMode,
  communityScopeParentId,
  communityHierarchyAvailable,
  detailedCommunitiesAvailable,
  graphLoaded,
  onModeSelect,
  onOverviewSelect,
  onCommunityLevelSelect
}: {
  selectedRepo: RepoSummary | null;
  graph: GraphResponse | null;
  viewMode: GraphViewMode;
  drilldownContainer: DrilldownContainerSelection | null;
  selectedFileId: string | null;
  selectedNode: CodeNode | null;
  selectedVisualData: VisualNodeData | null;
  communityLevelMode: CommunityLevelMode;
  communityScopeParentId: string | null;
  communityHierarchyAvailable: boolean;
  detailedCommunitiesAvailable: boolean;
  graphLoaded: boolean;
  onModeSelect: (mode: GraphViewMode) => void;
  onOverviewSelect: () => void;
  onCommunityLevelSelect: (mode: CommunityLevelMode, scopeParentId?: string | null) => void;
}) {
  const selectedFile = selectedFileId ? graph?.nodes.find((node) => node.id === selectedFileId) ?? null : null;
  const overviewSelection = viewMode === "overview" ? selectedVisualData ?? selectedNode : null;
  const showCommunityNavigation =
    communityHierarchyAvailable &&
    (viewMode === "overview" || (viewMode === "drilldown" && drilldownContainer?.containerType === "community"));
  const communityNavigationItems =
    showCommunityNavigation
      ? communityBreadcrumbItems({
          graph,
          graphLoaded,
          communityLevelMode,
          communityScopeParentId,
          detailedCommunitiesAvailable,
          showCurrentLevel: viewMode === "overview" && !overviewSelection,
          onCommunityLevelSelect
        })
      : [];
  const overviewIsRoot =
    viewMode === "overview" &&
    !overviewSelection &&
    communityLevelMode === "parents" &&
    communityScopeParentId === null;
  const items: BreadcrumbItem[] = [
    {
      id: "overview",
      icon: <Network size={14} />,
      label: "Overview",
      meta: selectedRepo?.name,
      active: overviewIsRoot && communityNavigationItems.length === 0,
      onClick: overviewIsRoot ? undefined : onOverviewSelect
    }
  ];

  items.push(...communityNavigationItems);

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
                className={`graph-breadcrumb-button${item.active ? " is-active" : ""}`}
                type="button"
                title={item.title ?? item.label}
                aria-current={item.active ? "page" : undefined}
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

const COMMUNITY_LEVEL_LABELS: Record<CommunityLevelMode, string> = {
  parents: "Architecture areas",
  children: "Implementation areas",
  details: "Detailed areas"
};

const COMMUNITY_LEVEL_META: Record<CommunityLevelMode, string> = {
  parents: "community level",
  children: "community level",
  details: "community level"
};

function BreadcrumbText({ item }: { item: BreadcrumbItem }) {
  return (
    <span className="graph-breadcrumb-text">
      <span className="graph-breadcrumb-label">{item.label}</span>
      {item.meta ? <span className="graph-breadcrumb-meta">{item.meta}</span> : null}
    </span>
  );
}

function communityBreadcrumbItems({
  graph,
  graphLoaded,
  communityLevelMode,
  communityScopeParentId,
  detailedCommunitiesAvailable,
  showCurrentLevel,
  onCommunityLevelSelect
}: {
  graph: GraphResponse | null;
  graphLoaded: boolean;
  communityLevelMode: CommunityLevelMode;
  communityScopeParentId: string | null;
  detailedCommunitiesAvailable: boolean;
  showCurrentLevel: boolean;
  onCommunityLevelSelect: (mode: CommunityLevelMode, scopeParentId?: string | null) => void;
}): BreadcrumbItem[] {
  const communitiesById = new Map((graph?.communities ?? []).map((community) => [community.id, community]));
  const scopeChain = communityScopeParentId ? communityAncestorChain(communitiesById, communityScopeParentId) : [];
  const architectureScope = scopeChain.find((community) => community.level === 0) ?? null;
  const implementationScope = scopeChain.find((community) => community.level === 1) ?? null;
  const items: BreadcrumbItem[] = [];

  const addLevelItem = (mode: CommunityLevelMode, scopeParentId: string | null = null) => {
    const isCurrent = communityLevelMode === mode && communityScopeParentId === scopeParentId;
    const isActive = showCurrentLevel && communityLevelMode === mode;
    items.push({
      id: `community-level:${mode}:${scopeParentId ?? "all"}`,
      icon: <Layers2 size={14} />,
      label: COMMUNITY_LEVEL_LABELS[mode],
      meta: COMMUNITY_LEVEL_META[mode],
      active: isActive,
      onClick:
        graphLoaded && (!isCurrent || !showCurrentLevel)
          ? () => onCommunityLevelSelect(mode, scopeParentId)
          : undefined
    });
  };

  const addScopeItem = (community: GraphCommunity, mode: CommunityLevelMode, scopeParentId: string) => {
    const isCurrent = communityLevelMode === mode && communityScopeParentId === scopeParentId;
    items.push({
      id: `community-scope:${community.id}`,
      icon: <FolderOpen size={14} />,
      label: community.name,
      meta: communityRoleLabel(community.level),
      title: community.summary || community.name,
      onClick:
        graphLoaded && (!isCurrent || !showCurrentLevel)
          ? () => onCommunityLevelSelect(mode, scopeParentId)
          : undefined
    });
  };

  addLevelItem("parents");
  if (architectureScope) {
    addScopeItem(architectureScope, "children", architectureScope.id);
  }

  if (communityLevelMode !== "parents" || architectureScope) {
    addLevelItem("children", architectureScope?.id ?? null);
  }

  if (detailedCommunitiesAvailable) {
    if (implementationScope) {
      addScopeItem(implementationScope, "details", implementationScope.id);
    }
    if (communityLevelMode === "details" || implementationScope) {
      addLevelItem("details", implementationScope?.id ?? null);
    }
  }

  return items;
}

function communityAncestorChain(
  communitiesById: Map<string, GraphCommunity>,
  communityId: string
): GraphCommunity[] {
  const chain: GraphCommunity[] = [];
  const seen = new Set<string>();
  let current = communitiesById.get(communityId);

  while (current && !seen.has(current.id)) {
    chain.unshift(current);
    seen.add(current.id);
    current = current.parent_id ? communitiesById.get(current.parent_id) : undefined;
  }

  return chain;
}

function communityRoleLabel(level: number): string {
  if (level === 0) {
    return "architecture area";
  }
  if (level === 1) {
    return "implementation area";
  }
  return "detailed area";
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
