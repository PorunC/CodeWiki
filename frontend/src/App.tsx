import {
  BookOpenText,
  GitBranch,
  MessageCircleQuestion,
  Network,
  Settings
} from "lucide-react";
import { useCallback, useEffect, useState, type MouseEvent } from "react";

import { AskPage } from "./pages/AskPage";
import { GraphPage } from "./pages/GraphPage";
import { SettingsPage } from "./pages/SettingsPage";
import { WikiPage } from "./pages/WikiPage";

type WorkspaceSection = "graph" | "wiki" | "ask" | "settings";

export function App() {
  const [selectedRepoId, setSelectedRepoId] = useState(() => routeFromLocation().repoId ?? "");
  const [activeSection, setActiveSection] = useState<WorkspaceSection>(() => routeFromLocation().section);

  useEffect(() => {
    const syncRouteFromUrl = () => {
      const route = routeFromLocation();
      setActiveSection(route.section);
      if (route.repoId) {
        setSelectedRepoId(route.repoId);
      }
    };

    window.addEventListener("hashchange", syncRouteFromUrl);
    window.addEventListener("popstate", syncRouteFromUrl);
    return () => {
      window.removeEventListener("hashchange", syncRouteFromUrl);
      window.removeEventListener("popstate", syncRouteFromUrl);
    };
  }, []);

  const navigateToSection = useCallback(
    (event: MouseEvent<HTMLAnchorElement>, sectionId: WorkspaceSection) => {
      event.preventDefault();
      setActiveSection(sectionId);
      window.history.pushState(null, "", pathForSection(sectionId, selectedRepoId));
    },
    [selectedRepoId]
  );

  const handleSelectedRepoChange = useCallback(
    (repoId: string) => {
      setSelectedRepoId(repoId);
      window.history.replaceState(null, "", pathForSection(activeSection, repoId));
    },
    [activeSection]
  );

  return (
    <main className="app-shell noise-overlay">
      <header className="app-header">
        <div className="brand-block">
          <div className="brand-mark">
            <Network size={18} />
          </div>
          <div>
            <div className="brand">Code Wiki</div>
            <div className="brand-subtitle">Repository intelligence</div>
          </div>
        </div>

        <nav className="top-nav" aria-label="Workspace">
          <a
            className={activeSection === "graph" ? "is-active" : undefined}
            href={pathForSection("graph", selectedRepoId)}
            onClick={(event) => navigateToSection(event, "graph")}
          >
            <GitBranch size={15} />
            Graph
          </a>
          <a
            className={activeSection === "wiki" ? "is-active" : undefined}
            href={pathForSection("wiki", selectedRepoId)}
            onClick={(event) => navigateToSection(event, "wiki")}
          >
            <BookOpenText size={15} />
            Wiki
          </a>
          <a
            className={activeSection === "ask" ? "is-active" : undefined}
            href={pathForSection("ask", selectedRepoId)}
            onClick={(event) => navigateToSection(event, "ask")}
          >
            <MessageCircleQuestion size={15} />
            Ask
          </a>
          <a
            className={activeSection === "settings" ? "is-active" : undefined}
            href={pathForSection("settings", selectedRepoId)}
            onClick={(event) => navigateToSection(event, "settings")}
          >
            <Settings size={15} />
            Settings
          </a>
        </nav>

        <div className="runtime-status">
          <span className="status-dot" />
          Local API
        </div>
      </header>

      <section className={`workspace is-section-${activeSection}`}>
        <GraphPage
          selectedRepoId={selectedRepoId}
          onSelectedRepoChange={handleSelectedRepoChange}
          isActiveSection={activeSection === "graph"}
        />
        {activeSection !== "graph" ? (
          <aside className="assistant-rail">
            {activeSection === "wiki" ? (
              <WikiPage
                selectedRepoId={selectedRepoId}
                onRepoChange={handleSelectedRepoChange}
                isActiveSection
              />
            ) : null}
            {activeSection === "ask" ? (
              <AskPage
                selectedRepoId={selectedRepoId}
                onRepoChange={handleSelectedRepoChange}
                isActiveSection={activeSection === "ask"}
              />
            ) : null}
            {activeSection === "settings" ? (
              <SettingsPage
                selectedRepoId={selectedRepoId}
                onRepoChange={handleSelectedRepoChange}
                isActiveSection
              />
            ) : null}
          </aside>
        ) : null}
      </section>
    </main>
  );
}

function routeFromLocation(): { section: WorkspaceSection; repoId?: string } {
  const pathSegments = window.location.pathname.split("/").filter(Boolean).map(decodeURIComponent);
  if (pathSegments[0] === "repos") {
    const repoId = pathSegments[1];
    const section = coerceSection(pathSegments[2], "graph");
    return repoId ? { section, repoId } : { section: "graph" };
  }
  if (pathSegments[0] === "settings") {
    return { section: "settings" };
  }

  const hash = window.location.hash.replace("#", "");
  return { section: coerceSection(hash, "graph") };
}

function coerceSection(value: string | undefined, fallback: WorkspaceSection): WorkspaceSection {
  const sections: WorkspaceSection[] = ["graph", "wiki", "ask", "settings"];
  return sections.includes(value as WorkspaceSection) ? (value as WorkspaceSection) : fallback;
}

function pathForSection(section: WorkspaceSection, repoId: string): string {
  if (repoId) {
    return `/repos/${encodeURIComponent(repoId)}/${section}`;
  }
  return section === "settings" ? "/settings" : `#${section}`;
}
