import { useEffect, useState } from "react";
import DataTable from "../components/DataTable";
import Pagination from "../components/Pagination";
import { ErrorState, LoadingState } from "../components/StateView";
import { api } from "../services/api";

export default function Teams() {
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState("wins");
  const [order, setOrder] = useState("desc");
  const [page, setPage] = useState(1);
  const [payload, setPayload] = useState(null);
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    setError("");
    api
      .teams({ search, sort_by: sortBy, order, page, limit: 20 })
      .then(setPayload)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [search, sortBy, order, page]);

  useEffect(() => {
    if (!selected) {
      setDetail(null);
      return;
    }
    api.team(selected).then(setDetail).catch((err) => setError(err.message));
  }, [selected]);

  const columns = [
    { key: "team", label: "Team", render: (row) => <button className="link-button" onClick={() => setSelected(row.team_id)}>{row.team}</button> },
    { key: "played", label: "Played" },
    { key: "wins", label: "Wins" },
    { key: "draws", label: "Draws" },
    { key: "losses", label: "Losses" },
    { key: "goals_for", label: "GF" },
    { key: "goals_against", label: "GA" },
    { key: "win_rate", label: "Win rate", render: (row) => `${row.win_rate}%` },
  ];

  return (
    <div className="split-page">
      <div className="page-stack">
        <div className="filters">
          <label>
            Search
            <input value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} />
          </label>
          <label>
            Sort by
            <select value={sortBy} onChange={(event) => { setSortBy(event.target.value); setPage(1); }}>
              {["team", "played", "wins", "draws", "losses", "goals_for", "goals_against", "win_rate"].map((value) => (
                <option key={value} value={value}>{value.replace("_", " ")}</option>
              ))}
            </select>
          </label>
          <label>
            Order
            <select value={order} onChange={(event) => { setOrder(event.target.value); setPage(1); }}>
              <option value="desc">Descending</option>
              <option value="asc">Ascending</option>
            </select>
          </label>
        </div>
        {error && <ErrorState message={error} />}
        {loading && <LoadingState label="Loading teams" />}
        {!loading && !error && (
          <>
            <DataTable columns={columns} rows={payload?.results || []} getKey={(row) => row.team_id} />
            <Pagination page={page} limit={20} total={payload?.pagination?.total || 0} onPage={setPage} />
          </>
        )}
      </div>
      <TeamDetail detail={detail} />
    </div>
  );
}

function TeamDetail({ detail }) {
  if (!detail) {
    return <aside className="detail-panel"><h2>Team details</h2><p>Select a team to inspect its tournament appearances and match history.</p></aside>;
  }
  const team = detail.team;
  return (
    <aside className="detail-panel">
      <h2>{team.team}</h2>
      <div className="mini-grid">
        <span>Played <b>{team.played}</b></span>
        <span>Wins <b>{team.wins}</b></span>
        <span>Draws <b>{team.draws}</b></span>
        <span>Losses <b>{team.losses}</b></span>
        <span>Goals for <b>{team.goals_for}</b></span>
        <span>Goals against <b>{team.goals_against}</b></span>
        <span>Win rate <b>{team.win_rate}%</b></span>
      </div>
      <h3>Tournament appearances</h3>
      <div className="chip-list">
        {detail.tournament_appearances.map((row) => <span key={row.year}>{row.year}: {row.matches} matches</span>)}
      </div>
      <h3>Match history</h3>
      <div className="history">
        {detail.match_history.slice(0, 12).map((match) => (
          <p key={match.match_id}>
            <b>{match.year}</b> {match.home_team} {match.home_score ?? "-"}:{match.away_score ?? "-"} {match.away_team}
          </p>
        ))}
      </div>
    </aside>
  );
}
