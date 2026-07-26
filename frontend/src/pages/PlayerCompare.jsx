import { useEffect, useState } from "react";
import AsyncEntityAutocomplete from "../components/AsyncEntityAutocomplete";
import { ErrorState, LoadingState } from "../components/StateView";
import { api } from "../services/api";

export default function PlayerCompare() {
  const [player1, setPlayer1] = useState(null);
  const [player2, setPlayer2] = useState(null);
  const [comparison, setComparison] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!player1?.id || !player2?.id || player1.id === player2.id) {
      setComparison(null);
      return;
    }
    setLoading(true);
    setError("");
    api.comparePlayers(player1.id, player2.id).then(setComparison).catch((err) => setError(err.message)).finally(() => setLoading(false));
  }, [player1, player2]);

  return (
    <div className="page-stack">
      <div className="filters compare-selectors">
        <AsyncEntityAutocomplete label="Player 1" value={player1} onChange={setPlayer1} search={api.searchPlayers} excludeId={player2?.id} placeholder="Search players" />
        <AsyncEntityAutocomplete label="Player 2" value={player2} onChange={setPlayer2} search={api.searchPlayers} excludeId={player1?.id} placeholder="Search players" />
      </div>
      {error && <ErrorState message={error} />}
      {loading && <LoadingState label="Loading player comparison" />}
      {!loading && !comparison && !error && <div className="state">Choose two different players to compare equivalent statistics.</div>}
      {comparison && <div className="compare-grid"><Card row={comparison.player1} /><Card row={comparison.player2} /></div>}
    </div>
  );
}

function Card({ row }) {
  const advanced = row.advanced_statistics;
  return (
    <article className="panel compare-card">
      <h2>{row.player}</h2>
      <div className="mini-grid">
        <span>Appearances <b>{row.appearances}</b></span>
        <span>Starts <b>{row.starts}</b></span>
        <span>Minutes <b>{row.minutes_played ?? "Unavailable"}</b></span>
        <span>Goals <b>{row.goals}</b></span>
        <span>Goals/match <b>{row.goals_per_match ?? "N/A"}</b></span>
        <span>Penalty goals <b>{row.penalty_goals}</b></span>
        <span>Yellow cards <b>{row.yellow_cards}</b></span>
        <span>Red cards <b>{row.red_cards}</b></span>
      </div>
      <h3>Advanced event statistics</h3>
      {advanced ? <p>Shots {advanced.shots ?? "N/A"}, pass completion {advanced.pass_completion ?? "N/A"}%, tackles {advanced.tackles ?? "N/A"}, interceptions {advanced.interceptions ?? "N/A"}.</p> : <p>Unavailable for this player.</p>}
    </article>
  );
}
