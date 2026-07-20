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
        <Board title="Goals per match" rows={data.goals_per_match} value="goals_per_match" />
        <Board title="Yellow cards" rows={data.yellow_cards} value="yellow_cards" />
        <Board title="Red cards" rows={data.red_cards} value="red_cards" />
        <Board title="StatsBomb advanced coverage" rows={data.advanced} value="shots" subValue="pass_completion" />
      </div>
    </div>
  );
}

function Board({ title, rows, value, subValue }) {
  return (
    <article className="panel">
      <h2>{title}</h2>
      <ol className="rank-list">
        {rows.map((row) => (
          <li key={`${title}-${row.player_id}`}>
            <span><b>{row.player}</b>{subValue && <small>{row[subValue] ?? "N/A"}% pass completion</small>}</span>
            <strong>{row[value] ?? "N/A"}</strong>
          </li>
        ))}
      </ol>
    </article>
  );
}
