import {
  BookOpenText,
  FolderGit2,
  GitBranch,
  MessageCircleQuestion,
  Moon,
  Network,
  Settings,
  Sun
} from "lucide-react";
import { useCallback, useEffect, useState, type MouseEvent } from "react";

import { AskPage } from "./pages/AskPage";
import { GraphPage } from "./pages/GraphPage";
import { ReposPage } from "./pages/ReposPage";
import { SettingsPage } from "./pages/SettingsPage";
import { WikiPage } from "./pages/WikiPage";

export type WorkspaceSection = "repos" | "graph" | "wiki" | "ask" | "settings";
type ThemeMode = "dark" | "light";

const THEME_STORAGE_KEY = "codewiki.theme";

export function App() {
  const [selectedRepoId, setSelectedRepoId] = useState(() => routeFromLocation().repoId ?? "");
  const [activeSection, setActiveSection] = useState<WorkspaceSection>(() => routeFromLocation().section);
  const [theme, setTheme] = useState<ThemeMode>(() => readStoredTheme());

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  }, [theme]);

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

  const openRepoSection = useCallback((repoId: string, section: WorkspaceSection) => {
    setSelectedRepoId(repoId);
    setActiveSection(section);
    window.history.pushState(null, "", pathForSection(section, repoId));
  }, []);

  const nextTheme = theme === "dark" ? "light" : "dark";

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
            className={activeSection === "repos" ? "is-active" : undefined}
            href={pathForSection("repos", selectedRepoId)}
            onClick={(event) => navigateToSection(event, "repos")}
          >
            <FolderGit2 size={15} />
            Repos
          </a>
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
        <button
          type="button"
          className="theme-toggle"
          aria-label={`Switch to ${nextTheme} mode`}
          title={`Switch to ${nextTheme} mode`}
          onClick={() => setTheme(nextTheme)}
        >
          {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
        </button>
      </header>

      <section className={`workspace is-section-${activeSection}`}>
        <GraphPage
          selectedRepoId={selectedRepoId}
          onSelectedRepoChange={handleSelectedRepoChange}
          isActiveSection={activeSection === "graph"}
        />
        {activeSection !== "graph" ? (
          <aside className="assistant-rail">
            {activeSection === "repos" ? (
              <ReposPage
                selectedRepoId={selectedRepoId}
                onRepoChange={handleSelectedRepoChange}
                onOpenRepo={openRepoSection}
                isActiveSection
              />
            ) : null}
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

function readStoredTheme(): ThemeMode {
  const storedTheme = window.localStorage.getItem(THEME_STORAGE_KEY);
  return storedTheme === "light" ? "light" : "dark";
}

function routeFromLocation(): { section: WorkspaceSection; repoId?: string } {
  const pathSegments = window.location.pathname.split("/").filter(Boolean).map(decodeURIComponent);
  if (pathSegments[0] === "repos") {
    const repoId = pathSegments[1];
    const section = coerceSection(pathSegments[2], "graph");
    return repoId ? { section, repoId } : { section: "repos" };
  }
  if (pathSegments[0] === "settings") {
    return { section: "settings" };
  }

  const hash = window.location.hash.replace("#", "");
  return { section: coerceSection(hash, "graph") };
}

function coerceSection(value: string | undefined, fallback: WorkspaceSection): WorkspaceSection {
  const sections: WorkspaceSection[] = ["repos", "graph", "wiki", "ask", "settings"];
  return sections.includes(value as WorkspaceSection) ? (value as WorkspaceSection) : fallback;
}

function pathForSection(section: WorkspaceSection, repoId: string): string {
  if (section === "repos") {
    return "/repos";
  }
  if (repoId) {
    return `/repos/${encodeURIComponent(repoId)}/${section}`;
  }
  return section === "settings" ? "/settings" : `#${section}`;
}
