import { BookOpenText, GitBranch, MessageCircleQuestion, Network } from "lucide-react";
import { useCallback, useEffect, useState, type MouseEvent } from "react";

import { AskPage } from "./pages/AskPage";
import { GraphPage } from "./pages/GraphPage";
import { WikiPage } from "./pages/WikiPage";

type WorkspaceSection = "graph" | "wiki" | "ask";

export function App() {
  const [selectedRepoId, setSelectedRepoId] = useState("");
  const [activeSection, setActiveSection] = useState<WorkspaceSection>(() => sectionFromHash());

  useEffect(() => {
    const syncSectionFromUrl = () => setActiveSection(sectionFromHash());

    window.addEventListener("hashchange", syncSectionFromUrl);
    window.addEventListener("popstate", syncSectionFromUrl);
    return () => {
      window.removeEventListener("hashchange", syncSectionFromUrl);
      window.removeEventListener("popstate", syncSectionFromUrl);
    };
  }, []);

  const navigateToSection = useCallback(
    (event: MouseEvent<HTMLAnchorElement>, sectionId: WorkspaceSection) => {
      event.preventDefault();
      setActiveSection(sectionId);
      window.history.pushState(null, "", `#${sectionId}`);
    },
    []
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
            href="#graph"
            onClick={(event) => navigateToSection(event, "graph")}
          >
            <GitBranch size={15} />
            Graph
          </a>
          <a
            className={activeSection === "wiki" ? "is-active" : undefined}
            href="#wiki"
            onClick={(event) => navigateToSection(event, "wiki")}
          >
            <BookOpenText size={15} />
            Wiki
          </a>
          <a
            className={activeSection === "ask" ? "is-active" : undefined}
            href="#ask"
            onClick={(event) => navigateToSection(event, "ask")}
          >
            <MessageCircleQuestion size={15} />
            Ask
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
          onSelectedRepoChange={setSelectedRepoId}
          isActiveSection={activeSection === "graph"}
        />
        {activeSection !== "graph" ? (
          <aside className="assistant-rail">
            {activeSection === "wiki" ? (
              <WikiPage
                selectedRepoId={selectedRepoId}
                onRepoChange={setSelectedRepoId}
                isActiveSection
              />
            ) : null}
            {activeSection === "ask" ? (
              <AskPage
                selectedRepoId={selectedRepoId}
                onRepoChange={setSelectedRepoId}
                isActiveSection={activeSection === "ask"}
              />
            ) : null}
          </aside>
        ) : null}
      </section>
    </main>
  );
}

function sectionFromHash(): WorkspaceSection {
  const hash = window.location.hash.replace("#", "");
  return hash === "wiki" || hash === "ask" || hash === "graph" ? hash : "graph";
}
