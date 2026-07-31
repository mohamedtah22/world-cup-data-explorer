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
import TournamentResultsPortal from "./components/TournamentResultsPortal";
import "./style.css";
import "./premium.css";

const pages = [
  { key: "overview", label: "Home", icon: "overview", component: Overview, description: "World Cup history, records, and trends in one live database." },
  { key: "tournaments", label: "Tournaments", icon: "tournaments", component: Tournaments, description: "Choose any edition and open its champion, final ranking, teams, scorers, matches, and headline numbers." },
  { key: "matches", label: "Matches", icon: "matches", component: Matches, description: "Search the complete match archive by edition, team, stage, date, or venue." },
  { key: "teams", label: "Teams", icon: "teams", component: Teams, description: "Explore every national team's historical World Cup record." },
  { key: "players", label: "Players", icon: "players", component: Players, description: "Inspect player careers, tournament appearances, goals, and match history." },
  { key: "leaderboards", label: "Leaderboards", icon: "leaderboard", component: PlayerLeaderboards, description: "All-time player rankings across the statistics covered by the database." },
  { key: "team-compare", label: "Team Compare", icon: "compare", component: Compare, description: "Compare two national teams side by side." },
  { key: "player-compare", label: "Player Compare", icon: "playerCompare", component: PlayerCompare, description: "Compare two players using the same database measures." },
  { key: "data-quality", label: "Data Quality", icon: "quality", component: DataQuality, description: "Review data sources, coverage, cleaning, and validation results." },
];

function getInitialPage() {
  const hash = window.location.hash.replace(/^#\/?/, "");
  return pages.some((page) => page.key === hash) ? hash : "overview";
}

export default function App() {
  const [pageKey, setPageKey] = useState(getInitialPage);
  const [menuOpen, setMenuOpen] = useState(false);
  const page = useMemo(() => pages.find((item) => item.key === pageKey) || pages[0], [pageKey]);
  const CurrentPage = page.component;

  useEffect(() => {
    window.location.hash = pageKey;
    window.scrollTo({ top: 0, behavior: "smooth" });
    setMenuOpen(false);
  }, [pageKey]);

  useEffect(() => {
    function onHashChange() {
      const hash = window.location.hash.replace(/^#\/?/, "");
      if (pages.some((item) => item.key === hash)) setPageKey(hash);
    }
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  return (
    <main className="site-shell">
      <header className="topbar">
        <button className="brand-button" onClick={() => setPageKey("overview")} aria-label="Open home page">
          <span className="brand-emblem" aria-hidden="true"><Icon name="goal" size={23} /></span>
          <span className="brand-copy">
            <strong>WORLD CUP</strong>
            <small>DATA EXPLORER</small>
          </span>
        </button>

        <nav className={`main-navigation ${menuOpen ? "navigation-open" : ""}`} aria-label="Primary navigation">
          {pages.map((item) => (
            <button
              key={item.key}
              className={pageKey === item.key ? "active" : ""}
              onClick={() => setPageKey(item.key)}
            >
              <Icon name={item.icon} size={17} />
              <span>{item.label}</span>
            </button>
          ))}
        </nav>

        <div className="topbar-actions">
          <div className="live-data-badge"><span className="status-dot" /> Live database</div>
          <button className="mobile-menu-button" onClick={() => setMenuOpen((open) => !open)} aria-label="Toggle navigation">
            <Icon name={menuOpen ? "close" : "menu"} />
          </button>
        </div>
      </header>

      {menuOpen && <button className="nav-backdrop" aria-label="Close navigation" onClick={() => setMenuOpen(false)} />}

      <section className="page-shell">
        <header className="page-intro">
          <div>
            <span className="eyebrow">FIFA MEN&apos;S WORLD CUP · 1930—2026</span>
            <h1>{page.label}</h1>
            <p>{page.description}</p>
          </div>
          <div className="page-intro-meta">
            <span>React</span><span>Flask</span><span>PostgreSQL</span>
          </div>
        </header>

        <CurrentPage />
        {pageKey === "tournaments" && <TournamentResultsPortal />}

        <footer className="site-footer">
          <div><strong>World Cup Data Explorer</strong><span>Real-world relational data, cleaned and connected.</span></div>
          <small>Free Render services may need about 40 seconds to wake up on the first visit.</small>
        </footer>
      </section>
    </main>
  );
}
