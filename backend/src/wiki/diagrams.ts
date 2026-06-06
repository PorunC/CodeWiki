import type { JsonObject, RetrievalTrace } from "../types.js";

export type MermaidDiagramKind =
  | "component"
  | "data_flow"
  | "symbol_flow"
  | "sequence"
  | "data_model"
  | "surface";

export type MermaidDiagram = {
  slot: string;
  kind: MermaidDiagramKind;
  title: string;
  headingHint: string;
  reason: string;
  lines: string[];
  sourceEdgeIds: string[];
};

type MermaidGroup = {
  key: string;
  label: string;
  kind: string;
  rank: number;
};

type MermaidEdgeAggregate = {
  sourceKey: string;
  targetKey: string;
  counts: Record<string, number>;
  confidenceTotal: number;
  evidenceCount: number;
  edgeIds: string[];
};

type SymbolFlowDiagram = {
  lines: string[];
  edgeIds: string[];
};

const ABSTRACT_DIAGRAM_EDGE_TYPES = new Set([
  "routes_to",
  "calls",
  "imports",
  "uses_config",
  "inherits",
  "implements",
  "exports",
  "references",
]);
const SOURCE_EDGE_TYPES = new Set([
  ...ABSTRACT_DIAGRAM_EDGE_TYPES,
  "contains",
  "defines",
]);
const SURFACE_NODE_TYPES = new Set([
  "endpoint",
  "class",
  "schema",
  "interface",
]);
const EDGE_LABEL_ORDER = [
  "routes_to",
  "calls",
  "imports",
  "uses_config",
  "inherits",
  "implements",
  "exports",
  "references",
];
const SYMBOL_FLOW_EDGE_TYPES = new Set([
  "routes_to",
  "calls",
  "imports",
  "uses_config",
  "inherits",
  "implements",
  "references",
]);
const SYMBOL_FLOW_NODE_TYPES = new Set([
  "endpoint",
  "function",
  "method",
  "class",
  "schema",
  "interface",
  "config",
  "file",
  "module",
]);

const MAX_MERMAID_COMPONENTS = 12;
const MAX_MERMAID_ABSTRACT_EDGES = 18;
const MAX_MERMAID_SURFACES = 12;
const MAX_MERMAID_DIAGRAMS = 5;
const MAX_MERMAID_SEQUENCE_MESSAGES = 10;
const MAX_MERMAID_CLASS_NODES = 10;
const MAX_MERMAID_CLASS_FIELDS = 8;
const MAX_MERMAID_SYMBOL_FLOW_EDGES = 14;
const MAX_MERMAID_SYMBOL_FLOW_NODES = 14;

export function mermaidDiagramsFromTrace(
  trace: RetrievalTrace,
  title: string | null = null,
): MermaidDiagram[] {
  const nodes = nodesById(trace);
  if (!nodes.size) {
    return [];
  }

  const pageTitle = diagramPageTitle(title);
  const diagrams: MermaidDiagram[] = [];
  const { groups, edges } = componentGroupsAndEdges(trace, nodes);
  const componentDiagram = abstractComponentDiagram(groups, edges);
  if (componentDiagram) {
    diagrams.push({
      slot: "component-relationships",
      kind: "component",
      title: diagramTitle(pageTitle, "component relationships"),
      headingHint: "System Context",
      reason:
        "Shows the strongest verified dependencies between retrieved components.",
      lines: componentDiagram,
      sourceEdgeIds: edgeIds(edges),
    });
  }

  const dataFlowDiagram = dataFlowDiagramForGroups(groups, edges);
  if (dataFlowDiagram) {
    diagrams.push({
      slot: "data-flow",
      kind: "data_flow",
      title: diagramTitle(pageTitle, "data and call flow"),
      headingHint: "Control Flow",
      reason:
        "Highlights runtime-like calls, routes, and imports selected from graph evidence.",
      lines: dataFlowDiagram,
      sourceEdgeIds: edgeIds(edges),
    });
  }

  const symbolFlow = symbolFlowDiagram(trace, nodes);
  if (symbolFlow) {
    diagrams.push({
      slot: "implementation-flow",
      kind: "symbol_flow",
      title: diagramTitle(pageTitle, "implementation flow"),
      headingHint: "Control Flow",
      reason:
        "Shows concrete endpoints, functions, methods, classes, imports, and configuration links selected from graph evidence.",
      lines: symbolFlow.lines,
      sourceEdgeIds: symbolFlow.edgeIds,
    });
  }

  const sequenceDiagram = interactionSequenceDiagram(groups, edges);
  if (sequenceDiagram) {
    diagrams.push({
      slot: "interaction-sequence",
      kind: "sequence",
      title: diagramTitle(pageTitle, "interaction sequence"),
      headingHint: "Control Flow",
      reason: "Orders the most relevant interactions as a compact sequence.",
      lines: sequenceDiagram,
      sourceEdgeIds: edgeIds(edges),
    });
  }

  const dataDiagram = dataModelDiagram(trace);
  if (dataDiagram) {
    diagrams.push({
      slot: "data-model",
      kind: "data_model",
      title: diagramTitle(pageTitle, "data model"),
      headingHint: "Data Model",
      reason:
        "Uses retrieved classes, schemas, and interfaces rather than inferred models.",
      lines: dataDiagram,
      sourceEdgeIds: edgeIdsForTypes(trace, new Set(["inherits"])),
    });
  }

  const surfaceDiagram = keySurfaceDiagram(trace, nodes);
  if (surfaceDiagram) {
    diagrams.push({
      slot: "api-surfaces",
      kind: "surface",
      title: diagramTitle(pageTitle, "public surfaces"),
      headingHint: "API Surface",
      reason:
        "Maps endpoints, classes, schemas, and interfaces to their owning components.",
      lines: surfaceDiagram,
      sourceEdgeIds: edgeIdsForTypes(trace, SOURCE_EDGE_TYPES),
    });
  }

  return diagrams.slice(0, MAX_MERMAID_DIAGRAMS);
}

