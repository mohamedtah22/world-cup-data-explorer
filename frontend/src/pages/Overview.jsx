import { useEffect, useState } from "react";
import { api } from "../services/api";
import { ErrorState, LoadingState } from "../components/StateView";

export default function Overview() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  function load() {
    setError("");
    api.dashboard().then(setData).catch((err) => setError(err.message));
  }

  useEffect(load, []);

  if (error) return <ErrorState message={error} onRetry={load} />;
  if (!data) return <LoadingState label="Loading dashboard" />;

  const counts = data.counts || {};
  const maxGoals = Math.max(...data.goals_by_tournament.map((row) => row.goals), 1);
  return (
    <>
      <div className="cards">
        <Kpi label="Tournaments" value={counts.tournament_count} />
        <Kpi label="Teams" value={counts.team_count} />
        <Kpi label="Matches" value={counts.match_count} />
        <Kpi label="Goals" value={counts.goal_count} />
        <Kpi label="Players" value={counts.player_count} />
        <Kpi label="Player appearances" value={counts.player_appearance_count} />
      </div>
      <div className="dashboard-grid">
        <article className="panel panel-wide">
          <h2>Goals by tournament</h2>
          <div className="bars" aria-label="Goals by tournament">
            {data.goals_by_tournament.map((row) => (
              <div key={row.year} className="bar-item" title={`${row.year}: ${row.goals} goals`}>
                <span style={{ height: `${Math.max(8, (row.goals / maxGoals) * 240)}px` }} />
                <small>{String(row.year).slice(2)}</small>
              </div>
            ))}
          </div>
        </article>
        <RankPanel title="Teams with the most wins" rows={data.teams_with_most_wins} nameKey="team" valueKey="wins" />
        <RankPanel title="Top scorers" rows={data.top_scorers} nameKey="player" valueKey="goals" subKey="team" />
        <RankPanel title="Stadiums with the most matches" rows={data.stadiums_with_most_matches} nameKey="name" valueKey="matches" subKey="city" />
        {data.player_highlights && <article className="panel">
          <h2>Player highlights</h2>
          <p>Top scorer: <b>{data.player_highlights.top_scorer?.player || "N/A"}</b> ({data.player_highlights.top_scorer?.goals || 0})</p>
          <p>Most appearances: <b>{data.player_highlights.most_appearances?.player || "N/A"}</b> ({data.player_highlights.most_appearances?.appearances || 0})</p>
          <p>Most goals in one tournament: <b>{data.player_highlights.most_goals_one_tournament?.player || "N/A"}</b> ({data.player_highlights.most_goals_one_tournament?.year || "N/A"})</p>
        </article>}
      </div>
    </>
  );
}

function Kpi({ label, value }) {
  return (
    <article className="kpi">
      <span>{label}</span>
      <strong>{Number(value || 0).toLocaleString()}</strong>
    </article>
  );
}

function RankPanel({ title, rows, nameKey, valueKey, subKey }) {
  return (
    <article className="panel">
      <h2>{title}</h2>
      <ol className="rank-list">
        {rows.map((row) => (
          <li key={`${title}-${row[nameKey]}-${row[valueKey]}`}>
            <span>
              <b>{row[nameKey]}</b>
              {subKey && <small>{row[subKey]}</small>}
            </span>
            <strong>{row[valueKey]}</strong>
          </li>
        ))}
      </ol>
    </article>
  );
}
