const API_BASE = "/api";

export type RepoSummary = {
  id: string;
  name: string;
  path: string;
  source_type: string;
};

export type CodeNode = {
  id: string;
  type: string;
  name: string;
  file_path: string | null;
  start_line: number | null;
  end_line: number | null;
  language: string | null;
  symbol_id: string | null;
  metadata: Record<string, unknown>;
};

export type CodeEdge = {
  id: string;
  source: string;
  target: string;
  type: string;
  confidence: number;
  is_inferred: boolean;
  metadata: Record<string, unknown>;
};

export type GraphResponse = {
  repo_id: string;
  nodes: CodeNode[];
  edges: CodeEdge[];
};

export type SourceRef = {
  file_path: string;
  start_line: number;
  end_line: number;
};

export type AskResponse = {
  answer: string;
  sources: SourceRef[];
  related_nodes: Array<Record<string, unknown> & { id?: string; name?: string; type?: string }>;
  related_edges: Array<Record<string, unknown> & { id?: string; type?: string; source_id?: string; target_id?: string }>;
  trace_id: string;
};

export type WikiCatalogItem = {
  title: string;
  slug: string;
  topic?: string;
  children?: WikiCatalogItem[];
};

export type WikiCatalog = {
  id: string;
  repo_id: string;
  title: string;
  structure: {
    items: WikiCatalogItem[];
  };
  generated_at: string | null;
};

export type WikiPageRecord = {
  id: string;
  repo_id: string;
  slug: string;
  title: string;
  parent_slug: string | null;
  markdown: string;
  source_refs: SourceRef[];
  graph_refs: string[];
  status: string;
  updated_at: string | null;
};

export type WikiResponse = {
  repo_id: string;
  catalog: WikiCatalog | null;
  items: WikiCatalogItem[];
  pages: WikiPageRecord[];
};

export async function getHealth(): Promise<{ status: string }> {
  const response = await fetch(`${API_BASE}/health`);
  return readJson(response, "Health check");
}

export async function getRepos(): Promise<RepoSummary[]> {
  const response = await fetch(`${API_BASE}/repos`);
  return readJson(response, "Repository list");
}

export async function getRepoGraph(repoId: string): Promise<GraphResponse> {
  const response = await fetch(`${API_BASE}/repos/${encodeURIComponent(repoId)}/graph`);
  return readJson(response, "Repository graph");
}

export async function askRepo(repoId: string, question: string): Promise<AskResponse> {
  const response = await fetch(`${API_BASE}/repos/${encodeURIComponent(repoId)}/ask`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      question,
      mode: "graph_rag",
      max_hops: 2,
      include_sources: true,
      include_graph: true
    })
  });
  return readJson(response, "Ask");
}

export async function getRepoWiki(repoId: string): Promise<WikiResponse> {
  const response = await fetch(`${API_BASE}/repos/${encodeURIComponent(repoId)}/wiki`);
  return readJson(response, "Repository wiki");
}

async function readJson<T>(response: Response, label: string): Promise<T> {
  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new Error(`${label} failed: ${response.status}${detail ? ` - ${detail}` : ""}`);
  }
  return response.json() as Promise<T>;
}

async function readErrorDetail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    return typeof body.detail === "string" ? body.detail : "";
  } catch {
    return "";
  }
}