export function diagramSlotsPayload(diagrams: MermaidDiagram[]): JsonObject[] {
  return diagrams.map((diagram) => ({
    slot: diagram.slot,
    placeholder: `[[DIAGRAM:${diagram.slot}]]`,
    kind: diagram.kind,
    title: diagram.title,
    heading_hint: diagram.headingHint,
    reason: diagram.reason,
    source_edge_ids: diagram.sourceEdgeIds,
  }));
}

export function graphRefsFromTrace(trace: RetrievalTrace): string[] {
  const refs = new Set<string>();
  for (const node of [...trace.seed_nodes, ...trace.expanded_nodes]) {
    const id = stringValue(node.id);
    if (id) {
      refs.add(id);
    }
  }
  for (const edge of trace.related_edges) {
    for (const key of ["id", "source_id", "target_id", "source", "target"]) {
      const value = stringValue(edge[key]);
      if (value) {
        refs.add(value);
      }
    }
  }
  return [...refs].sort();
}

function nodesById(trace: RetrievalTrace): Map<string, JsonObject> {
  const nodes = new Map<string, JsonObject>();
  for (const node of [...trace.seed_nodes, ...trace.expanded_nodes]) {
    const id = stringValue(node.id);
    if (id) {
      nodes.set(id, node);
    }
  }
  return nodes;
}

function componentGroupsAndEdges(
  trace: RetrievalTrace,
  nodes: Map<string, JsonObject>,
): { groups: Map<string, MermaidGroup>; edges: MermaidEdgeAggregate[] } {
  const community = aggregateComponentEdges(trace, nodes, "community");
  if (community.edges.length && community.groups.size > 1) {
    return community;
  }

  const file = aggregateComponentEdges(trace, nodes, "file");
  if (file.edges.length && file.groups.size > 1) {
    return file;
  }
  return { groups: new Map(), edges: [] };
}

function aggregateComponentEdges(
  trace: RetrievalTrace,
  nodes: Map<string, JsonObject>,
  groupMode: "community" | "file",
): { groups: Map<string, MermaidGroup>; edges: MermaidEdgeAggregate[] } {
  const communityGroups = communityIndex(trace.community_summaries);
  const groups = new Map<string, MermaidGroup>();
  const aggregates = new Map<string, MermaidEdgeAggregate>();

  for (const edge of trace.related_edges) {
    const edgeType = stringValue(edge.type) ?? "";
    if (!ABSTRACT_DIAGRAM_EDGE_TYPES.has(edgeType)) {
      continue;
    }
    const sourceId = edgeEndpoint(edge, "source_id", "source");
    const targetId = edgeEndpoint(edge, "target_id", "target");
    const sourceNode = nodes.get(sourceId);
    const targetNode = nodes.get(targetId);
    if (!sourceNode || !targetNode) {
      continue;
    }

    const sourceGroup = abstractGroupForNode(
      sourceNode,
      communityGroups,
      groupMode,
    );
    const targetGroup = abstractGroupForNode(
      targetNode,
      communityGroups,
      groupMode,
    );
    if (sourceGroup.key === targetGroup.key) {
      continue;
    }

    groups.set(sourceGroup.key, sourceGroup);
    groups.set(targetGroup.key, targetGroup);
    const aggregateKey = `${sourceGroup.key}\0${targetGroup.key}`;
    const aggregate = aggregates.get(aggregateKey) ?? {
      sourceKey: sourceGroup.key,
      targetKey: targetGroup.key,
      counts: {},
      confidenceTotal: 0,
      evidenceCount: 0,
      edgeIds: [],
    };
    aggregate.counts[edgeType] = (aggregate.counts[edgeType] ?? 0) + 1;
    aggregate.confidenceTotal += edgeConfidence(edge);
    aggregate.evidenceCount += 1;
    const edgeId = stringValue(edge.id);
    if (edgeId) {
      aggregate.edgeIds.push(edgeId);
    }
    aggregates.set(aggregateKey, aggregate);
  }

  const selected = selectComponentEdges([...aggregates.values()]);
  const selectedGroupKeys = new Set(
    selected.flatMap((edge) => [edge.sourceKey, edge.targetKey]),
  );
  return {
    groups: new Map(
      [...groups.entries()].filter(([key]) => selectedGroupKeys.has(key)),
    ),
    edges: selected,
  };
}

