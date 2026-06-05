import { describe, expect, it } from "vitest";
import {
  createPrettyLogStream,
  formatPrettyLogRecord,
} from "../src/http/logging.js";

describe("HTTP logging", () => {
  it("formats request records as compact readable lines", () => {
    const line = formatPrettyLogRecord({
      level: 30,
      method: "GET",
      reqId: "req-4",
      responseTime: 1781.451457977295,
      statusCode: 200,
      time: 1780646624077,
      url: "/api/repos/8889b09b261b930e/graph",
    });

    expect(line).toContain(
      "INFO  GET /api/repos/8889b09b261b930e/graph -> 200 1.78s #req-4",
    );
  });

  it("formats server records without raw JSON fields", () => {
    const line = formatPrettyLogRecord({
      level: 30,
      msg: "Server listening at http://127.0.0.1:8000",
      time: 1780646615192,
    });

    expect(line).toContain("INFO  Server listening at http://127.0.0.1:8000");
    expect(line).not.toContain('"level"');
    expect(line).not.toContain('"time"');
  });

  it("formats JSON stream chunks and preserves invalid lines", () => {
    const writes: string[] = [];
    const stream = createPrettyLogStream({
      write: (chunk: string) => {
        writes.push(chunk);
      },
    });

    stream.write(
      '{"level":40,"msg":"first line","time":1780646615192}\n{"level":',
    );
    stream.write('50,"msg":"second line","time":1780646615192}\nnot-json\n');

    expect(writes).toHaveLength(3);
    expect(writes[0]).toContain("WARN  first line");
    expect(writes[1]).toContain("ERROR second line");
    expect(writes[2]).toBe("not-json\n");
  });
});
