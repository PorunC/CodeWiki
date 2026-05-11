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
