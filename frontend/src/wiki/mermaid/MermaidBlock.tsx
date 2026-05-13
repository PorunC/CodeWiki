import { RotateCcw, ZoomIn, ZoomOut } from "lucide-react";
import { useEffect, useId, useMemo, useState } from "react";

let mermaidInitialized = false;
let mermaidPromise: Promise<typeof import("mermaid").default> | null = null;

export function MermaidBlock({ chart }: { chart: string }) {
  const reactId = useId();
  const diagramId = useMemo(
    () => `wiki-mermaid-${reactId.replace(/[^a-zA-Z0-9_-]/g, "")}-${hashString(chart)}`,
    [chart, reactId]
  );
  const [svg, setSvg] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [scale, setScale] = useState(1);

  useEffect(() => {
    setScale(1);
  }, [chart]);

  useEffect(() => {
    let cancelled = false;
    setSvg("");
    setError(null);
    loadMermaid()
      .then((mermaidApi) => {
        if (!mermaidInitialized) {
          mermaidApi.initialize({
            startOnLoad: false,
            securityLevel: "strict",
            theme: "dark",
            themeVariables: {
              background: "#101111",
              primaryColor: "#1a1b1a",
              primaryBorderColor: "#d4a574",
              primaryTextColor: "#f5f0eb",
              lineColor: "#d4a574",
              secondaryColor: "#132224",
              tertiaryColor: "#0b0c0c"
            }
          });
          mermaidInitialized = true;
        }
        return mermaidApi.render(diagramId, chart);
      })
      .then((result) => {
        if (!cancelled) {
          setSvg(result.svg);
        }
      })
      .catch((renderError: unknown) => {
        if (!cancelled) {
          setError(renderError instanceof Error ? renderError.message : "Failed to render Mermaid diagram");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [chart, diagramId]);

  if (error) {
    return (
      <div className="mermaid-block is-error">
        <strong>Mermaid render failed</strong>
        <pre>{chart}</pre>
      </div>
    );
  }

  if (!svg) {
    return <div className="mermaid-block is-loading">Rendering diagram...</div>;
  }

  return (
    <div className="mermaid-block">
      <div className="mermaid-toolbar" aria-label="Diagram zoom controls">
        <button
          type="button"
          title="Zoom out"
          aria-label="Zoom out"
          onClick={() => setScale((current) => Math.max(0.5, Number((current - 0.1).toFixed(2))))}
        >
          <ZoomOut size={14} />
        </button>
        <span>{Math.round(scale * 100)}%</span>
        <button
          type="button"
          title="Zoom in"
          aria-label="Zoom in"
          onClick={() => setScale((current) => Math.min(2.4, Number((current + 0.1).toFixed(2))))}
        >
          <ZoomIn size={14} />
        </button>
        <button
          type="button"
          title="Reset zoom"
          aria-label="Reset zoom"
          onClick={() => setScale(1)}
        >
          <RotateCcw size={14} />
        </button>
      </div>
      <div className="mermaid-viewport">
        <div
          className="mermaid-canvas"
          style={{ transform: `scale(${scale})` }}
          dangerouslySetInnerHTML={{ __html: svg }}
        />
      </div>
    </div>
  );
}

function loadMermaid(): Promise<typeof import("mermaid").default> {
  mermaidPromise ??= import("mermaid").then((module) => module.default);
  return mermaidPromise;
}

function hashString(value: string): string {
  let hash = 0;
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 31 + value.charCodeAt(index)) >>> 0;
  }
  return hash.toString(36);
}
