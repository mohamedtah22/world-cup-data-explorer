import { useEffect, useState } from "react";
import { ErrorState, LoadingState } from "../components/StateView";
import { api } from "../services/api";

export default function PlayerCompare() {
  const [players, setPlayers] = useState([]);
  const [player1, setPlayer1] = useState("");
  const [player2, setPlayer2] = useState("");
  const [comparison, setComparison] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    api.playerList({ limit: 100, sort_by: "name", order: "asc" }).then((payload) => setPlayers(payload.results)).catch((err) => setError(err.message));
  }, []);

  useEffect(() => {
    if (!player1 || !player2 || player1 === player2) {
      setComparison(null);
      return;
    }
    setLoading(true);
    setError("");
    api.comparePlayers(player1, player2).then(setComparison).catch((err) => setError(err.message)).finally(() => setLoading(false));
  }, [player1, player2]);

  return (
    <div className="page-stack">
      <div className="filters compare-selectors">
        <label>Player 1<SelectPlayer value={player1} setValue={setPlayer1} players={players} exclude={player2} /></label>
        <label>Player 2<SelectPlayer value={player2} setValue={setPlayer2} players={players} exclude={player1} /></label>
      </div>
      {error && <ErrorState message={error} />}
      {loading && <LoadingState label="Loading player comparison" />}
      {!loading && !comparison && !error && <div className="state">Choose two different players to compare equivalent statistics.</div>}
      {comparison && <div className="compare-grid"><Card row={comparison.player1} /><Card row={comparison.player2} /></div>}
    </div>
  );
}

function SelectPlayer({ value, setValue, players, exclude }) {
  return (
    <select value={value} onChange={(event) => setValue(event.target.value)}>
      <option value="">Choose player</option>
      {players.filter((player) => String(player.player_id) !== String(exclude)).map((player) => <option key={player.player_id} value={player.player_id}>{player.player}</option>)}
    </select>
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