function communityIndex(communities: JsonObject[]): Map<string, MermaidGroup> {
  const index = new Map<string, MermaidGroup>();
  const visible = communitiesForLevel(communities);
  visible.forEach((community, rank) => {
    const communityId = stringValue(community.id);
    if (!communityId) {
      return;
    }
    const group: MermaidGroup = {
      key: `community:${communityId}`,
      label:
        stringValue(community.name) ??
        communityId.split(":").at(-1) ??
        communityId,
      kind: "community",
      rank,
    };
    for (const nodeId of [
      ...stringList(community.matched_node_ids),
      ...stringList(community.node_ids),
    ]) {
      index.set(nodeId, group);
    }
  });
  return index;
}

function communitiesForLevel(communities: JsonObject[]): JsonObject[] {
  const levels = communities.map((community) => intValue(community.level));
  const selectedLevel = levels.length ? Math.max(...levels) : 0;
  const selected = communities.filter(
    (community) => intValue(community.level) === selectedLevel,
  );
  return selected.length ? selected : communities;
}

function abstractGroupForNode(
  node: JsonObject,
  communityGroups: Map<string, MermaidGroup>,
  groupMode: "community" | "file",
): MermaidGroup {
  const nodeId = stringValue(node.id) ?? "";
  const communityGroup = communityGroups.get(nodeId);
  if (groupMode === "community" && communityGroup) {
    return communityGroup;
  }

  const metadata = recordValue(node.metadata);
  const name = stringValue(node.name) ?? nodeId;
  if (stringValue(node.type) === "module" && metadata.external === true) {
    return {
      key: `external:${name}`,
      label: `External: ${name}`,
      kind: "external",
      rank: 90,
    };
  }

  const filePath = stringValue(node.file_path);
  if (filePath) {
    return {
      key: `file:${filePath}`,
      label: componentLabel(filePath),
      kind: "file",
      rank: 20,
    };
  }

  return {
    key: `node:${nodeId}`,
    label: mermaidLabel(node),
    kind: "node",
    rank: 80,
  };
}

function abstractComponentDiagram(
  groups: Map<string, MermaidGroup>,
  edges: MermaidEdgeAggregate[],
): string[] | null {
  if (!edges.length || groups.size <= 1) {
    return null;
  }
  return renderComponentDiagram(groups, edges);
}

function renderComponentDiagram(
  groups: Map<string, MermaidGroup>,
  edges: MermaidEdgeAggregate[],
): string[] {
  const keys = [...groups.keys()].sort((left, right) => {
    const leftGroup = groups.get(left);
    const rightGroup = groups.get(right);
    if (!leftGroup || !rightGroup) {
      return left.localeCompare(right);
    }
    return (
      leftGroup.rank - rightGroup.rank ||
      leftGroup.label.localeCompare(rightGroup.label) ||
      left.localeCompare(right)
    );
  });
  const aliases = new Map(keys.map((key, index) => [key, `C${index}`]));
  const lines = ["graph TD"];
  for (const key of keys) {
    const group = groups.get(key);
    const alias = aliases.get(key);
    if (group && alias) {
      lines.push(`  ${alias}["${mermaidText(group.label)}"]`);
    }
  }
  for (const edge of edges) {
    const sourceAlias = aliases.get(edge.sourceKey);
    const targetAlias = aliases.get(edge.targetKey);
    if (sourceAlias && targetAlias) {
      lines.push(
        `  ${sourceAlias} -->|${edgeLabel(edge.counts)}| ${targetAlias}`,
      );
    }
  }
  return lines;
}

