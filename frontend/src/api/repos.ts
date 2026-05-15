import { API_BASE, readJson } from "./http";
import type { RepoSummary } from "./types";

export type CreateRepoPayload = {
  path: string;
  name?: string;
  source_type?: string;
};

export async function getHealth(): Promise<{ status: string }> {
  const response = await fetch(`${API_BASE}/health`);
  return readJson(response, "Health check");
}

export async function getRepos(): Promise<RepoSummary[]> {
  const response = await fetch(`${API_BASE}/repos`);
  return readJson(response, "Repository list");
}

export async function createRepo(payload: CreateRepoPayload): Promise<RepoSummary> {
  const response = await fetch(`${API_BASE}/repos`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  return readJson(response, "Repository create");
}

export async function deleteRepo(repoId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/repos/${encodeURIComponent(repoId)}`, {
    method: "DELETE"
  });
  if (!response.ok) {
    await readJson(response, "Repository delete");
  }
}
