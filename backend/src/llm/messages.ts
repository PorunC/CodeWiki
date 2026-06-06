import type { JsonValue } from "../types.js";

export function stableJsonMessage(label: string, payload: JsonValue): string {
  return `${label}:\n${stableJson(payload)}`;
}

export function dynamicJsonMessage(label: string, payload: JsonValue): string {
  return `${label}:\n${JSON.stringify(payload)}`;
}

function stableJson(value: JsonValue): string {
  if (Array.isArray(value)) {
    return `[${value.map(stableJson).join(",")}]`;
  }
  if (value && typeof value === "object") {
    return `{${Object.entries(value)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, nested]) => `${JSON.stringify(key)}:${stableJson(nested)}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}
