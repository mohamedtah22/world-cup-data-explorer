import { useEffect, useState } from "react";
import AsyncEntityAutocomplete from "../components/AsyncEntityAutocomplete";
import { ErrorState, LoadingState } from "../components/StateView";
import { api } from "../services/api";

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
    api.compare(team1.id, team2.id).then(setComparison).catch((err) => setError(err.message)).finally(() => setLoading(false));
  }, [team1, team2]);

  return (
    <div className="page-stack">
      <div className="filters compare-selectors">
        <AsyncEntityAutocomplete label="Team 1" value={team1} onChange={setTeam1} search={api.searchTeams} excludeId={team2?.id} placeholder="Search teams" />
        <AsyncEntityAutocomplete label="Team 2" value={team2} onChange={setTeam2} search={api.searchTeams} excludeId={team1?.id} placeholder="Search teams" />
      </div>
      {team1?.id && team2?.id && team1.id === team2.id && <ErrorState message="Choose two different teams." />}
      {error && <ErrorState message={error} />}
      {loading && <LoadingState label="Loading comparison" />}
      {!loading && !error && (!team1?.id || !team2?.id) && <div className="state">Choose two different teams to compare their SQL-calculated records.</div>}
      {comparison && (
        <div className="compare-grid">
          <CompareCard row={comparison.team1} />
          <CompareCard row={comparison.team2} />
        </div>
      )}
    </div>
  );
}

function CompareCard({ row }) {
  return (
    <article className="panel compare-card">
      <h2>{row.team}</h2>
      <div className="mini-grid">
        <span>Played <b>{row.played}</b></span>
        <span>Wins <b>{row.wins}</b></span>
        <span>Draws <b>{row.draws}</b></span>
        <span>Losses <b>{row.losses}</b></span>
        <span>Goals for <b>{row.goals_for}</b></span>
        <span>Goals against <b>{row.goals_against}</b></span>
        <span>Win rate <b>{row.win_rate}%</b></span>
        <span>Appearances <b>{row.tournament_appearances}</b></span>
      </div>
      <p className="best-line">
        Best tournament by goals: <b>{row.best_tournament_by_goals?.year || "N/A"}</b> ({row.best_tournament_by_goals?.goals || 0})
      </p>
    </article>
  );
}
