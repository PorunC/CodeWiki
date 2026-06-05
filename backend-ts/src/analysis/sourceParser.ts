export type SymbolRecord = {
  name: string;
  type: "function" | "class" | "method" | "interface" | "route" | "variable";
  file_path: string;
  start_line: number;
  end_line: number;
  language: string;
  signature: string;
};

export type ImportRecord = {
  file_path: string;
  target: string;
  line: number;
  raw: string;
};

export type FileParseResult = {
  symbols: SymbolRecord[];
  imports: ImportRecord[];
  calls: Array<{ file_path: string; name: string; line: number }>;
};

export function parseSource(
  filePath: string,
  language: string,
  content: string,
): FileParseResult {
  const lines = content.split(/\r?\n/);
  const symbols: SymbolRecord[] = [];
  const imports: ImportRecord[] = [];
  const calls: Array<{ file_path: string; name: string; line: number }> = [];

  for (const [index, line] of lines.entries()) {
    const lineNumber = index + 1;
    const trimmed = line.trim();
    const symbol = parseSymbolLine(
      filePath,
      language,
      trimmed,
      lineNumber,
      lines.length,
    );
    if (symbol) {
      symbols.push(symbol);
    }
    const importRecord = parseImportLine(
      filePath,
      language,
      trimmed,
      lineNumber,
    );
    if (importRecord) {
      imports.push(importRecord);
    }
    for (const callName of parseCallNames(language, trimmed)) {
      calls.push({ file_path: filePath, name: callName, line: lineNumber });
    }
  }

  return { symbols, imports, calls };
}

function parseSymbolLine(
  filePath: string,
  language: string,
  line: string,
  lineNumber: number,
  fileLineCount: number,
): SymbolRecord | null {
  const patterns: Array<[RegExp, SymbolRecord["type"]]> = [
    [/^def\s+([A-Za-z_][\w]*)\s*\(/, "function"],
    [/^async\s+def\s+([A-Za-z_][\w]*)\s*\(/, "function"],
    [/^class\s+([A-Za-z_][\w]*)\b/, "class"],
    [
      /^(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(/,
      "function",
    ],
    [/^(?:export\s+)?class\s+([A-Za-z_$][\w$]*)\b/, "class"],
    [/^(?:export\s+)?interface\s+([A-Za-z_$][\w$]*)\b/, "interface"],
    [
      /^(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(/,
      "function",
    ],
    [
      /^(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*[^=]/,
      "variable",
    ],
    [
      /^(?:public\s+|private\s+|protected\s+|static\s+)*(?:async\s+)?([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{?$/,
      "method",
    ],
    [/^func\s+(?:\([^)]+\)\s*)?([A-Za-z_][\w]*)\s*\(/, "function"],
    [/^type\s+([A-Za-z_][\w]*)\s+(?:struct|interface)\b/, "class"],
    [/^fn\s+([A-Za-z_][\w]*)\s*\(/, "function"],
    [/^pub\s+fn\s+([A-Za-z_][\w]*)\s*\(/, "function"],
  ];
  for (const [pattern, type] of patterns) {
    const match = line.match(pattern);
    if (!match?.[1]) {
      continue;
    }
    return {
      name: match[1],
      type,
      file_path: filePath,
      start_line: lineNumber,
      end_line: Math.min(fileLineCount, lineNumber + 40),
      language,
      signature: line.slice(0, 300),
    };
  }

  const routeMatch = line.match(
    /\.(get|post|put|patch|delete)\(\s*["'`]([^"'`]+)["'`]/,
  );
  if (routeMatch?.[2]) {
    return {
      name: `${routeMatch[1]?.toUpperCase() ?? "ROUTE"} ${routeMatch[2]}`,
      type: "route",
      file_path: filePath,
      start_line: lineNumber,
      end_line: lineNumber,
      language,
      signature: line.slice(0, 300),
    };
  }
  return null;
}

function parseImportLine(
  filePath: string,
  language: string,
  line: string,
  lineNumber: number,
): ImportRecord | null {
  const patterns =
    language === "python"
      ? [/^import\s+([A-Za-z_][\w.]*)/, /^from\s+([A-Za-z_][\w.]*)\s+import\s+/]
      : [
          /^import\s+.+?\s+from\s+["'`]([^"'`]+)["'`]/,
          /^import\s+["'`]([^"'`]+)["'`]/,
          /^export\s+.+?\s+from\s+["'`]([^"'`]+)["'`]/,
        ];
  for (const pattern of patterns) {
    const match = line.match(pattern);
    if (match?.[1]) {
      return {
        file_path: filePath,
        target: match[1],
        line: lineNumber,
        raw: line,
      };
    }
  }
  return null;
}

function parseCallNames(language: string, line: string): string[] {
  if (
    /^(?:import|from|class|interface|type|def|function|func|fn)\b/.test(line)
  ) {
    return [];
  }
  const names = new Set<string>();
  const callPattern = /([A-Za-z_$][\w$]*)\s*\(/g;
  for (const match of line.matchAll(callPattern)) {
    const name = match[1];
    if (!name || RESERVED_CALL_WORDS.has(name)) {
      continue;
    }
    if (
      language === "python" &&
      ["print", "len", "str", "int", "list", "dict"].includes(name)
    ) {
      continue;
    }
    names.add(name);
  }
  return [...names];
}

const RESERVED_CALL_WORDS = new Set([
  "if",
  "for",
  "while",
  "switch",
  "catch",
  "function",
  "return",
  "typeof",
  "new",
  "super",
  "await",
  "Promise",
]);
