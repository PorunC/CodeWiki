import { API_BASE, readJson } from "./http";
import type { AskResponse } from "./types";

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
