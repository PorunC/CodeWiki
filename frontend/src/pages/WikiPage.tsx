export function WikiPage() {
  return (
    <section id="wiki" className="side-panel wiki-panel">
      <header>
        <span className="eyebrow">Wiki</span>
        <h2>Documentation</h2>
      </header>
      <div className="wiki-list">
        <div className="wiki-row">
          <span>Catalog</span>
          <strong>Pending</strong>
        </div>
        <div className="wiki-row">
          <span>Pages</span>
          <strong>0</strong>
        </div>
        <div className="wiki-row">
          <span>Sources</span>
          <strong>Graph</strong>
        </div>
      </div>
    </section>
  );
}
