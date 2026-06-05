import type {
  FastifyInstance,
  FastifyRequest,
  FastifyServerOptions,
} from "fastify";
import type { CodeWikiSettings } from "../config.js";

type FastifyLoggingOptions = Pick<
  FastifyServerOptions,
  "disableRequestLogging" | "logger"
>;

type LogRecord = Record<string, unknown> & {
  err?: { message?: string; stack?: string } | Error;
  level?: number | string;
  method?: string;
  msg?: string;
  reqId?: string;
  responseTime?: number;
  statusCode?: number;
  time?: number | string;
  url?: string;
};

type LogDestination = {
  write: (chunk: string) => void;
};

const LEVEL_LABELS: Record<number, string> = {
  10: "TRACE",
  20: "DEBUG",
  30: "INFO",
  40: "WARN",
  50: "ERROR",
  60: "FATAL",
};

const requestErrors = new WeakMap<FastifyRequest, Error>();

export function fastifyLoggingOptions(
  settings: CodeWikiSettings,
  enabled: boolean,
): FastifyLoggingOptions {
  if (!enabled) {
    return { logger: false };
  }

  const logger = {
    level: settings.log.level,
    ...(settings.log.format === "pretty"
      ? { stream: createPrettyLogStream() }
      : {}),
  };

  return {
    disableRequestLogging: true,
    logger,
  };
}

export function registerHttpRequestLogging(app: FastifyInstance): void {
  app.addHook("onError", async (request, _reply, error) => {
    requestErrors.set(request, error);
  });

  app.addHook("onResponse", async (request, reply) => {
    const error = requestErrors.get(request);
    requestErrors.delete(request);

    const payload = {
      method: request.method,
      url: request.url,
      statusCode: reply.statusCode,
      responseTime: reply.elapsedTime,
      ...(error ? { err: error } : {}),
    };

    if (error || reply.statusCode >= 500) {
      request.log.error(payload, "request completed");
      return;
    }
    if (reply.statusCode >= 400) {
      request.log.warn(payload, "request completed");
      return;
    }
    request.log.info(payload, "request completed");
  });
}

export function createPrettyLogStream(
  destination: LogDestination = process.stdout,
): { write: (chunk: string) => void } {
  let pending = "";
  return {
    write(chunk: string): void {
      pending += chunk;
      let newlineIndex = pending.indexOf("\n");
      while (newlineIndex >= 0) {
        const rawLine = pending.slice(0, newlineIndex);
        pending = pending.slice(newlineIndex + 1);
        writePrettyLine(rawLine, destination);
        newlineIndex = pending.indexOf("\n");
      }
    },
  };
}

export function formatPrettyLogRecord(record: LogRecord): string {
  const prefix = `[${formatTimestamp(record.time)}] ${formatLevel(record.level)}`;
  const message = formatMessage(record);
  const requestId = typeof record.reqId === "string" ? ` #${record.reqId}` : "";
  const errorDetails = formatError(record.err);
  const line = `${prefix} ${message}${requestId}`;
  return errorDetails ? `${line}\n${errorDetails}` : line;
}

function writePrettyLine(rawLine: string, destination: LogDestination): void {
  if (!rawLine.trim()) {
    return;
  }
  try {
    destination.write(
      `${formatPrettyLogRecord(JSON.parse(rawLine) as LogRecord)}\n`,
    );
  } catch {
    destination.write(`${rawLine}\n`);
  }
}

function formatMessage(record: LogRecord): string {
  if (isRequestRecord(record)) {
    return [
      record.method,
      record.url,
      "->",
      record.statusCode.toString(),
      formatDuration(record.responseTime),
    ].join(" ");
  }
  return record.msg ?? "";
}

function isRequestRecord(
  record: LogRecord,
): record is LogRecord &
  Required<Pick<LogRecord, "method" | "responseTime" | "statusCode" | "url">> {
  return (
    typeof record.method === "string" &&
    typeof record.url === "string" &&
    typeof record.statusCode === "number" &&
    typeof record.responseTime === "number"
  );
}

function formatTimestamp(value: LogRecord["time"]): string {
  const date =
    typeof value === "number" || typeof value === "string"
      ? new Date(value)
      : new Date();
  return [
    date.getFullYear().toString().padStart(4, "0"),
    "-",
    pad(date.getMonth() + 1),
    "-",
    pad(date.getDate()),
    " ",
    pad(date.getHours()),
    ":",
    pad(date.getMinutes()),
    ":",
    pad(date.getSeconds()),
    ".",
    date.getMilliseconds().toString().padStart(3, "0"),
  ].join("");
}

function formatLevel(level: LogRecord["level"]): string {
  if (typeof level === "number") {
    return (LEVEL_LABELS[level] ?? `LVL${level}`).padEnd(5, " ");
  }
  if (typeof level === "string" && level) {
    return level.toUpperCase().padEnd(5, " ");
  }
  return "INFO ".padEnd(5, " ");
}

function formatDuration(milliseconds: number): string {
  if (!Number.isFinite(milliseconds)) {
    return "0ms";
  }
  if (milliseconds < 10) {
    return `${milliseconds.toFixed(1)}ms`;
  }
  if (milliseconds < 1000) {
    return `${Math.round(milliseconds)}ms`;
  }
  return `${(milliseconds / 1000).toFixed(2)}s`;
}

function formatError(error: LogRecord["err"]): string {
  if (!error) {
    return "";
  }
  const message = error instanceof Error ? error.message : error.message;
  const stack = error instanceof Error ? error.stack : error.stack;
  if (stack) {
    return stack;
  }
  return message ? `Error: ${message}` : "";
}

function pad(value: number): string {
  return value.toString().padStart(2, "0");
}