function dataFlowDiagramForGroups(
  groups: Map<string, MermaidGroup>,
  edges: MermaidEdgeAggregate[],
): string[] | null {
  const flowEdges = [...edges]
    .sort(compareComponentEdges)
    .filter(
      (edge) =>
        edge.counts.routes_to || edge.counts.calls || edge.counts.imports,
    )
    .slice(0, MAX_MERMAID_SEQUENCE_MESSAGES);
  if (groups.size <= 1 || flowEdges.length < 2) {
    return null;
  }
  const involved = new Set(
    flowEdges.flatMap((edge) => [edge.sourceKey, edge.targetKey]),
  );
  const keys = [...involved]
    .filter((key) => groups.has(key))
    .sort((left, right) =>
      compareGroups(groups.get(left), groups.get(right), left, right),
    );
  const aliases = new Map(keys.map((key, index) => [key, `D${index}`]));
  const lines = ["flowchart LR"];
  for (const key of keys) {
    const group = groups.get(key);
    const alias = aliases.get(key);
    if (group && alias) {
      lines.push(`  ${alias}["${mermaidText(group.label)}"]`);
    }
  }
  for (const edge of flowEdges) {
    const sourceAlias = aliases.get(edge.sourceKey);
    const targetAlias = aliases.get(edge.targetKey);
    const label = sequenceEdgeLabel(edge.counts);
    if (sourceAlias && targetAlias && label) {
      lines.push(`  ${sourceAlias} -->|${label}| ${targetAlias}`);
    }
  }
  return lines.length > 1 ? lines : null;
}

function interactionSequenceDiagram(
  groups: Map<string, MermaidGroup>,
  edges: MermaidEdgeAggregate[],
): string[] | null {
  const sequenceEdges = [...edges]
    .sort(compareComponentEdges)
    .filter((edge) => sequenceEdgeLabel(edge.counts))
    .slice(0, MAX_MERMAID_SEQUENCE_MESSAGES);
  if (groups.size <= 1 || !sequenceEdges.length) {
    return null;
  }

  const involvedKeys: string[] = [];
  for (const edge of sequenceEdges) {
    for (const key of [edge.sourceKey, edge.targetKey]) {
      if (groups.has(key) && !involvedKeys.includes(key)) {
        involvedKeys.push(key);
      }
    }
  }
  const aliases = new Map(involvedKeys.map((key, index) => [key, `P${index}`]));
  const lines = ["sequenceDiagram"];
  for (const key of involvedKeys) {
    const group = groups.get(key);
    const alias = aliases.get(key);
    if (group && alias) {
      lines.push(
        `  participant ${alias} as ${mermaidSequenceText(group.label)}`,
      );
    }
  }
  for (const edge of sequenceEdges) {
    const sourceAlias = aliases.get(edge.sourceKey);
    const targetAlias = aliases.get(edge.targetKey);
    const label = sequenceEdgeLabel(edge.counts);
    if (sourceAlias && targetAlias && label) {
      const arrow = sequenceEdgeIsRuntime(edge.counts) ? "->>" : "-->>";
      lines.push(`  ${sourceAlias}${arrow}${targetAlias}: ${label}`);
    }
  }
  return lines.length > 1 ? lines : null;
}

function symbolFlowDiagram(
  trace: RetrievalTrace,
  nodes: Map<string, JsonObject>,
): SymbolFlowDiagram | null {
  const candidates = trace.related_edges.filter((edge) =>
    isSymbolFlowEdge(edge, nodes),
  );
  if (!candidates.length) {
    return null;
  }

  const selectedEdges: JsonObject[] = [];
  const selectedNodeIds: string[] = [];
  const selectedNodeSet = new Set<string>();
  for (const edge of [...candidates].sort(compareSymbolFlowEdges)) {
    const proposed = [
      edgeEndpoint(edge, "source_id", "source"),
      edgeEndpoint(edge, "target_id", "target"),
    ].filter((nodeId) => nodeId && !selectedNodeSet.has(nodeId));
    if (
      selectedEdges.length &&
      selectedNodeSet.size + proposed.length > MAX_MERMAID_SYMBOL_FLOW_NODES
    ) {
      continue;
    }
    for (const nodeId of proposed) {
      selectedNodeSet.add(nodeId);
      selectedNodeIds.push(nodeId);
    }
    selectedEdges.push(edge);
    if (selectedEdges.length >= MAX_MERMAID_SYMBOL_FLOW_EDGES) {
      break;
    }
  }

  if (!selectedEdges.length || selectedNodeIds.length < 2) {
    return null;
  }

  const aliases = new Map(
    selectedNodeIds.map((nodeId, index) => [nodeId, `I${index}`]),
  );
  const lines = ["flowchart TD"];
  for (const nodeId of selectedNodeIds) {
    const node = nodes.get(nodeId);
    const alias = aliases.get(nodeId);
    if (node && alias) {
      lines.push(`  ${alias}["${symbolFlowLabel(node)}"]`);
    }
  }

  const edgeIds: string[] = [];
  for (const edge of selectedEdges) {
    const sourceAlias = aliases.get(edgeEndpoint(edge, "source_id", "source"));
    const targetAlias = aliases.get(edgeEndpoint(edge, "target_id", "target"));
    if (!sourceAlias || !targetAlias) {
      continue;
    }
    lines.push(
      `  ${sourceAlias} -->|${mermaidEdgeText(symbolFlowEdgeLabel(edge))}| ${targetAlias}`,
    );
    const edgeId = stringValue(edge.id);
    if (edgeId) {
      edgeIds.push(edgeId);
    }
  }
  return lines.length > 1 ? { lines, edgeIds } : null;
}

