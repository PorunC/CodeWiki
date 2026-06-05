import type { JsonObject, JsonValue } from "../types.js";

export const DEFAULT_PROTOCOL_VERSION = "2024-11-05";

export function params(message: JsonObject): JsonObject {
  const value = message.params ?? {};
  if (!isJsonObject(value)) {
    throw new Error("JSON-RPC params must be an object.");
  }
  return value;
}

export function toolResponse(
  payload: unknown,
  options: { isError?: boolean } = {},
): JsonObject {
  const text =
    typeof payload === "string"
      ? payload
      : JSON.stringify(jsonable(payload), null, 2);
  return {
    content: [{ type: "text", text }],
    isError: Boolean(options.isError),
  };
}

export function result(requestId: unknown, payload: unknown): JsonObject {
  return {
    jsonrpc: "2.0",
    id: jsonableId(requestId),
    result: jsonable(payload),
  };
}

export function error(
  requestId: unknown,
  code: number,
  message: string,
): JsonObject {
  return {
    jsonrpc: "2.0",
    id: jsonableId(requestId),
    error: { code, message },
  };
}

export function jsonable(value: unknown): JsonValue {
  if (
    value === null ||
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  ) {
    return value;
  }
  if (typeof value === "bigint") {
    return value.toString();
  }
  if (value instanceof Date) {
    return value.toISOString();
  }
  if (Array.isArray(value)) {
    return value.map((item) => jsonable(item));
  }
  if (value instanceof Set) {
    return [...value].map((item) => jsonable(item));
  }
  if (value instanceof Map) {
    const record: JsonObject = {};
    for (const [key, item] of value.entries()) {
      record[String(key)] = jsonable(item);
    }
    return record;
  }
  if (isJsonObject(value)) {
    const record: JsonObject = {};
    for (const [key, item] of Object.entries(value)) {
      if (typeof item !== "undefined" && typeof item !== "function") {
        record[key] = jsonable(item);
      }
    }
    return record;
  }
  if (typeof value === "undefined") {
    return null;
  }
  return Object.prototype.toString.call(value);
}

export function isJsonObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function jsonableId(value: unknown): JsonValue {
  if (
    typeof value === "string" ||
    typeof value === "number" ||
    value === null
  ) {
    return value;
  }
  return null;
}
