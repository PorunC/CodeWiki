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
      return { background: "#13251d", border: "#69b779" };
    case "directory":
      return { background: "#172129", border: "#5aa9c8" };
    case "file":
      return { background: "#151f2d", border: "#6e9ee8" };
    case "config":
      return { background: "#201f12", border: "#c7aa4a" };
    case "module":
      return { background: "#281d2c", border: "#c78be8" };
    case "class":
      return { background: "#242014", border: "#d7b65c" };
    case "function":
      return { background: "#14251d", border: "#63c08a" };
    case "method":
      return { background: "#241b22", border: "#e0829d" };
    default:
      return { background: "#171717", border: "#a39787" };
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
