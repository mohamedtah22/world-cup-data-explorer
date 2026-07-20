import { useState } from "react";
import Overview from "./pages/Overview";
import Matches from "./pages/Matches";
import Teams from "./pages/Teams";
import Tournaments from "./pages/Tournaments";
import Compare from "./pages/Compare";
import DataQuality from "./pages/DataQuality";
import Players from "./pages/Players";
import PlayerLeaderboards from "./pages/PlayerLeaderboards";
import PlayerCompare from "./pages/PlayerCompare";
import "./style.css";

const pages = {
  Overview,
  Matches,
  Teams,
  Players,
  "Player Leaderboards": PlayerLeaderboards,
  Tournaments,
  Compare,
  "Player Compare": PlayerCompare,
  "Data Quality": DataQuality,
};

export default function App() {
  const [page, setPage] = useState("Overview");
  const CurrentPage = pages[page];

  return (
    <main className="app-shell">
      <nav className="sidebar" aria-label="Primary navigation">
        <div className="brand">
          <strong>World Cup</strong>
          <span>Data Explorer</span>
        </div>
        {Object.keys(pages).map((name) => (
          <button key={name} className={page === name ? "active" : ""} onClick={() => setPage(name)}>
            {name}
          </button>
        ))}
      </nav>
      <section className="content">
        <header className="page-header">
          <div>
            <span>World Cup Archive</span>
            <h1>{page}</h1>
          </div>
        </header>
        <CurrentPage />
      </section>
    </main>
  );
}