function dataModelDiagram(trace: RetrievalTrace): string[] | null {
  const selected = selectDataNodes([
    ...trace.seed_nodes,
    ...trace.expanded_nodes,
  ]);
  if (!selected.length) {
    return null;
  }
  const aliases = classAliases(selected);
  const lines = ["classDiagram"];
  for (const node of selected) {
    const nodeId = stringValue(node.id) ?? "";
    const alias = aliases.get(nodeId);
    if (!alias) {
      continue;
    }
    lines.push(`  class ${alias}`);
    const label = classDisplayLabel(node);
    if (label !== alias) {
      lines.push(`  ${alias} : ${mermaidClassText(label)}`);
    }
    for (const field of dataNodeFields(node).slice(
      0,
      MAX_MERMAID_CLASS_FIELDS,
    )) {
      lines.push(`  ${alias} : +${mermaidClassText(field)}`);
    }
  }

  const selectedIds = new Set(
    selected.map((node) => stringValue(node.id) ?? ""),
  );
  for (const edge of trace.related_edges) {
    if (edge.type !== "inherits") {
      continue;
    }
    const sourceId = edgeEndpoint(edge, "source_id", "source");
    const targetId = edgeEndpoint(edge, "target_id", "target");
    if (selectedIds.has(sourceId) && selectedIds.has(targetId)) {
      const sourceAlias = aliases.get(sourceId);
      const targetAlias = aliases.get(targetId);
      if (sourceAlias && targetAlias) {
        lines.push(`  ${targetAlias} <|-- ${sourceAlias}`);
      }
    }
  }
  return lines.length > 1 ? lines : null;
}

function keySurfaceDiagram(
  trace: RetrievalTrace,
  nodes: Map<string, JsonObject>,
): string[] | null {
  const communityGroups = communityIndex(trace.community_summaries);
  const surfaces = selectSurfaceNodes([
    ...trace.seed_nodes,
    ...trace.expanded_nodes,
  ]);
  if (!surfaces.length) {
    return null;
  }

  const groups = new Map<string, MermaidGroup>();
  const surfaceAliases = new Map<string, string>();
  for (const surface of surfaces) {
    const nodeId = stringValue(surface.id);
    if (!nodeId || !nodes.has(nodeId)) {
      continue;
    }
    let group = abstractGroupForNode(surface, communityGroups, "community");
    if (group.kind !== "community") {
      group = abstractGroupForNode(surface, communityGroups, "file");
    }
    groups.set(group.key, group);
    surfaceAliases.set(nodeId, `S${surfaceAliases.size}`);
  }

  const groupKeys = [...groups.keys()].sort((left, right) =>
    compareGroups(groups.get(left), groups.get(right), left, right),
  );
  const groupAliases = new Map(
    groupKeys.map((key, index) => [key, `G${index}`]),
  );
  const lines = ["flowchart TD"];
  for (const key of groupKeys) {
    const group = groups.get(key);
    const alias = groupAliases.get(key);
    if (group && alias) {
      lines.push(`  ${alias}["${mermaidText(group.label)}"]`);
    }
  }

  for (const surface of surfaces) {
    const nodeId = stringValue(surface.id) ?? "";
    const surfaceAlias = surfaceAliases.get(nodeId);
    if (!surfaceAlias) {
      continue;
    }
    let group = abstractGroupForNode(surface, communityGroups, "community");
    if (group.kind !== "community") {
      group = abstractGroupForNode(surface, communityGroups, "file");
    }
    const groupAlias = groupAliases.get(group.key);
    if (!groupAlias) {
      continue;
    }
    lines.push(`  ${surfaceAlias}["${surfaceLabel(surface)}"]`);
    lines.push(`  ${groupAlias} --> ${surfaceAlias}`);
  }

  return lines.length > 1 ? lines : null;
}

