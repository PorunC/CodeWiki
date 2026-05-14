import { API_BASE, readJson } from "./http";
import type { GenerateWikiPagesResponse, WikiPageGenerationResult, WikiResponse } from "./types";

export async function getRepoWiki(repoId: string): Promise<WikiResponse> {
  const response = await fetch(`${API_BASE}/repos/${encodeURIComponent(repoId)}/wiki`);
  return readJson(response, "Repository wiki");
}

export async function generateWikiPages(repoId: string): Promise<GenerateWikiPagesResponse> {
  const response = await fetch(`${API_BASE}/repos/${encodeURIComponent(repoId)}/wiki/pages/generate`, {
    method: "POST"
  });
  return readJson(response, "Wiki page generation");
}

export async function regenerateWikiPage(repoId: string, slug: string): Promise<WikiPageGenerationResult> {
  const response = await fetch(
    `${API_BASE}/repos/${encodeURIComponent(repoId)}/wiki/pages/${encodeURIComponent(slug)}/regenerate`,
    {
      method: "POST"
    }
  );
  return readJson(response, "Wiki page regeneration");
}
