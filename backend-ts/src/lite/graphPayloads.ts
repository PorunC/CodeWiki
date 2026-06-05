import type { LiteRepoContext } from "../lite.js";
import type { CodeGraphEdge } from "../types.js";
import {
  chunkPayload,
  edgePayload,
  findNode,
  nodePayload,
  type RelationshipDirection,
} from "./payloadCommon.js";

export function relationshipPayload(
  context: LiteRepoContext,
  symbol: string,
  direction: RelationshipDirection,
  limit: number,
): {
  repo_id: string;
  symbol: string;
  relationships: Array<{
    source: ReturnType<typeof nodePayload>;
    target: ReturnType<typeof nodePayload>;
    edge: ReturnType<typeof edgePayload>;
  }>;
} {
  const graph = context.store.getGraph(context.repo.id);
  const node = findNode(graph.nodes, symbol);
  if (!node) {
    return { repo_id: context.repo.id, symbol, relationships: [] };
  }
  const relationships = graph.edges
    .filter((edge) =>
      direction === "callers"
        ? edge.target_id === node.id
        : edge.source_id === node.id,
    )
    .slice(0, limit)
    .flatMap((edge) => {
      const source = graph.nodes.find(
        (candidate) => candidate.id === edge.source_id,
      );
      const target = graph.nodes.find(
        (candidate) => candidate.id === edge.target_id,
      );
      return source && target
        ? [
            {
              source: nodePayload(source),
              target: nodePayload(target),
              edge: edgePayload(edge),
            },
          ]
        : [];
    });
  return { repo_id: context.repo.id, symbol, relationships };
}

export function graphImpactPayload(
  context: LiteRepoContext,
  symbol: string,
  depth: number,
): {
  repo_id: string;
  symbol: string;
  depth: number;
  root_ids: string[];
  nodes: Array<ReturnType<typeof nodePayload>>;
  edges: Array<ReturnType<typeof edgePayload>>;
} {
  const graph = context.store.getGraph(context.repo.id);
  const roots = graph.nodes.filter(
    (node) => node.name === symbol || node.id === symbol,
  );
  const visited = new Set(roots.map((node) => node.id));
  const selectedEdges = new Map<string, CodeGraphEdge>();
  let frontier = new Set(visited);
  for (let level = 0; level < depth && frontier.size; level += 1) {
    const next = new Set<string>();
    for (const edge of graph.edges) {
      if (!frontier.has(edge.source_id) && !frontier.has(edge.target_id)) {
        continue;
      }
      selectedEdges.set(edge.id, edge);
      for (const nodeId of [edge.source_id, edge.target_id]) {
        if (!visited.has(nodeId)) {
          visited.add(nodeId);
          next.add(nodeId);
        }
      }
    }
    frontier = next;
  }
  return {
    repo_id: context.repo.id,
    symbol,
    depth,
    root_ids: roots.map((node) => node.id),
    nodes: graph.nodes.filter((node) => visited.has(node.id)).map(nodePayload),
    edges: [...selectedEdges.values()].map(edgePayload),
  };
}

export function contextPayload(
  context: LiteRepoContext,
  task: string,
  maxFiles: number,
  maxNodes: number,
): {
  repo_id: string;
  task: string;
  nodes: Array<ReturnType<typeof nodePayload>>;
  source_sections: Array<ReturnType<typeof chunkPayload>>;
  text: string;
  stats: { node_count: number; source_section_count: number };
} {
  const nodes = context.store
    .searchCodeNodes(context.repo.id, task, { limit: maxNodes })
    .map((hit) => nodePayload(hit.node));
  const sourceSections = context.store
    .searchCodeChunks(context.repo.id, task, maxFiles)
    .map((hit) => chunkPayload(hit.chunk, true));
  const text = [
    `Context for: ${task}`,
    `Nodes: ${nodes.length}`,
    ...nodes
      .slice(0, 12)
      .map(
        (node) =>
          `- ${node.name} (${node.type}) ${node.file_path}:${node.start_line ?? ""}`,
      ),
    `Source sections: ${sourceSections.length}`,
    ...sourceSections
      .slice(0, 4)
      .map(
        (chunk) =>
          `- ${chunk.file_path}:L${chunk.start_line}-L${chunk.end_line}`,
      ),
  ].join("\n");
  return {
    repo_id: context.repo.id,
    task,
    nodes,
    source_sections: sourceSections,
    text,
    stats: {
      node_count: nodes.length,
      source_section_count: sourceSections.length,
    },
  };
}

