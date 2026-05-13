import type { AskResponse } from "../api/types";
import { dispatchHighlightRelatedNodes } from "../graph/navigationEvents";

export function getRelatedNodeIds(response: AskResponse | null): string[] {
  return (
    response?.related_nodes
      .map((node) => node.id)
      .filter((nodeId): nodeId is string => typeof nodeId === "string") ?? []
  );
}

export function highlightRelatedNodes(repoId: string, response: AskResponse) {
  dispatchHighlightRelatedNodes({
    repoId,
    nodeIds: getRelatedNodeIds(response)
  });
}
