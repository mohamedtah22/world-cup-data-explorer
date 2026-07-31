import { useEffect, useState } from "react";
import DataTable from "../components/DataTable";
import Pagination from "../components/Pagination";
import { ErrorState, LoadingState } from "../components/StateView";
import { api } from "../services/api";
import { formatDecimal, formatNumber, hasValue } from "../utils/format";
import "../leaderboards.css";

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
    api.playerList({ ...filters, page, limit: 25 })
      .then(setPayload)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
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
    {
      key: "player",
      label: "Player",
      render: (row) => <button className="link-button" onClick={() => setSelected(row.player_id)}>{row.player}</button>,
    },
    {
      key: "preferred_position",
      label: "Position",
      optional: true,
      isAvailable: (row) => hasValue(row.preferred_position),
    },
    {
      key: "appearances",
      label: "Apps",
      optional: true,
      isAvailable: (row) => hasValue(row.appearances) && Number(row.appearances) > 0,
      render: (row) => formatNumber(row.appearances),
    },
    {
      key: "starts",
      label: "Starts",
      optional: true,
      isAvailable: (row) => hasValue(row.starts) && Number(row.starts) > 0,
      render: (row) => formatNumber(row.starts),
    },
    {
      key: "substitute_appearances",
      label: "Sub apps",
      optional: true,
      isAvailable: (row) => hasValue(row.substitute_appearances) && Number(row.substitute_appearances) > 0,
      render: (row) => formatNumber(row.substitute_appearances),
    },
    { key: "goals", label: "Goals", render: (row) => formatNumber(row.goals) },
    {
      key: "assists",
      label: "Assists",
      optional: true,
      isAvailable: (row) => hasValue(row.assists) && Number(row.assists) > 0,
      render: (row) => formatNumber(row.assists),
    },
    {
      key: "goals_per_match",
      label: "G/Match",
      optional: true,
      isAvailable: (row) => hasValue(row.goals_per_match) && Number(row.appearances) > 0,
      render: (row) => formatDecimal(row.goals_per_match, 3),
    },
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

        <div className="player-coverage-note">
          Missing source values are left blank instead of being shown as zero or N/A. Historical goals can be available even when detailed appearance or minute records are not.
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
    return <aside className="detail-panel"><h2>Player details</h2><p>Select a player to view the statistics that are actually recorded for that player.</p></aside>;
  }

  const player = detail.profile;
  const metrics = [
    { label: "Appearances", value: Number(player.appearances) > 0 ? player.appearances : null, format: formatNumber },
    { label: "Starts", value: Number(player.starts) > 0 ? player.starts : null, format: formatNumber },
    { label: "Sub apps", value: Number(player.substitute_appearances) > 0 ? player.substitute_appearances : null, format: formatNumber },
    { label: "Minutes", value: Number(player.minutes_played) > 0 ? player.minutes_played : null, format: formatNumber },
    { label: "Goals", value: player.goals, format: formatNumber },
    { label: "Penalty goals", value: Number(player.penalty_goals) > 0 ? player.penalty_goals : null, format: formatNumber },
    { label: "Assists", value: Number(player.assists) > 0 ? player.assists : null, format: formatNumber },
    { label: "Goals / match", value: Number(player.appearances) > 0 && hasValue(player.goals_per_match) ? player.goals_per_match : null, format: (value) => formatDecimal(value, 3) },
  ].filter((metric) => hasValue(metric.value));

  return (
    <aside className="detail-panel">
      <h2>{player.player}</h2>
      <div className="player-metric-grid">
        {metrics.map((metric) => (
          <div className="player-metric" key={metric.label}>
            <span>{metric.label}</span>
            <strong>{metric.format(metric.value)}</strong>
          </div>
        ))}
      </div>

      {Number(player.appearances) === 0 && Number(player.goals) > 0 && (
        <div className="player-coverage-note">Goal records exist for this player, but complete appearance coverage is not available. Rate statistics are therefore omitted.</div>
      )}

      <h3>Tournaments</h3>
      <div className="chip-list">
        {(detail.tournaments || []).map((row) => (
          <span key={`${row.year}-${row.team}`}>{row.year} {row.team}: {formatNumber(row.goals)} goals</span>
        ))}
      </div>

      <h3>Recent match history</h3>
      {(detail.match_history || []).length ? (
        <div className="history">
          {detail.match_history.slice(0, 8).map((match) => (
            <p key={match.match_id}><b>{match.year}</b> {match.home_team} {match.home_score}:{match.away_score} {match.away_team} · {formatNumber(match.goals || 0)} goals{Number(match.assists) > 0 ? ` · ${formatNumber(match.assists)} assists` : ""}</p>
          ))}
        </div>
      ) : <p className="empty-history">No recorded match-by-match appearance history is available for this player.</p>}
    </aside>
  );
}
