import { useEffect, useMemo, useState } from "react";
import Overview from "./pages/Overview";
import Matches from "./pages/Matches";
import Teams from "./pages/Teams";
import Tournaments from "./pages/Tournaments";
import Compare from "./pages/Compare";
import DataQuality from "./pages/DataQuality";
import Players from "./pages/Players";
import PlayerLeaderboards from "./pages/PlayerLeaderboards";
import PlayerCompare from "./pages/PlayerCompare";
import Icon from "./components/Icon";

const pageDefinitions = [
  { key: "overview", label: "Overview", icon: "overview", component: Overview, description: "A complete view of World Cup history through 2026." },
  { key: "matches", label: "Matches", icon: "matches", component: Matches, description: "Search every match by edition, team, stage, date, or stadium." },
  { key: "teams", label: "Teams", icon: "teams", component: Teams, description: "Compare historical records, results, and tournament appearances." },
  { key: "players", label: "Players", icon: "players", component: Players, description: "Explore player careers, goals, appearances, and match history." },
  { key: "leaderboards", label: "Leaderboards", icon: "leaderboard", component: PlayerLeaderboards, description: "The leading World Cup players across the main statistics." },
  { key: "tournaments", label: "Tournaments", icon: "tournaments", component: Tournaments, description: "Browse every edition and inspect its teams, scorers, and matches." },
  { key: "team-compare", label: "Team Compare", icon: "compare", component: Compare, description: "Place two national teams side by side." },
  { key: "player-compare", label: "Player Compare", icon: "playerCompare", component: PlayerCompare, description: "Compare two players using equivalent database statistics." },
  { key: "data-quality", label: "Data Quality", icon: "quality", component: DataQuality, description: "See data sources, coverage, cleaning, and quality checks." },
];

function getInitialPage() {
  const hash = window.location.hash.replace(/^#\/?/, "");
  return pageDefinitions.some((page) => page.key === hash) ? hash : "overview";
}

export default function App() {
  const [pageKey, setPageKey] = useState(getInitialPage);
  const [menuOpen, setMenuOpen] = useState(false);
  const page = useMemo(() => pageDefinitions.find((item) => item.key === pageKey) || pageDefinitions[0], [pageKey]);
  const CurrentPage = page.component;

  useEffect(() => {
    window.location.hash = pageKey;
    window.scrollTo({ top: 0, behavior: "smooth" });
    setMenuOpen(false);
  }, [pageKey]);

  useEffect(() => {
    function onHashChange() {
      const hash = window.location.hash.replace(/^#\/?/, "");
      if (pageDefinitions.some((item) => item.key === hash)) setPageKey(hash);
    }
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  return (
    <main className="app-shell">
      <button className="mobile-menu-button" onClick={() => setMenuOpen((open) => !open)} aria-label="Toggle navigation">
        <Icon name={menuOpen ? "close" : "menu"} />
      </button>

      {menuOpen && <button className="nav-backdrop" aria-label="Close navigation" onClick={() => setMenuOpen(false)} />}

      <nav className={`sidebar ${menuOpen ? "sidebar-open" : ""}`} aria-label="Primary navigation">
        <div className="brand">
          <div className="brand-mark"><span /></div>
          <div>
            <strong>World Cup</strong>
            <span>Data Explorer</span>
          </div>
        </div>

        <div className="nav-section-label">Explore</div>
        <div className="nav-items">
          {pageDefinitions.map((item) => (
            <button
              key={item.key}
              className={pageKey === item.key ? "active" : ""}
              onClick={() => setPageKey(item.key)}
            >
              <Icon name={item.icon} size={19} />
              <span>{item.label}</span>
            </button>
          ))}
        </div>

        <div className="sidebar-footer">
          <div className="database-status">
            <span className="status-dot" />
            <div>
              <b>PostgreSQL archive</b>
              <small>23 editions · through 2026</small>
            </div>
          </div>
          <small className="cold-start-note">The free Render API may take about 40 seconds on the first visit.</small>
        </div>
      </nav>

      <section className="content">
        <header className="page-header">
          <div>
            <span className="eyebrow">FIFA Men&apos;s World Cup Archive</span>
            <h1>{page.label}</h1>
            <p>{page.description}</p>
          </div>
          <div className="header-badge">
            <span className="status-dot" />
            Data through 2026
          </div>
        </header>
        <CurrentPage />
        <footer className="app-footer">
          <span>World Cup Data Explorer</span>
          <span>React · Flask · PostgreSQL</span>
        </footer>
      </section>
    </main>
  );
}
