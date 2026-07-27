import { useEffect, useState } from "react";
import { ErrorState, LoadingState } from "../components/StateView";
import { api } from "../services/api";

export default function PlayerLeaderboards() {
  const [minimum, setMinimum] = useState(5);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setError("");
    api.playerLeaderboards({ minimum_appearances: minimum }).then(setData).catch((err) => setError(err.message));
  }, [minimum]);

  if (error) return <ErrorState message={error} />;
  if (!data) return <LoadingState label="Loading player leaderboards" />;

  return (
    <div className="page-stack">
      <div className="filters">
        <label>
          Minimum appearances
          <input value={minimum} onChange={(event) => setMinimum(event.target.value)} inputMode="numeric" />
        </label>
      </div>
      <div className="dashboard-grid">
        <Board title="Top scorers" rows={data.goals} value="goals" />
        <Board title="Most appearances" rows={data.appearances} value="appearances" />
        <Board title="Most starts" rows={data.starts} value="starts" />
        <Board title="Most substitute appearances" rows={data.substitute_appearances} value="substitute_appearances" />
        <Board title="Most minutes" rows={data.minutes_played} value="minutes_played" />
        <Board title="Goals per match" rows={data.goals_per_match} value="goals_per_match" />
        <Board title="Most assists" rows={data.assists} value="assists" />
      </div>
    </div>
  );
}

function Board({ title, rows, value }) {
  return (
    <article className="panel">
      <h2>{title}</h2>
      <ol className="rank-list">
        {rows.map((row) => (
          <li key={`${title}-${row.player_id}`}>
            <span><b>{row.player}</b></span>
            <strong>{row[value] ?? "N/A"}</strong>
          </li>
        ))}
      </ol>
    </article>
  );
}
