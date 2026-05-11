import { BookOpenText, GitBranch, MessageCircleQuestion, Network } from "lucide-react";

import { AskPage } from "./pages/AskPage";
import { GraphPage } from "./pages/GraphPage";
import { WikiPage } from "./pages/WikiPage";

export function App() {
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
          <a href="#graph">
            <GitBranch size={15} />
            Graph
          </a>
          <a href="#wiki">
            <BookOpenText size={15} />
            Wiki
          </a>
          <a href="#ask">
            <MessageCircleQuestion size={15} />
            Ask
          </a>
        </nav>

        <div className="runtime-status">
          <span className="status-dot" />
          Local API
        </div>
      </header>

      <section className="workspace">
        <GraphPage />
        <aside className="assistant-rail">
          <WikiPage />
          <AskPage />
        </aside>
      </section>
    </main>
  );
}
