import { API_BASE, readJson } from "./http";
import type { WikiResponse } from "./types";

export async function getRepoWiki(repoId: string): Promise<WikiResponse> {
  const response = await fetch(`${API_BASE}/repos/${encodeURIComponent(repoId)}/wiki`);
  return readJson(response, "Repository wiki");
}
