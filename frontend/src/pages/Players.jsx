import { useEffect, useState } from "react";
import DataTable from "../components/DataTable";
import Pagination from "../components/Pagination";
import { ErrorState, LoadingState } from "../components/StateView";
import { api } from "../services/api";

export default function Players() {
  const [filters, setFilters] = useState({ search: "", team: "", tournament: "", position: "", sort_by: "goals", order: "desc" });
  const [page, setPage] = useState(1);
  const [payload, setPayload] = useState(null);
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    setLoading(true);
    setError("");
    api.playerList({ ...filters, page, limit: 25 }).then(setPayload).catch((err) => setError(err.message)).finally(() => setLoading(false));
  }, [filters, page]);

  useEffect(() => {
    if (!selected) {
      setDetail(null);
      return;
    }
    api.player(selected).then(setDetail).catch((err) => setError(err.message));
  }, [selected]);

  function update(event) {
    setFilters((current) => ({ ...current, [event.target.name]: event.target.value }));
    setPage(1);
  }

  const columns = [
    { key: "player", label: "Player", render: (row) => <button className="link-button" onClick={() => setSelected(row.player_id)}>{row.player}</button> },
    { key: "preferred_position", label: "Position", render: (row) => row.preferred_position || "N/A" },
    { key: "appearances", label: "Apps" },
    { key: "starts", label: "Starts" },
    { key: "substitute_appearances", label: "Sub apps" },
    { key: "goals", label: "Goals" },
    { key: "assists", label: "Assists" },
    { key: "goals_per_match", label: "G/Match", render: (row) => row.goals_per_match ?? "N/A" },
  ];

  return (
    <div className="split-page">
      <div className="page-stack">
        <div className="filters">
          <label>Search<input name="search" value={filters.search} onChange={update} /></label>
          <label>Team<input name="team" value={filters.team} onChange={update} /></label>
          <label>Tournament<input name="tournament" value={filters.tournament} onChange={update} inputMode="numeric" /></label>
          <label>Position<input name="position" value={filters.position} onChange={update} /></label>
          <label>Sort<select name="sort_by" value={filters.sort_by} onChange={update}><option value="goals">Goals</option><option value="appearances">Appearances</option><option value="starts">Starts</option><option value="name">Name</option></select></label>
          <label>Order<select name="order" value={filters.order} onChange={update}><option value="desc">Descending</option><option value="asc">Ascending</option></select></label>
        </div>
        {error && <ErrorState message={error} />}
        {loading && <LoadingState label="Loading players" />}
        {!loading && !error && (
          <>
            <DataTable columns={columns} rows={payload?.results || []} getKey={(row) => row.player_id} />
            <Pagination page={page} limit={25} total={payload?.pagination?.total || 0} onPage={setPage} />
          </>
        )}
      </div>
      <PlayerDetailPanel detail={detail} />
    </div>
  );
}

function PlayerDetailPanel({ detail }) {
  if (!detail) {
    return <aside className="detail-panel"><h2>Player details</h2><p>Select a player to view World Cup appearances, starts, minutes, goals, penalty goals, assists, and data-source coverage.</p></aside>;
  }
  const p = detail.profile;
  return (
    <aside className="detail-panel">
      <h2>{p.player}</h2>
      <div className="mini-grid">
        <span>Appearances <b>{p.appearances}</b></span>
        <span>Starts <b>{p.starts}</b></span>
        <span>Sub apps <b>{p.substitute_appearances}</b></span>
        <span>Minutes <b>{p.minutes_played ?? "N/A"}</b></span>
        <span>Goals <b>{p.goals}</b></span>
        <span>Penalty goals <b>{p.penalty_goals}</b></span>
        <span>Assists <b>{p.assists}</b></span>
      </div>
      <h3>Tournaments</h3>
      <div className="chip-list">{detail.tournaments.map((row) => <span key={`${row.year}-${row.team}`}>{row.year} {row.team}: {row.goals} goals</span>)}</div>
      <h3>Recent match history</h3>
      <div className="history">
        {detail.match_history.slice(0, 8).map((match) => <p key={match.match_id}><b>{match.year}</b> {match.home_team} {match.home_score}:{match.away_score} {match.away_team} · {match.goals || 0} goals · {match.assists || 0} assists</p>)}
      </div>
    </aside>
  );
}