function selectComponentEdges(
  edges: MermaidEdgeAggregate[],
): MermaidEdgeAggregate[] {
  const selected: MermaidEdgeAggregate[] = [];
  const selectedGroups = new Set<string>();
  for (const edge of [...edges].sort(compareComponentEdges)) {
    const proposed = new Set(selectedGroups);
    proposed.add(edge.sourceKey);
    proposed.add(edge.targetKey);
    if (selected.length && proposed.size > MAX_MERMAID_COMPONENTS) {
      continue;
    }
    selected.push(edge);
    selectedGroups.clear();
    for (const key of proposed) {
      selectedGroups.add(key);
    }
    if (selected.length >= MAX_MERMAID_ABSTRACT_EDGES) {
      break;
    }
  }
  return selected;
}

function compareComponentEdges(
  left: MermaidEdgeAggregate,
  right: MermaidEdgeAggregate,
): number {
  const scoreDiff = componentEdgeScore(right) - componentEdgeScore(left);
  return (
    scoreDiff ||
    left.sourceKey.localeCompare(right.sourceKey) ||
    left.targetKey.localeCompare(right.targetKey)
  );
}

function componentEdgeScore(edge: MermaidEdgeAggregate): number {
  const typeWeight: Record<string, number> = {
    routes_to: 6,
    calls: 4.5,
    imports: 3.5,
    uses_config: 3,
    inherits: 2.8,
    implements: 2.6,
    exports: 1.8,
    references: 1.4,
  };
  let score = 0;
  for (const [edgeType, count] of Object.entries(edge.counts)) {
    score += (typeWeight[edgeType] ?? 1) * Math.min(count, 4);
  }
  if (edge.evidenceCount) {
    score += edge.confidenceTotal / edge.evidenceCount;
  }
  return score;
}

function isSymbolFlowEdge(
  edge: JsonObject,
  nodes: Map<string, JsonObject>,
): boolean {
  const edgeType = stringValue(edge.type) ?? "";
  if (!SYMBOL_FLOW_EDGE_TYPES.has(edgeType)) {
    return false;
  }
  const sourceNode = nodes.get(edgeEndpoint(edge, "source_id", "source"));
  const targetNode = nodes.get(edgeEndpoint(edge, "target_id", "target"));
  return Boolean(
    sourceNode &&
    targetNode &&
    SYMBOL_FLOW_NODE_TYPES.has(stringValue(sourceNode.type) ?? "") &&
    SYMBOL_FLOW_NODE_TYPES.has(stringValue(targetNode.type) ?? ""),
  );
}

function compareSymbolFlowEdges(left: JsonObject, right: JsonObject): number {
  const scoreDiff = symbolFlowEdgeScore(right) - symbolFlowEdgeScore(left);
  return (
    scoreDiff ||
    edgeEndpoint(left, "source_id", "source").localeCompare(
      edgeEndpoint(right, "source_id", "source"),
    ) ||
    edgeEndpoint(left, "target_id", "target").localeCompare(
      edgeEndpoint(right, "target_id", "target"),
    )
  );
}

function symbolFlowEdgeScore(edge: JsonObject): number {
  const typeWeight: Record<string, number> = {
    routes_to: 7,
    calls: 6,
    uses_config: 4,
    imports: 3.5,
    inherits: 3.2,
    implements: 3,
    references: 2,
  };
  return (typeWeight[stringValue(edge.type) ?? ""] ?? 1) + edgeConfidence(edge);
}

function selectSurfaceNodes(nodes: JsonObject[]): JsonObject[] {
  return nodes
    .filter((node) => SURFACE_NODE_TYPES.has(stringValue(node.type) ?? ""))
    .sort(compareSurfaceNodes)
    .slice(0, MAX_MERMAID_SURFACES);
}

function selectDataNodes(nodes: JsonObject[]): JsonObject[] {
  return nodes
    .filter((node) =>
      ["class", "schema", "interface"].includes(stringValue(node.type) ?? ""),
    )
    .sort(compareSurfaceNodes)
    .slice(0, MAX_MERMAID_CLASS_NODES);
}

function compareSurfaceNodes(left: JsonObject, right: JsonObject): number {
  return (
    surfaceRank(stringValue(left.type) ?? "") -
      surfaceRank(stringValue(right.type) ?? "") ||
    intValue(left.hop) - intValue(right.hop) ||
    numberValue(right.score) - numberValue(left.score) ||
    (stringValue(left.file_path) ?? "").localeCompare(
      stringValue(right.file_path) ?? "",
    ) ||
    (stringValue(left.name) ?? "").localeCompare(stringValue(right.name) ?? "")
  );
}

function surfaceRank(nodeType: string): number {
  return { endpoint: 0, schema: 1, class: 2, interface: 3 }[nodeType] ?? 9;
}

