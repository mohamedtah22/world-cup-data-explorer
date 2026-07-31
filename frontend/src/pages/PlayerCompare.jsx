import { useEffect, useState } from "react";
import AsyncEntityAutocomplete from "../components/AsyncEntityAutocomplete";
import ComparisonBoard from "../components/ComparisonBoard";
import { ErrorState, LoadingState } from "../components/StateView";
import { api } from "../services/api";
import { formatDecimal, formatNumber } from "../utils/format";

const playerMetrics = [
  { key: "appearances", label: "Appearances", value: (row) => row.appearances, format: formatNumber, direction: "higher" },
  { key: "starts", label: "Starts", value: (row) => row.starts, format: formatNumber, direction: "higher" },
  { key: "substitute_appearances", label: "Substitute appearances", value: (row) => row.substitute_appearances, format: formatNumber },
  { key: "minutes_played", label: "Minutes played", value: (row) => row.minutes_played, format: formatNumber, direction: "higher" },
  { key: "tournament_appearances", label: "Tournaments", value: (row) => row.tournament_appearances, format: formatNumber, direction: "higher" },
  { key: "goals", label: "Goals", value: (row) => row.goals, format: formatNumber, direction: "higher" },
  { key: "goals_per_match", label: "Goals per match", value: (row) => row.goals_per_match, format: (value) => formatDecimal(value, 3), direction: "higher" },
  { key: "penalty_goals", label: "Penalty goals", value: (row) => row.penalty_goals, format: formatNumber, direction: "higher" },
  { key: "assists", label: "Assists", value: (row) => row.assists, format: formatNumber, direction: "higher" },
];

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
    api.comparePlayers(player1.id, player2.id)
      .then(setComparison)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [player1, player2]);

  return (
    <div className="page-stack comparison-page">
      <section className="comparison-selector-panel player-selector-panel">
        <div className="comparison-selector-copy">
          <span className="eyebrow">PLAYER DUEL</span>
          <h2>Compare two World Cup careers</h2>
          <p>Missing source fields are removed completely instead of showing “Unavailable”. Zero remains visible because it is a real statistic.</p>
        </div>
        <div className="comparison-selectors">
          <AsyncEntityAutocomplete label="Player 1" value={player1} onChange={setPlayer1} search={api.searchPlayers} excludeId={player2?.id} placeholder="Search for a player" />
          <div className="selector-versus">VS</div>
          <AsyncEntityAutocomplete label="Player 2" value={player2} onChange={setPlayer2} search={api.searchPlayers} excludeId={player1?.id} placeholder="Search for a player" />
        </div>
      </section>

      {player1?.id && player2?.id && player1.id === player2.id && <ErrorState message="Choose two different players." />}
      {error && <ErrorState message={error} />}
      {loading && <LoadingState label="Loading player comparison" />}
      {!loading && !comparison && !error && (
        <div className="comparison-empty"><strong>Start a player duel</strong><span>Select two players above to compare their available World Cup statistics.</span></div>
      )}
      {comparison && (
        <ComparisonBoard
          left={comparison.player1}
          right={comparison.player2}
          leftName={comparison.player1.player}
          rightName={comparison.player2.player}
          metrics={playerMetrics}
          type="player"
        />
      )}
    </div>
  );
}
