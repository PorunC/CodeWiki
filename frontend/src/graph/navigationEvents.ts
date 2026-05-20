export const OPEN_FILE_DETAIL_EVENT = "codewiki:open-file-detail";
export const HIDE_VISUAL_NODE_EVENT = "codewiki:hide-visual-node";
export const HIGHLIGHT_RELATED_NODES_EVENT = "codewiki:highlight-related-nodes";
export const OPEN_SOURCE_REF_EVENT = "codewiki:open-source-ref";
export const OPEN_CONTAINER_DRILLDOWN_EVENT = "codewiki:open-container-drilldown";

export type OpenFileDetailDetail = {
  fileId: string;
};

export type HideVisualNodeDetail = {
  nodeId: string;
};

export type OpenContainerDrilldownDetail = {
  id: string;
  title: string;
  pathLabel: string;
  containerType: "community" | "directory";
  communityId?: string;
  communityLevel?: number;
  parentCommunityId?: string | null;
  rawNodeIds: string[];
};

export type HighlightRelatedNodesDetail = {
  repoId?: string;
  nodeIds: string[];
};

export type SourceRefNavigationDetail = {
  repoId?: string;
  filePath: string;
  startLine: number;
  endLine: number;
};

export function dispatchOpenFileDetail(fileId: string) {
  dispatchNavigationEvent(OPEN_FILE_DETAIL_EVENT, { fileId });
}

export function dispatchHideVisualNode(nodeId: string) {
  dispatchNavigationEvent(HIDE_VISUAL_NODE_EVENT, { nodeId });
}

export function dispatchOpenContainerDrilldown(detail: OpenContainerDrilldownDetail) {
  dispatchNavigationEvent(OPEN_CONTAINER_DRILLDOWN_EVENT, detail);
}

export function dispatchHighlightRelatedNodes(detail: HighlightRelatedNodesDetail) {
  dispatchNavigationEvent(HIGHLIGHT_RELATED_NODES_EVENT, detail);
}

export function dispatchOpenSourceRef(detail: SourceRefNavigationDetail, options: { navigateToGraph?: boolean } = {}) {
  dispatchNavigationEvent(OPEN_SOURCE_REF_EVENT, detail);
  if (options.navigateToGraph) {
    navigateToGraph(detail.repoId);
  }
}

export function onOpenFileDetail(handler: (detail: Partial<OpenFileDetailDetail> | undefined) => void) {
  return listenNavigationEvent<Partial<OpenFileDetailDetail>>(OPEN_FILE_DETAIL_EVENT, handler);
}

export function onHideVisualNode(handler: (detail: Partial<HideVisualNodeDetail> | undefined) => void) {
  return listenNavigationEvent<Partial<HideVisualNodeDetail>>(HIDE_VISUAL_NODE_EVENT, handler);
}

export function onOpenContainerDrilldown(
  handler: (detail: Partial<OpenContainerDrilldownDetail> | undefined) => void
) {
  return listenNavigationEvent<Partial<OpenContainerDrilldownDetail>>(OPEN_CONTAINER_DRILLDOWN_EVENT, handler);
}

export function onHighlightRelatedNodes(
  handler: (detail: Partial<HighlightRelatedNodesDetail> | undefined) => void
) {
  return listenNavigationEvent<Partial<HighlightRelatedNodesDetail>>(HIGHLIGHT_RELATED_NODES_EVENT, handler);
}

export function onOpenSourceRef(handler: (detail: Partial<SourceRefNavigationDetail> | undefined) => void) {
  return listenNavigationEvent<Partial<SourceRefNavigationDetail>>(OPEN_SOURCE_REF_EVENT, handler);
}

export function navigateToGraph(repoId?: string) {
  if (repoId) {
    window.history.pushState(null, "", `/repos/${encodeURIComponent(repoId)}/graph`);
    window.dispatchEvent(new PopStateEvent("popstate"));
    return;
  }
  if (window.location.hash !== "#graph") {
    window.location.hash = "graph";
  }
}

function dispatchNavigationEvent<T>(name: string, detail: T) {
  window.dispatchEvent(new CustomEvent(name, { detail }));
}

function listenNavigationEvent<T>(name: string, handler: (detail: T | undefined) => void) {
  const listener = (event: Event) => {
    handler((event as CustomEvent<T>).detail);
  };
  window.addEventListener(name, listener);
  return () => window.removeEventListener(name, listener);
}
