export function AskPage() {
  return (
    <section id="ask" className="side-panel ask-panel">
      <header>
        <span className="eyebrow">Ask</span>
        <h2>GraphRAG</h2>
      </header>
      <form className="ask-form">
        <input placeholder="Ask about this repository" aria-label="Ask about this repository" />
        <button type="submit">Ask</button>
      </form>
    </section>
  );
}
