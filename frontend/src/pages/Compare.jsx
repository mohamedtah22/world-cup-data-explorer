import { useEffect, useState } from "react";
import AsyncEntityAutocomplete from "../components/AsyncEntityAutocomplete";
import ComparisonBoard from "../components/ComparisonBoard";
import { ErrorState, LoadingState } from "../components/StateView";
import { api } from "../services/api";
import { formatDecimal, formatNumber, hasValue } from "../utils/format";

const teamMetrics = [
  { key: "played", label: "Matches played", value: (row) => row.played, format: formatNumber },
  { key: "wins", label: "Wins", value: (row) => row.wins, format: formatNumber, direction: "higher" },
  { key: "draws", label: "Draws", value: (row) => row.draws, format: formatNumber },
  { key: "losses", label: "Losses", value: (row) => row.losses, format: formatNumber, direction: "lower" },
  { key: "goals_for", label: "Goals scored", value: (row) => row.goals_for, format: formatNumber, direction: "higher" },
  { key: "goals_against", label: "Goals conceded", value: (row) => row.goals_against, format: formatNumber, direction: "lower" },
  { key: "goal_difference", label: "Goal difference", value: (row) => Number(row.goals_for) - Number(row.goals_against), format: formatNumber, direction: "higher" },
  { key: "win_rate", label: "Win rate", value: (row) => row.win_rate, format: (value) => `${formatDecimal(value, 1)}%`, direction: "higher" },
  { key: "appearances", label: "Tournament appearances", value: (row) => row.tournament_appearances, format: formatNumber },
  {
    key: "best_tournament",
    label: "Best tournament by goals",
    value: (row) => hasValue(row.best_tournament_by_goals?.year) && hasValue(row.best_tournament_by_goals?.goals)
      ? `${row.best_tournament_by_goals.year} · ${row.best_tournament_by_goals.goals} goals`
      : null,
  },
];

export default function Compare() {
  const [team1, setTeam1] = useState(null);
  const [team2, setTeam2] = useState(null);
  const [comparison, setComparison] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!team1?.id || !team2?.id || team1.id === team2.id) {
      setComparison(null);
      return;
    }
    setLoading(true);
    setError("");
    api.compare(team1.id, team2.id)
      .then(setComparison)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [team1, team2]);

  return (
    <div className="page-stack comparison-page">
      <section className="comparison-selector-panel">
        <div className="comparison-selector-copy">
          <span className="eyebrow">HEAD-TO-HEAD</span>
          <h2>Choose two national teams</h2>
          <p>Only statistics available for both teams are displayed. The stronger value is highlighted where comparison is meaningful.</p>
        </div>
        <div className="comparison-selectors">
          <AsyncEntityAutocomplete label="Team 1" value={team1} onChange={setTeam1} search={api.searchTeams} excludeId={team2?.id} placeholder="Search for a team" />
          <div className="selector-versus">VS</div>
          <AsyncEntityAutocomplete label="Team 2" value={team2} onChange={setTeam2} search={api.searchTeams} excludeId={team1?.id} placeholder="Search for a team" />
        </div>
      </section>

      {team1?.id && team2?.id && team1.id === team2.id && <ErrorState message="Choose two different teams." />}
      {error && <ErrorState message={error} />}
      {loading && <LoadingState label="Loading team comparison" />}
      {!loading && !error && (!team1?.id || !team2?.id) && (
        <div className="comparison-empty"><strong>Start a comparison</strong><span>Select two teams above to build the head-to-head table.</span></div>
      )}
      {comparison && (
        <ComparisonBoard
          left={comparison.team1}
          right={comparison.team2}
          leftName={comparison.team1.team}
          rightName={comparison.team2.team}
          metrics={teamMetrics}
          type="team"
        />
      )}
    </div>
  );
}
