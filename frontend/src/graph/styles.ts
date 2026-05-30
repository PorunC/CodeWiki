import type { FlowNode } from "./types";

export function miniMapColor(node: FlowNode): string {
  const data = node.data;
  if (data.kind === "container") {
    return data.accentColor;
  }
  return data.accentColor;
}

export function nodeTone(type: string): { border: string; background: string } {
  switch (type) {
    case "repository":
      return { background: "var(--graph-tone-repository-bg)", border: "var(--graph-tone-repository-border)" };
    case "directory":
      return { background: "var(--graph-tone-directory-bg)", border: "var(--graph-tone-directory-border)" };
    case "file":
      return { background: "var(--graph-tone-file-bg)", border: "var(--graph-tone-file-border)" };
    case "config":
      return { background: "var(--graph-tone-config-bg)", border: "var(--graph-tone-config-border)" };
    case "module":
      return { background: "var(--graph-tone-module-bg)", border: "var(--graph-tone-module-border)" };
    case "class":
      return { background: "var(--graph-tone-class-bg)", border: "var(--graph-tone-class-border)" };
    case "function":
      return { background: "var(--graph-tone-function-bg)", border: "var(--graph-tone-function-border)" };
    case "method":
      return { background: "var(--graph-tone-method-bg)", border: "var(--graph-tone-method-border)" };
    default:
      return { background: "var(--graph-tone-default-bg)", border: "var(--graph-tone-default-border)" };
  }
}

export function edgeTone(type: string): { stroke: string; active: string; label: string } {
  switch (type) {
    case "contains":
      return { stroke: "rgba(212, 165, 116, 0.35)", active: "rgba(232, 196, 154, 0.88)", label: "#d4a574" };
    case "imports":
      return { stroke: "#6e9ee8", active: "#a9c6f5", label: "#a9c6f5" };
    case "calls":
      return { stroke: "#63c08a", active: "#a7dfba", label: "#a7dfba" };
    case "references":
      return { stroke: "#c7aa4a", active: "#ead67d", label: "#ead67d" };
    case "implements":
      return { stroke: "#9ea4f0", active: "#c3c7ff", label: "#c3c7ff" };
    case "uses_config":
      return { stroke: "#d08a58", active: "#efbc8d", label: "#efbc8d" };
    default:
      return { stroke: "rgba(163, 151, 135, 0.58)", active: "#e8c49a", label: "#a39787" };
  }
}
