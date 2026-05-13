export const API_BASE = "/api";

export async function readJson<T>(response: Response, label: string): Promise<T> {
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
