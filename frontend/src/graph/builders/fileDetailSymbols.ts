import type { CodeNode } from "../../api/types";
import { GROUP_HEADER_HEIGHT, SYMBOL_NODE_HEIGHT, SYMBOL_NODE_WIDTH } from "../constants";
import {
  classDisplayName,
  compactSymbolName,
  formatLineRange,
  functionDisplayName,
  methodDisplayName,
  nodeSummary,
  symbolSummary
} from "../formatters";
import { compareBySourceOrder, nearestAncestorOfType } from "../topology";
import type { ContainmentIndex, FileDetailSymbolSlot } from "../types";

export function layoutFileDetailSymbols(
  symbols: CodeNode[],
  fileId: string,
  containment: ContainmentIndex
): FileDetailSymbolSlot[] {
  const slots: FileDetailSymbolSlot[] = [];
  const processed = new Set<string>();
  const visibleById = new Set(symbols.map((node) => node.id));
  const methodsByClass = new Map<string, CodeNode[]>();

  symbols.forEach((node) => {
    if (node.type !== "method") {
      return;
    }
    const classId = nearestAncestorOfType(node.id, "class", containment);
    if (!classId || !visibleById.has(classId)) {
      return;
    }
    const methods = methodsByClass.get(classId) ?? [];
    methods.push(node);
    methodsByClass.set(classId, methods);
  });

  methodsByClass.forEach((methods) => {
    methods.sort(compareBySourceOrder);
  });

  let y = GROUP_HEADER_HEIGHT + 26;
  const classX = 32;
  const methodX = 330;
  const methodGap = 12;
  const sectionGap = 22;

  symbols.forEach((node) => {
    if (processed.has(node.id)) {
      return;
    }

    if (node.type === "class") {
      const methods = methodsByClass.get(node.id) ?? [];
      const className = classDisplayName(node);
      const methodStackHeight =
        methods.length === 0 ? 0 : methods.length * SYMBOL_NODE_HEIGHT + (methods.length - 1) * methodGap;
      const sectionHeight = Math.max(SYMBOL_NODE_HEIGHT, methodStackHeight);

      slots.push({
        node,
        x: classX,
        y,
        width: SYMBOL_NODE_WIDTH,
        height: SYMBOL_NODE_HEIGHT,
        label: className,
        pathLabel: "class",
        summary: methods.length > 0 ? `${className} / ${methods.length} methods` : className,
        countLabel: formatLineRange(node)
      });
      processed.add(node.id);

      methods.forEach((method, index) => {
        slots.push({
          node: method,
          x: methodX,
          y: y + index * (SYMBOL_NODE_HEIGHT + methodGap),
          width: SYMBOL_NODE_WIDTH,
          height: SYMBOL_NODE_HEIGHT,
          label: methodDisplayName(method),
          pathLabel: className,
          summary: methodDisplayName(method),
          countLabel: formatLineRange(method)
        });
        processed.add(method.id);
      });

      y += sectionHeight + sectionGap;
      return;
    }

    if (node.type === "method") {
      const classId = nearestAncestorOfType(node.id, "class", containment);
      const classNode = classId ? containment.nodeById.get(classId) : null;
      const className = classNode ? classDisplayName(classNode) : "method";

      slots.push({
        node,
        x: classNode ? methodX : classX + 34,
        y,
        width: SYMBOL_NODE_WIDTH,
        height: SYMBOL_NODE_HEIGHT,
        label: methodDisplayName(node),
        pathLabel: className,
        summary: methodDisplayName(node),
        countLabel: formatLineRange(node)
      });
      processed.add(node.id);
      y += SYMBOL_NODE_HEIGHT + sectionGap;
      return;
    }

    slots.push({
      node,
      x: classX,
      y,
      width: SYMBOL_NODE_WIDTH,
      height: SYMBOL_NODE_HEIGHT,
      label: node.type === "function" ? functionDisplayName(node) : compactSymbolName(node),
      pathLabel: node.type === "function" ? "function" : node.type,
      summary: node.type === "function" ? functionDisplayName(node) : symbolSummary(node, nodeSummary(node)),
      countLabel: formatLineRange(node)
    });
    processed.add(node.id);
    y += SYMBOL_NODE_HEIGHT + sectionGap;
  });

  return slots;
}
