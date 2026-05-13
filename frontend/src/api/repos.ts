import { API_BASE, readJson } from "./http";
import type { RepoSummary } from "./types";

export async function getHealth(): Promise<{ status: string }> {
  const response = await fetch(`${API_BASE}/health`);
  return readJson(response, "Health check");
}

export async function getRepos(): Promise<RepoSummary[]> {
  const response = await fetch(`${API_BASE}/repos`);
  return readJson(response, "Repository list");
}
