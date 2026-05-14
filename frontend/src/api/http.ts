export const API_BASE = "/api";

export async function readJson<T>(response: Response, label: string): Promise<T> {
  const contentType = response.headers.get("content-type") ?? "";
  if (!response.ok) {
    const detail = await readErrorDetail(response, contentType);
    throw new Error(`${label} failed: ${response.status}${detail ? ` - ${detail}` : ""}`);
  }
  if (!isJsonResponse(contentType)) {
    const preview = await readTextPreview(response);
    throw new Error(
      `${label} failed: expected JSON from the API but received ${describeContentType(contentType)}.` +
        `${preview ? ` Response started with: ${preview}` : ""}`
    );
  }
  return response.json() as Promise<T>;
}

async function readErrorDetail(response: Response, contentType: string): Promise<string> {
  if (!isJsonResponse(contentType)) {
    return readTextPreview(response);
  }
  try {
    const body = (await response.json()) as { detail?: unknown };
    return typeof body.detail === "string" ? body.detail : "";
  } catch {
    return "";
  }
}

async function readTextPreview(response: Response): Promise<string> {
  try {
    return (await response.text()).trim().replace(/\s+/g, " ").slice(0, 120);
  } catch {
    return "";
  }
}

function isJsonResponse(contentType: string): boolean {
  return contentType.toLowerCase().includes("application/json");
}

function describeContentType(contentType: string): string {
  return contentType ? contentType.split(";")[0] : "non-JSON content";
}
