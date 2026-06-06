#!/usr/bin/env node
import { execFileSync } from "node:child_process";

const DEFAULT_LIMIT = 5;
const DEFAULT_MAX_CHARS = 700;

main();

function main() {
  const { positional, options } = parseArgs(process.argv.slice(2));
  if (options.help || positional.length < 2) {
    printHelp();
    process.exit(positional.length < 2 && !options.help ? 1 : 0);
  }

  const [slug, repo] = positional;
  const language = stringOption(options.language, "en");
  const limit = positiveInt(options.limit, DEFAULT_LIMIT);
  const maxChars = positiveInt(options["max-chars"], DEFAULT_MAX_CHARS);
  const codewikiBin = stringOption(options["codewiki-bin"], "codewiki");

  const raw = runCodeWiki(codewikiBin, [
    "wiki",
    "evidence",
    slug,
    repo,
    "--language",
    language,
    "--limit",
    String(limit),
    "--json",
  ]);
  const payload = JSON.parse(raw);
  const compact = compactEvidence(payload, { limit, maxChars });
  process.stdout.write(`${JSON.stringify(compact, null, 2)}\n`);
}

function compactEvidence(payload, options) {
  const trace = objectValue(payload.retrieval_trace);
  const sourceChunks = arrayValue(trace.source_chunks).length
    ? arrayValue(trace.source_chunks)
    : arrayValue(trace.chunks);
  const allowedRefs = arrayValue(payload.allowed_source_refs).slice(0, options.limit);
  const chunksByCitation = new Map(
    sourceChunks
      .map((chunk, index) => {
        const id = stringValue(chunk.citation_id) || `S${index + 1}`;
        return [id, objectValue(chunk)];
      })
      .filter(([id]) => id),
  );

  return {
    repo_id: payload.repo_id,
    language_code: payload.language_code,
    page: compactPage(payload.page),
    catalog_context: compactCatalogContext(payload.catalog_context),
    allowed_source_refs: allowedRefs.map((ref) => compactSourceRef(ref)),
    source_snippets: allowedRefs.map((ref) =>
      compactSnippet(ref, chunksByCitation, options.maxChars),
    ),
    symbols: arrayValue(trace.nodes).slice(0, 8).map(compactNode),
    relationships: arrayValue(trace.related_edges).slice(0, 8).map(compactEdge),
    instructions: [
      "Write only claims supported by source_snippets, symbols, relationships, or catalog_context.",
      "Cite concrete code claims with [[S#]] from allowed_source_refs.",
      "If this compact pack is insufficient, rerun compact-evidence for this slug with a slightly higher --limit.",
    ],
    omitted: {
      retrieval_trace_context: true,
      context_pack: true,
      full_chunk_bodies: true,
      total_source_chunks: sourceChunks.length,
    },
  };
}

function compactSnippet(ref, chunksByCitation, maxChars) {
  const citationId = stringValue(ref.citation_id);
  const chunk = citationId ? chunksByCitation.get(citationId) || {} : {};
  const content = stringValue(chunk.content) || "";
  return {
    ...compactSourceRef(ref),
    score: numberValue(chunk.score),
    match_type: stringValue(chunk.match_type),
    reasons: arrayValue(chunk.reasons).filter((value) => typeof value === "string"),
    excerpt: clip(content, maxChars),
  };
}

function compactSourceRef(ref) {
  return {
    citation_id: stringValue(ref.citation_id),
    file_path: stringValue(ref.file_path),
    start_line: numberValue(ref.start_line),
    end_line: numberValue(ref.end_line),
  };
}

function compactCatalogContext(value) {
  const context = objectValue(value);
  return {
    parent: compactPage(context.parent),
    children: arrayValue(context.children).map(compactPage),
    siblings: arrayValue(context.siblings).map(compactPage),
  };
}

function compactPage(value) {
  if (!value || typeof value !== "object") {
    return null;
  }
  return {
    slug: stringValue(value.slug),
    title: stringValue(value.title),
    parent_slug: stringValue(value.parent_slug),
    kind: stringValue(value.kind),
    path: stringValue(value.path),
    topic: stringValue(value.topic),
    source_hints: arrayValue(value.source_hints).filter(
      (entry) => typeof entry === "string",
    ),
    has_children: booleanValue(value.has_children),
  };
}

function compactNode(value) {
  const node = objectValue(value);
  return {
    id: stringValue(node.id),
    type: stringValue(node.type),
    name: stringValue(node.name),
    file_path: stringValue(node.file_path),
    start_line: numberValue(node.start_line),
    end_line: numberValue(node.end_line),
    summary: clip(stringValue(node.summary) || "", 220),
  };
}

function compactEdge(value) {
  const edge = objectValue(value);
  return {
    type: stringValue(edge.type),
    source: stringValue(edge.source) || stringValue(edge.source_id),
    target: stringValue(edge.target) || stringValue(edge.target_id),
    reason: clip(stringValue(edge.reason) || "", 220),
  };
}

function runCodeWiki(bin, args) {
  try {
    return execFileSync(bin, args, {
      encoding: "utf8",
      maxBuffer: 64 * 1024 * 1024,
      stdio: ["ignore", "pipe", "pipe"],
    });
  } catch (error) {
    const stderr = error?.stderr ? String(error.stderr) : "";
    const message = stderr.trim() || error.message || "codewiki command failed";
    throw new Error(message);
  }
}

function parseArgs(args) {
  const positional = [];
  const options = {};
  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    if (!arg.startsWith("--")) {
      positional.push(arg);
      continue;
    }
    const eq = arg.indexOf("=");
    if (eq > 2) {
      options[arg.slice(2, eq)] = arg.slice(eq + 1);
      continue;
    }
    const key = arg.slice(2);
    if (key === "help") {
      options.help = true;
      continue;
    }
    const next = args[index + 1];
    if (next && !next.startsWith("--")) {
      options[key] = next;
      index += 1;
    } else {
      options[key] = true;
    }
  }
  return { positional, options };
}

function printHelp() {
  process.stdout.write(`Usage: compact-evidence.mjs <slug> <repo> [options]

Options:
  --language <code>       Wiki language. Default: en
  --limit <number>        Source refs to keep. Default: ${DEFAULT_LIMIT}
  --max-chars <number>    Max chars per source excerpt. Default: ${DEFAULT_MAX_CHARS}
  --codewiki-bin <path>   CodeWiki executable. Default: codewiki
`);
}

function clip(value, maxChars) {
  const text = String(value || "").trim();
  if (text.length <= maxChars) {
    return text;
  }
  return `${text.slice(0, maxChars).replace(/\s+\S*$/, "")}\n...`;
}

function objectValue(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function arrayValue(value) {
  return Array.isArray(value) ? value : [];
}

function stringValue(value) {
  return typeof value === "string" && value.length ? value : null;
}

function numberValue(value) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function booleanValue(value) {
  return typeof value === "boolean" ? value : null;
}

function stringOption(value, fallback) {
  return typeof value === "string" && value.length ? value : fallback;
}

function positiveInt(value, fallback) {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}