function classAliases(nodes: JsonObject[]): Map<string, string> {
  const aliases = new Map<string, string>();
  const used = new Set<string>();
  nodes.forEach((node, index) => {
    const nodeId = stringValue(node.id);
    if (!nodeId) {
      return;
    }
    const base = classIdentifier(stringValue(node.name) ?? `Data${index}`);
    let alias = base;
    let suffix = 2;
    while (used.has(alias)) {
      alias = `${base}${suffix}`;
      suffix += 1;
    }
    used.add(alias);
    aliases.set(nodeId, alias);
  });
  return aliases;
}

function classIdentifier(value: string): string {
  let cleaned = value.replace(/[^A-Za-z0-9_]/g, "_").replace(/^_+|_+$/g, "");
  if (!cleaned) {
    return "DataModel";
  }
  if (/^\d/.test(cleaned)) {
    cleaned = `Data${cleaned}`;
  }
  return cleaned.slice(0, 48);
}

function dataNodeFields(node: JsonObject): string[] {
  const metadata = recordValue(node.metadata);
  const fields = metadata.fields;
  if (Array.isArray(fields)) {
    return fields
      .map((field) => (field === null ? "" : String(field)))
      .filter(Boolean);
  }
  const signature = stringValue(metadata.signature);
  if (signature) {
    return [signature];
  }
  const bases = metadata.bases;
  if (Array.isArray(bases)) {
    return bases
      .map((base) => (base === null ? "" : String(base)))
      .filter(Boolean)
      .map((base) => `extends ${base}`);
  }
  return [];
}

function classDisplayLabel(node: JsonObject): string {
  const name = stringValue(node.name) ?? "";
  const nodeType = stringValue(node.type) ?? "";
  return nodeType && nodeType !== "class" ? `${name} (${nodeType})` : name;
}

function surfaceLabel(node: JsonObject): string {
  const nodeType = stringValue(node.type) ?? "";
  const metadata = recordValue(node.metadata);
  if (nodeType === "endpoint") {
    const method = (stringValue(metadata.route_method) ?? "").toUpperCase();
    const routePath = stringValue(metadata.route_path) ?? "";
    const route = [method, routePath].filter(Boolean).join(" ");
    if (route) {
      return mermaidText(route);
    }
  }
  return mermaidLabel(node);
}

function symbolFlowLabel(node: JsonObject): string {
  const nodeType = stringValue(node.type) ?? "";
  const metadata = recordValue(node.metadata);
  if (nodeType === "endpoint") {
    const method = (stringValue(metadata.route_method) ?? "").toUpperCase();
    const routePath = stringValue(metadata.route_path) ?? "";
    const label =
      [method, routePath].filter(Boolean).join(" ") ||
      stringValue(node.name) ||
      "endpoint";
    return mermaidText(`${label}<br/>endpoint`);
  }

  const name = stringValue(node.name) ?? stringValue(node.id) ?? nodeType;
  const filePath = stringValue(node.file_path);
  if (nodeType === "module" && metadata.external === true) {
    return mermaidText(`External<br/>${name}`);
  }
  if (filePath) {
    return mermaidText(`${name} (${nodeType})<br/>${filePath}`);
  }
  return mermaidText(`${name} (${nodeType})`);
}

function symbolFlowEdgeLabel(edge: JsonObject): string {
  const edgeType = stringValue(edge.type) ?? "";
  const metadata = recordValue(edge.metadata);
  if (edgeType === "routes_to") {
    const method = (stringValue(metadata.route_method) ?? "").toUpperCase();
    const routePath = stringValue(metadata.route_path) ?? "";
    const route = [method, routePath].filter(Boolean).join(" ");
    return route ? `routes to ${route}` : "routes to";
  }
  const call = scalarLabel(metadata.call);
  if (edgeType === "calls" && call) {
    return `calls ${call}`;
  }
  const imported = scalarLabel(metadata.import);
  if (edgeType === "imports" && imported) {
    return `imports ${imported}`;
  }
  if (edgeType === "uses_config") {
    return "uses config";
  }
  const base = scalarLabel(metadata.base);
  if (edgeType === "inherits" && base) {
    return `inherits ${base}`;
  }
  const implemented = scalarLabel(metadata.interface);
  if (edgeType === "implements" && implemented) {
    return `implements ${implemented}`;
  }
  const reference = scalarLabel(metadata.reference);
  if (edgeType === "references" && reference) {
    return `references ${reference}`;
  }
  return edgeType.replace(/_/g, " ");
}