export function tracePayload(
  context: LiteRepoContext,
  fromSymbol: string,
  toSymbol: string,
  maxDepth: number,
): {
  repo_id: string;
  from_symbol: string;
  to_symbol: string;
  found: boolean;
  nodes: Array<ReturnType<typeof nodePayload>>;
  edges: Array<ReturnType<typeof edgePayload>>;
  text: string;
} {
  const graph = context.store.getGraph(context.repo.id);
  const start = findNode(graph.nodes, fromSymbol);
  const target = findNode(graph.nodes, toSymbol);
  if (!start || !target) {
    return {
      repo_id: context.repo.id,
      from_symbol: fromSymbol,
      to_symbol: toSymbol,
      found: false,
      nodes: [],
      edges: [],
      text: `Trace endpoints not found: ${!start ? fromSymbol : toSymbol}`,
    };
  }
  const queue: Array<{ nodeId: string; pathEdges: CodeGraphEdge[] }> = [
    { nodeId: start.id, pathEdges: [] },
  ];
  const visited = new Set([start.id]);
  while (queue.length) {
    const current = queue.shift()!;
    if (current.nodeId === target.id) {
      const nodeIds = new Set([
        start.id,
        target.id,
        ...current.pathEdges.flatMap((edge) => [
          edge.source_id,
          edge.target_id,
        ]),
      ]);
      const nodes = graph.nodes.filter((node) => nodeIds.has(node.id));
      return {
        repo_id: context.repo.id,
        from_symbol: fromSymbol,
        to_symbol: toSymbol,
        found: true,
        nodes: nodes.map(nodePayload),
        edges: current.pathEdges.map(edgePayload),
        text: `Trace found: ${nodes.map((node) => node.name).join(" -> ")}`,
      };
    }
    if (current.pathEdges.length >= maxDepth) {
      continue;
    }
    for (const edge of graph.edges.filter(
      (candidate) => candidate.source_id === current.nodeId,
    )) {
      if (visited.has(edge.target_id)) {
        continue;
      }
      visited.add(edge.target_id);
      queue.push({
        nodeId: edge.target_id,
        pathEdges: [...current.pathEdges, edge],
      });
    }
  }
  return {
    repo_id: context.repo.id,
    from_symbol: fromSymbol,
    to_symbol: toSymbol,
    found: false,
    nodes: [nodePayload(start), nodePayload(target)],
    edges: [],
    text: `No trace found from ${fromSymbol} to ${toSymbol}.`,
  };
}

export function nodeContextPayload(
  context: LiteRepoContext,
  symbol: string,
  includeCode: boolean,
): {
  repo_id: string;
  symbol: string;
  node: ReturnType<typeof nodePayload>;
  callers: ReturnType<typeof relationshipPayload>["relationships"];
  callees: ReturnType<typeof relationshipPayload>["relationships"];
  source_sections: Array<ReturnType<typeof chunkPayload>>;
  text: string;
} {
  const graph = context.store.getGraph(context.repo.id);
  const node = findNode(graph.nodes, symbol);
  if (!node) {
    throw new Error(`Graph node not found: ${symbol}`);
  }
  const callers = relationshipPayload(
    context,
    node.id,
    "callers",
    20,
  ).relationships;
  const callees = relationshipPayload(
    context,
    node.id,
    "callees",
    20,
  ).relationships;
  const sourceSections = context.store
    .listCodeChunks(context.repo.id)
    .filter((chunk) => chunk.file_path === node.file_path)
    .slice(0, 3)
    .map((chunk) => chunkPayload(chunk, includeCode));
  const text = [
    `${node.name} (${node.type}) ${node.file_path}:${node.start_line ?? ""}`,
    `Callers: ${callers.length}`,
    `Callees: ${callees.length}`,
    ...sourceSections.map(
      (chunk) => `${chunk.file_path}:L${chunk.start_line}-L${chunk.end_line}`,
    ),
  ].join("\n");
  return {
    repo_id: context.repo.id,
    symbol,
    node: nodePayload(node),
    callers,
    callees,
    source_sections: sourceSections,
    text,
  };
}
