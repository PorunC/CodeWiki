import type { JsonObject, JsonValue, RetrievalTrace } from "../types.js";

export function graphFactsPayload(trace: RetrievalTrace): JsonObject {
  return {
    seed_nodes: trace.seed_nodes.map(promptNode),
    expanded_nodes: trace.expanded_nodes.map(promptNode),
    related_edges: trace.related_edges.map(promptEdge),
    community_edges: trace.community_edges.map(promptEdge),
    community_summaries: trace.community_summaries.map(promptCommunitySummary),
    community_hierarchy: communityHierarchy(trace.community_summaries),
  };
}

export function promptContract(): JsonObject {
  return {
    source_linking: {
      source_refs:
        "Use only file_path/start_line/end_line values from allowed_source_refs.",
      source_urls:
        "The server will convert validated source refs into clickable source URLs when repository git metadata is available.",
      inline_citations:
        "Use [[S1]] style markers from allowed_source_refs after source-grounded sentences. The server validates and converts markers to source links.",
    },
    citation_style: {
      inline_markers:
        "Use compact [[S#]] markers near concrete claims. The server renders them as short citations and groups full source ranges separately.",
      avoid_noise:
        "Do not repeat long source file labels in prose. Avoid section-level Sources lines; the server renders grouped source ranges once at the end.",
    },
    documentation_style: {
      name: "DeepWiki",
      workflow: [
        "GATHER with mandatory ReadFile evidence, source_chunks, and graph_facts",
        "think through subsystem boundaries, lifecycle, contracts, state changes, extension points, and failure paths",
        "write detailed Markdown with compact tables, concrete execution paths, and inline citations",
      ],
      required_sections: [
        "Purpose and Scope",
        "Architecture or System Context when relationships are evidenced",
        "Control Flow or Lifecycle when runtime behavior is evidenced",
        "Data Model, API Surface, Configuration, or Failure Handling when evidenced",
        "Extension Points or Operational Notes when change boundaries are evidenced",
      ],
      server_injected_sections: [
        "Relevant source files",
        "validated Mermaid diagrams at requested diagram placeholders or near matching headings",
        "grouped Sources",
      ],
    },
    detail_expectations: {
      minimum_depth:
        "For non-trivial pages, go beyond a summary. Cover responsibility, lifecycle/control flow, dependencies, inputs and outputs, data surfaces, APIs or UI routes, configuration, validation, extension points, failure handling, operational implications, state transitions, and internal tradeoffs when those details are present.",
      section_depth:
        "When evidence is sufficient, implementation pages should have 5-8 substantive sections and at least four evidence-backed detail blocks. Parent pages should synthesize child boundaries, shared contracts, and cross-child data/control flow rather than listing children.",
      preferred_tables: [
        "component/file/responsibility/evidence",
        "symbol/function/caller/callee/evidence",
        "route or API/symbol/purpose/evidence",
        "data structure/owner/fields or role/evidence",
        "configuration key/default or source/effect/evidence",
        "workflow step/owner/input/output/side effect/evidence",
        "failure mode/trigger/handling/evidence",
        "state transition/current state/trigger/next state/evidence",
        "extension point/current owner/change path/contract/evidence",
      ],
      code_examples:
        "Use exact source snippets only when source_chunks provide them; otherwise prefer prose over invented examples.",
      related_pages:
        "Mention related pages only from catalog_context.related_pages and only when the relationship is supported by the retrieved evidence.",
      missing_information:
        "If a detail is expected but absent from source evidence, state the gap briefly instead of filling it with assumptions.",
      depth_targets: [
        "explain how the subsystem is entered and what it returns or mutates",
        "name important collaborators and why each boundary exists",
        "describe data contracts, persistence records, schemas, DTOs, or component props",
        "trace at least two end-to-end workflows when graph_facts or source_chunks support them",
        "distinguish thin adapters from domain logic and explain handoff points",
        "explain cache, reuse, recomputation, pruning, or persistence behavior when visible",
        "call out validation, retry, fallback, draft/error state, or cleanup behavior",
        "identify extension points and contracts that constrain future changes",
        "include representative tests only when they clarify observable behavior",
      ],
    },
    diagram_placement: {
      placeholder_format: "[[DIAGRAM:<slot>]]",
      instructions:
        "The server generates Mermaid from graph facts. When a listed diagram slot would clarify a section, place the exact placeholder on its own line near the paragraph that introduces that relationship. Do not invent slots. If no slot fits naturally, omit placeholders and the server will place diagrams near matching headings.",
    },
    agent_tools: {
      available: [
        {
          name: "ReadFile",
          purpose: "Read exact repository source ranges before writing.",
        },
      ],
      required_for_page_generation: ["ReadFile"],
    },
    server_diagram_strategy: {
      diagram_generation: "server_generated_from_graph_facts_only",
      llm_must_not_emit_mermaid: true,
      strategies: {
        component: "graph TD for high-level component dependency maps",
        data_flow: "flowchart LR for data moving between components",
        control_flow: "flowchart TD for hierarchical control or route flow",
        symbol_flow:
          "flowchart TD for concrete endpoints, functions, methods, and calls",
        sequence:
          "sequenceDiagram for request/response or multi-agent interactions",
        data_model: "classDiagram for schemas, classes, DTOs, and inheritance",
      },
      grouping:
        "Prefer flexible subsystem/file labels over raw community names when the graph group name is too generic. Diagrams are inserted in context rather than as a fixed Graph section at the end.",
    },
    required_json_shape: {
      title: "Use the exact page title from page_payload.title.",
      markdown:
        "# Page title\n\n## Purpose and Scope\n\nGrounded Markdown with inline [[S1]] citations, optional [[DIAGRAM:slot]] placeholders from diagram_slots, and no Mermaid fences.",
      source_refs: [
        {
          citation_id: "S1",
          file_path: "path.py",
          start_line: 1,
          end_line: 5,
        },
      ],
    },
  };
}