function edgeIds(edges: MermaidEdgeAggregate[]): string[] {
  const ids: string[] = [];
  const seen = new Set<string>();
  for (const edge of edges) {
    for (const edgeId of edge.edgeIds) {
      if (!seen.has(edgeId)) {
        seen.add(edgeId);
        ids.push(edgeId);
      }
    }
  }
  return ids;
}

function edgeIdsForTypes(
  trace: RetrievalTrace,
  edgeTypes: Set<string>,
): string[] {
  return trace.related_edges.flatMap((edge) => {
    const edgeId = stringValue(edge.id);
    const edgeType = stringValue(edge.type);
    return edgeId && edgeType && edgeTypes.has(edgeType) ? [edgeId] : [];
  });
}

function componentLabel(filePath: string): string {
  const parts = filePath.split("/").filter(Boolean);
  if (parts.length >= 2) {
    const parent = parts.at(-2);
    const leaf = parts.at(-1);
    return parent && leaf ? `${parent}/${leaf}` : filePath;
  }
  return filePath;
}

function edgeEndpoint(
  edge: JsonObject,
  primary: string,
  fallback: string,
): string {
  return stringValue(edge[primary]) ?? stringValue(edge[fallback]) ?? "";
}

function edgeConfidence(edge: JsonObject): number {
  return numberValue(edge.confidence, 1);
}

function edgeLabel(counts: Record<string, number>): string {
  const labels = EDGE_LABEL_ORDER.flatMap((edgeType) => {
    const count = counts[edgeType] ?? 0;
    if (!count) {
      return [];
    }
    const label = edgeType.replace(/_/g, " ");
    return [count > 1 ? `${label} x${count}` : label];
  });
  return mermaidEdgeText(labels.join(" / "));
}

function sequenceEdgeLabel(counts: Record<string, number>): string {
  const labels = ["routes_to", "calls", "imports"].flatMap((edgeType) => {
    const count = counts[edgeType] ?? 0;
    if (!count) {
      return [];
    }
    const label = edgeType.replace(/_/g, " ");
    return [count > 1 ? `${label} x${count}` : label];
  });
  return mermaidEdgeText(labels.join(" / "));
}

function sequenceEdgeIsRuntime(counts: Record<string, number>): boolean {
  return Boolean(counts.routes_to || counts.calls);
}

function mermaidLabel(node: JsonObject): string {
  const name = stringValue(node.name) ?? stringValue(node.id) ?? "";
  const nodeType = stringValue(node.type) ?? "";
  return mermaidText(`${name} (${nodeType})`);
}

function mermaidText(value: string): string {
  return value
    .replace(/\\/g, "\\\\")
    .replace(/"/g, "'")
    .replace(/\n/g, " ")
    .slice(0, 80);
}

function mermaidEdgeText(value: string): string {
  return mermaidText(value).replace(/\|/g, "/");
}

function mermaidSequenceText(value: string): string {
  return mermaidEdgeText(value).replace(/:/g, " -");
}

function mermaidClassText(value: string): string {
  return mermaidEdgeText(value)
    .replace(/\{/g, "(")
    .replace(/}/g, ")")
    .replace(/:/g, " -");
}

function diagramPageTitle(title: string | null): string {
  const normalized = title?.trim();
  return normalized || "Repository";
}

function diagramTitle(pageTitle: string, suffix: string): string {
  return pageTitle ? `${pageTitle} ${suffix}` : capitalize(suffix);
}

function capitalize(value: string): string {
  return value ? `${value.slice(0, 1).toUpperCase()}${value.slice(1)}` : value;
}

function compareGroups(
  left: MermaidGroup | undefined,
  right: MermaidGroup | undefined,
  leftKey: string,
  rightKey: string,
): number {
  if (!left || !right) {
    return leftKey.localeCompare(rightKey);
  }
  return (
    left.rank - right.rank ||
    left.label.localeCompare(right.label) ||
    leftKey.localeCompare(rightKey)
  );
}

function intValue(value: unknown, fallback = 0): number {
  if (typeof value === "number" && Number.isFinite(value)) {
    return Math.trunc(value);
  }
  if (typeof value === "string") {
    const parsed = Number.parseInt(value, 10);
    return Number.isFinite(parsed) ? parsed : fallback;
  }
  return fallback;
}

function numberValue(value: unknown, fallback = 0): number {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string") {
    const parsed = Number.parseFloat(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  }
  return fallback;
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function scalarLabel(value: unknown): string | null {
  if (typeof value === "string") {
    return value.trim() || null;
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    return String(value);
  }
  if (typeof value === "boolean") {
    return String(value);
  }
  return null;
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter(
    (item): item is string => typeof item === "string" && item.length > 0,
  );
}

function recordValue(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return {};
  }
  return Object.fromEntries(Object.entries(value));
}
