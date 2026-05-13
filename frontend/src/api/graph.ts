import { API_BASE, readJson } from "./http";
import type { GraphResponse } from "./types";

export async function getRepoGraph(repoId: string): Promise<GraphResponse> {
  const response = await fetch(`${API_BASE}/repos/${encodeURIComponent(repoId)}/graph`);
  return readJson(response, "Repository graph");
}
