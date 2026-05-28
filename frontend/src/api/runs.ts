import { API_BASE, readJson } from "./http";
import type { AnalysisRunResponse, IncrementalUpdateResponse } from "./types";

export async function analyzeRepo(
  repoId: string,
  payload: { name_communities?: boolean } = {}
): Promise<AnalysisRunResponse> {
  const response = await fetch(`${API_BASE}/repos/${encodeURIComponent(repoId)}/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  return readJson(response, "Repository analysis");
}

export async function getAnalysisRun(repoId: string, runId: string): Promise<AnalysisRunResponse> {
  const response = await fetch(
    `${API_BASE}/repos/${encodeURIComponent(repoId)}/runs/${encodeURIComponent(runId)}`
  );
  return readJson(response, "Analysis run");
}

export async function updateRepo(
  repoId: string,
  payload: {
    refresh_chunks?: boolean;
    name_communities?: boolean;
    regenerate_wiki?: boolean;
  } = {}
): Promise<IncrementalUpdateResponse> {
  const response = await fetch(`${API_BASE}/repos/${encodeURIComponent(repoId)}/update`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  return readJson(response, "Repository update");
}
