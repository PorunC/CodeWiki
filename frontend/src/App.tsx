import { AskPage } from "./pages/AskPage";
import { GraphPage } from "./pages/GraphPage";
import { WikiPage } from "./pages/WikiPage";

export function App() {
  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">Code Wiki</div>
        <nav>
          <a href="#wiki">Wiki</a>
          <a href="#graph">Graph</a>
          <a href="#ask">Ask</a>
        </nav>
      </aside>
      <section className="workspace">
        <WikiPage />
        <GraphPage />
        <AskPage />
      </section>
    </main>
  );
}

