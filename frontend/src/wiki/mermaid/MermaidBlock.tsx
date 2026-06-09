import { Maximize2, RotateCcw, X, ZoomIn, ZoomOut } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

let mermaidPromise: Promise<typeof import("mermaid").default> | null = null;
type ThemeMode = "dark" | "light";
const MIN_SCALE = 0.5;
const MAX_SCALE = 4;
const SCALE_STEP = 0.1;

export function MermaidBlock({ chart }: { chart: string }) {
  const reactId = useId();
  const diagramId = useMemo(
    () => `wiki-mermaid-${reactId.replace(/[^a-zA-Z0-9_-]/g, "")}-${hashString(chart)}`,
    [chart, reactId]
  );
  const [svg, setSvg] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [scale, setScale] = useState(1);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const theme = useDocumentTheme();

  useEffect(() => {
    setScale(1);
    setIsFullscreen(false);
  }, [chart]);

  useEffect(() => {
    if (!isFullscreen) {
      return;
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsFullscreen(false);
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    closeButtonRef.current?.focus();
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isFullscreen]);

  useEffect(() => {
    let cancelled = false;
    setSvg("");
    setError(null);
    loadMermaid()
      .then((mermaidApi) => {
        mermaidApi.initialize(getMermaidConfig(theme));
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
  }, [chart, diagramId, theme]);

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

  const zoomOut = () => setScale((current) => clampScale(current - SCALE_STEP));
  const zoomIn = () => setScale((current) => clampScale(current + SCALE_STEP));
  const resetZoom = () => setScale(1);
  const renderCanvas = (className = "mermaid-canvas") => (
    <div
      className={className}
      style={{ transform: `scale(${scale})` }}
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
  const renderToolbar = (mode: "inline" | "fullscreen") => (
    <div
      className="mermaid-toolbar"
      aria-label={mode === "fullscreen" ? "Fullscreen diagram controls" : "Diagram zoom controls"}
    >
      <button type="button" title="Zoom out" aria-label="Zoom out" onClick={zoomOut}>
        <ZoomOut size={14} />
      </button>
      <span>{Math.round(scale * 100)}%</span>
      <button type="button" title="Zoom in" aria-label="Zoom in" onClick={zoomIn}>
        <ZoomIn size={14} />
      </button>
      <button type="button" title="Reset zoom" aria-label="Reset zoom" onClick={resetZoom}>
        <RotateCcw size={14} />
      </button>
      {mode === "fullscreen" ? (
        <button
          ref={closeButtonRef}
          type="button"
          title="Close fullscreen"
          aria-label="Close fullscreen diagram"
          onClick={() => setIsFullscreen(false)}
        >
          <X size={15} />
        </button>
      ) : (
        <button
          type="button"
          title="Open fullscreen"
          aria-label="Open diagram fullscreen"
          onClick={() => setIsFullscreen(true)}
        >
          <Maximize2 size={14} />
        </button>
      )}
    </div>
  );

  return (
    <>
      <div className="mermaid-block">
        {renderToolbar("inline")}
        <div className="mermaid-viewport" aria-hidden={isFullscreen}>
          {isFullscreen ? null : renderCanvas()}
        </div>
      </div>
      {isFullscreen
        ? createPortal(
            <div
              className="mermaid-fullscreen"
              role="dialog"
              aria-modal="true"
              aria-label="Fullscreen Mermaid diagram"
            >
              <div className="mermaid-fullscreen-header">{renderToolbar("fullscreen")}</div>
              <div className="mermaid-fullscreen-viewport">
                {renderCanvas("mermaid-canvas mermaid-canvas-fullscreen")}
              </div>
            </div>,
            document.body
          )
        : null}
    </>
  );
}

function clampScale(value: number): number {
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, Number(value.toFixed(2))));
}

function useDocumentTheme(): ThemeMode {
  const [theme, setTheme] = useState<ThemeMode>(() => readDocumentTheme());

  useEffect(() => {
    const observer = new MutationObserver(() => setTheme(readDocumentTheme()));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observer.disconnect();
  }, []);

  return theme;
}

function readDocumentTheme(): ThemeMode {
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

function getMermaidConfig(theme: ThemeMode) {
  const styles = getComputedStyle(document.documentElement);
  const color = (name: string) => styles.getPropertyValue(name).trim();

  return {
    startOnLoad: false,
    securityLevel: "strict" as const,
    theme: theme === "dark" ? ("dark" as const) : ("default" as const),
    themeVariables: {
      background: color("--color-surface"),
      primaryColor: color("--color-elevated"),
      primaryBorderColor: color("--color-accent"),
      primaryTextColor: color("--color-text-primary"),
      lineColor: color("--color-accent"),
      secondaryColor: color("--color-panel"),
      tertiaryColor: color("--color-code-bg")
    }
  };
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
