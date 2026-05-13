import { API_BASE, readJson } from "./http";
import type { RepoFilesResponse } from "./types";

export async function getRepoFiles(repoId: string): Promise<RepoFilesResponse> {
  const response = await fetch(`${API_BASE}/repos/${encodeURIComponent(repoId)}/files`);
  return readJson(response, "Repository files");
}
