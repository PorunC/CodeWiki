import { API_BASE, readJson } from "./http";
import type {
  GenerateWikiPagesResponse,
  TranslateWikiResponse,
  WikiPageGenerationResult,
  WikiResponse
} from "./types";

export async function getRepoWiki(repoId: string, language = "en"): Promise<WikiResponse> {
  const response = await fetch(`${API_BASE}/repos/${encodeURIComponent(repoId)}/wiki${languageQuery(language)}`);
  return readJson(response, "Repository wiki");
}

export async function generateWikiPages(
  repoId: string,
  language = "en"
): Promise<GenerateWikiPagesResponse> {
  const response = await fetch(
    `${API_BASE}/repos/${encodeURIComponent(repoId)}/wiki/pages/generate${languageQuery(language)}`,
    {
      method: "POST"
    }
  );
  return readJson(response, "Wiki page generation");
}

export async function regenerateWikiPage(
  repoId: string,
  slug: string,
  language = "en"
): Promise<WikiPageGenerationResult> {
  const response = await fetch(
    `${API_BASE}/repos/${encodeURIComponent(repoId)}/wiki/pages/${encodeURIComponent(slug)}/regenerate${languageQuery(language)}`,
    {
      method: "POST"
    }
  );
  return readJson(response, "Wiki page regeneration");
}

export async function translateWiki(
  repoId: string,
  targetLanguage: string,
  sourceLanguage = "en"
): Promise<TranslateWikiResponse> {
  const response = await fetch(`${API_BASE}/repos/${encodeURIComponent(repoId)}/wiki/translate`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      source_language: sourceLanguage,
      target_language: targetLanguage
    })
  });
  return readJson(response, "Wiki translation");
}

function languageQuery(language: string): string {
  return `?${new URLSearchParams({ language }).toString()}`;
}