function promptNode(node: JsonObject): JsonObject {
  return compactJsonObject({
    id: node.id,
    type: node.type,
    name: node.name,
    file_path: node.file_path,
    line: lineRange(node),
    hop: node.hop,
    score: node.score,
    confidence: node.confidence,
  });
}

function promptEdge(edge: JsonObject): JsonObject {
  return compactJsonObject({
    id: edge.id,
    source: edge.source,
    target: edge.target,
    type: edge.type,
    confidence: edge.confidence,
    reason: edge.reason,
  });
}

function promptCommunitySummary(community: JsonObject): JsonObject {
  const nodeIds = Array.isArray(community.node_ids)
    ? community.node_ids.filter(
        (value): value is string => typeof value === "string",
      )
    : [];
  return compactJsonObject({
    id: community.id,
    name: community.name,
    level: community.level,
    parent_id: community.parent_id,
    summary: community.summary,
    node_count: numberValue(community.node_count) ?? nodeIds.length,
    matched_node_ids: Array.isArray(community.matched_node_ids)
      ? community.matched_node_ids
      : nodeIds,
  });
}

function communityHierarchy(communities: JsonObject[]): JsonObject[] {
  const byId = new Map<string, JsonObject>();
  const roots: JsonObject[] = [];
  for (const community of communities) {
    const id = stringValue(community.id);
    if (id) {
      byId.set(id, promptCommunitySummary(community));
    }
  }
  for (const community of communities) {
    const id = stringValue(community.id);
    if (!id) {
      continue;
    }
    const item = byId.get(id);
    if (!item) {
      continue;
    }
    const parentId = stringValue(community.parent_id);
    const parent = parentId ? byId.get(parentId) : null;
    if (parent) {
      const children = Array.isArray(parent.children) ? parent.children : [];
      children.push(item);
      parent.children = children;
    } else {
      roots.push(item);
    }
  }
  return roots;
}

function lineRange(item: JsonObject): string | null {
  const startLine = numberValue(item.start_line);
  const endLine = numberValue(item.end_line);
  if (!startLine) {
    return null;
  }
  return endLine && endLine !== startLine
    ? `${startLine}-${endLine}`
    : String(startLine);
}

function compactJsonObject(values: Record<string, unknown>): JsonObject {
  const payload: JsonObject = {};
  for (const [key, value] of Object.entries(values)) {
    if (value === undefined || value === null || value === "") {
      continue;
    }
    if (Array.isArray(value) && !value.length) {
      continue;
    }
    if (isJsonValue(value)) {
      payload[key] = value;
    }
  }
  return payload;
}

function isJsonValue(value: unknown): value is JsonValue {
  if (
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean" ||
    value === null
  ) {
    return true;
  }
  if (Array.isArray(value)) {
    return value.every(isJsonValue);
  }
  return isRecord(value) && Object.values(value).every(isJsonValue);
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) ? value : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
