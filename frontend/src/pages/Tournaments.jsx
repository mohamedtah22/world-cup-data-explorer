import { useEffect, useState } from "react";
import DataTable from "../components/DataTable";
import { ErrorState, LoadingState } from "../components/StateView";
import { api } from "../services/api";

export default function Tournaments() {
  const [rows, setRows] = useState([]);
  const [selectedYear, setSelectedYear] = useState(null);
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.tournaments().then((data) => {
      setRows(data);
      if (data.length) setSelectedYear(data[data.length - 1].year);
    }).catch((err) => setError(err.message));
  }, []);

  useEffect(() => {
    if (!selectedYear) return;
    api.tournament(selectedYear).then(setDetail).catch((err) => setError(err.message));
  }, [selectedYear]);

  if (error) return <ErrorState message={error} />;
  if (!rows.length) return <LoadingState label="Loading tournaments" />;

  return (
    <div className="page-stack">
      <div className="tournament-grid">
        {rows.map((row) => (
          <button key={row.year} className={selectedYear === row.year ? "edition active-edition" : "edition"} onClick={() => setSelectedYear(row.year)}>
            <strong>{row.year}</strong>
            <span>{row.matches} matches</span>
            <span>{row.teams} teams</span>
            <span>{row.goals_per_match || 0} goals/match</span>
          </button>
        ))}
      </div>
      {!detail ? <LoadingState label="Loading tournament detail" /> : <TournamentDetail detail={detail} />}
    </div>
  );
}

function TournamentDetail({ detail }) {
  const columns = [
    { key: "match_date", label: "Date" },
    { key: "home_team", label: "Home" },
    { key: "score", label: "Score", render: (row) => `${row.home_score ?? "-"} : ${row.away_score ?? "-"}` },
    { key: "away_team", label: "Away" },
    { key: "stage", label: "Stage" },
  ];
  return (
    <div className="detail-section">
      <article className="panel">
        <h2>{detail.tournament.name}</h2>
        <div className="mini-grid">
          <span>Matches <b>{detail.tournament.matches}</b></span>
          <span>Goals <b>{detail.tournament.goals}</b></span>
          <span>Teams <b>{detail.teams.length}</b></span>
        </div>
      </article>
      <article className="panel">
        <h2>Participating teams</h2>
        <div className="chip-list">{detail.teams.map((team) => <span key={team.team_id}>{team.team}</span>)}</div>
      </article>
      <article className="panel">
        <h2>Top scorers</h2>
        <ol className="rank-list compact">
          {detail.top_scorers.map((row) => <li key={row.player_id}><span><b>{row.player}</b><small>{row.team}</small></span><strong>{row.goals}</strong></li>)}
        </ol>
      </article>
      <DataTable columns={columns} rows={detail.matches} getKey={(row) => row.match_id} />
    </div>
  );
}
