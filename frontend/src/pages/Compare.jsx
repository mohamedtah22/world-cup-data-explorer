import { useEffect, useState } from "react";
import { ErrorState, LoadingState } from "../components/StateView";
import { api } from "../services/api";

export default function Compare() {
  const [teams, setTeams] = useState([]);
  const [team1, setTeam1] = useState("");
  const [team2, setTeam2] = useState("");
  const [comparison, setComparison] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    api.teams({ limit: 500, sort_by: "team", order: "asc" }).then((payload) => setTeams(payload.results)).catch((err) => setError(err.message));
  }, []);

  useEffect(() => {
    if (!team1 || !team2 || team1 === team2) {
      setComparison(null);
      return;
    }
    setLoading(true);
    setError("");
    api.compare(team1, team2).then(setComparison).catch((err) => setError(err.message)).finally(() => setLoading(false));
  }, [team1, team2]);

  return (
    <div className="page-stack">
      <div className="filters compare-selectors">
        <label>
          Team 1
          <select
            value={team1}
            onChange={(event) => {
              const value = event.target.value;
              setTeam1(value);
              if (value === team2) setTeam2("");
            }}
          >
            <option value="">Choose team</option>
            {teams.map((team) => <option key={team.team_id} value={team.team_id}>{team.team}</option>)}
          </select>
        </label>
        <label>
          Team 2
          <select value={team2} onChange={(event) => setTeam2(event.target.value)}>
            <option value="">Choose team</option>
            {teams.filter((team) => String(team.team_id) !== String(team1)).map((team) => <option key={team.team_id} value={team.team_id}>{team.team}</option>)}
          </select>
        </label>
      </div>
      {team1 && team2 && team1 === team2 && <ErrorState message="Choose two different teams." />}
      {error && <ErrorState message={error} />}
      {loading && <LoadingState label="Loading comparison" />}
      {!loading && !error && (!team1 || !team2) && <div className="state">Choose two different teams to compare their SQL-calculated records.</div>}
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
