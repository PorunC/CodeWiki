export const OPEN_FILE_DETAIL_EVENT = "codewiki:open-file-detail";
export const HIDE_VISUAL_NODE_EVENT = "codewiki:hide-visual-node";
export const HIGHLIGHT_RELATED_NODES_EVENT = "codewiki:highlight-related-nodes";
export const OPEN_SOURCE_REF_EVENT = "codewiki:open-source-ref";

export type OpenFileDetailDetail = {
  fileId: string;
};

export type HideVisualNodeDetail = {
  nodeId: string;
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

export function dispatchHighlightRelatedNodes(detail: HighlightRelatedNodesDetail) {
  dispatchNavigationEvent(HIGHLIGHT_RELATED_NODES_EVENT, detail);
}

export function dispatchOpenSourceRef(detail: SourceRefNavigationDetail, options: { navigateToGraph?: boolean } = {}) {
  dispatchNavigationEvent(OPEN_SOURCE_REF_EVENT, detail);
  if (options.navigateToGraph) {
    navigateToGraph();
  }
}

export function onOpenFileDetail(handler: (detail: Partial<OpenFileDetailDetail> | undefined) => void) {
  return listenNavigationEvent<Partial<OpenFileDetailDetail>>(OPEN_FILE_DETAIL_EVENT, handler);
}

export function onHideVisualNode(handler: (detail: Partial<HideVisualNodeDetail> | undefined) => void) {
  return listenNavigationEvent<Partial<HideVisualNodeDetail>>(HIDE_VISUAL_NODE_EVENT, handler);
}

export function onHighlightRelatedNodes(
  handler: (detail: Partial<HighlightRelatedNodesDetail> | undefined) => void
) {
  return listenNavigationEvent<Partial<HighlightRelatedNodesDetail>>(HIGHLIGHT_RELATED_NODES_EVENT, handler);
}

export function onOpenSourceRef(handler: (detail: Partial<SourceRefNavigationDetail> | undefined) => void) {
  return listenNavigationEvent<Partial<SourceRefNavigationDetail>>(OPEN_SOURCE_REF_EVENT, handler);
}

export function navigateToGraph() {
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
