export function AskPage() {
  return (
    <section id="ask" className="panel">
      <header>
        <span className="eyebrow">Ask</span>
        <h2>GraphRAG Q&A</h2>
      </header>
      <form className="ask-form">
        <input placeholder="Ask about this repository" />
        <button type="submit">Ask</button>
      </form>
    </section>
  );
}

