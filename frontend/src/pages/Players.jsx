import { useEffect, useState } from "react";
import Pagination from "../components/Pagination";
import { EmptyState, ErrorState, LoadingState } from "../components/StateView";
import { api } from "../services/api";
import { formatNumber, hasValue } from "../utils/format";
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

  const rows = payload?.results || [];

  return (
    <div className="players-layout">
      <section className="page-stack players-main-column">
        <div className="filters players-filters">
          <label>Search<input name="search" value={filters.search} onChange={update} /></label>
          <label>Team<input name="team" value={filters.team} onChange={update} /></label>
          <label>Tournament<input name="tournament" value={filters.tournament} onChange={update} inputMode="numeric" /></label>
          <label>Position<input name="position" value={filters.position} onChange={update} /></label>
          <label>Sort<select name="sort_by" value={filters.sort_by} onChange={update}><option value="goals">Goals</option><option value="appearances">Recorded appearances</option><option value="starts">Recorded starts</option><option value="name">Name</option></select></label>
          <label>Order<select name="order" value={filters.order} onChange={update}><option value="desc">Descending</option><option value="asc">Ascending</option></select></label>
        </div>

        <div className="player-coverage-note">
          Goals and match appearances come from separate source tables. The cards show only values that are actually recorded; appearance numbers are labelled as recorded coverage and are not used to invent missing historical matches.
        </div>

        {error && <ErrorState message={error} />}
        {loading && <LoadingState label="Loading players" />}
        {!loading && !error && !rows.length && <EmptyState label="No players match the selected filters." />}
        {!loading && !error && rows.length > 0 && (
          <>
            <div className="players-results-grid">
              {rows.map((player) => (
                <PlayerCard
                  key={player.player_id}
                  player={player}
                  selected={String(selected) === String(player.player_id)}
                  onSelect={() => setSelected(player.player_id)}
                />
              ))}
            </div>
            <Pagination page={page} limit={25} total={payload?.pagination?.total || 0} onPage={setPage} />
          </>
        )}
      </section>

      <PlayerDetailPanel detail={detail} />
    </div>
  );
}

function PlayerCard({ player, selected, onSelect }) {
  const metrics = [
    { label: "Goals", value: player.goals, always: true },
    { label: "Recorded apps", value: positiveValue(player.appearances) },
    { label: "Recorded starts", value: positiveValue(player.starts) },
    { label: "Sub apps", value: positiveValue(player.substitute_appearances) },
    { label: "Assists", value: positiveValue(player.assists) },
  ].filter((metric) => metric.always || hasValue(metric.value));

  const missingAppearances = Number(player.goals) > 0 && Number(player.appearances) === 0;

  return (
    <button className={`player-record-card ${selected ? "selected" : ""}`} onClick={onSelect}>
      <header className="player-record-head">
        <span className="player-record-avatar">{initials(player.player)}</span>
        <span className="player-record-identity">
          <strong>{player.player}</strong>
          {hasValue(player.preferred_position) && <small>{player.preferred_position}</small>}
        </span>
        <span className="player-record-open">View</span>
      </header>

      <div className="player-record-stats">
        {metrics.map((metric) => (
          <span key={metric.label}>
            <small>{metric.label}</small>
            <strong>{formatNumber(metric.value)}</strong>
          </span>
        ))}
      </div>

      {missingAppearances && (
        <span className="player-record-coverage">Historical goals recorded · appearance details not available</span>
      )}
    </button>
  );
}

function PlayerDetailPanel({ detail }) {
  if (!detail) {
    return <aside className="detail-panel player-detail-card"><span className="eyebrow">PLAYER PROFILE</span><h2>Select a player</h2><p>Open any card to inspect the statistics and match history that are present in the database.</p></aside>;
  }

  const player = detail.profile;
  const metrics = [
    { label: "Goals", value: player.goals },
    { label: "Recorded appearances", value: positiveValue(player.appearances) },
    { label: "Recorded starts", value: positiveValue(player.starts) },
    { label: "Substitute appearances", value: positiveValue(player.substitute_appearances) },
    { label: "Minutes recorded", value: positiveValue(player.minutes_played) },
    { label: "Penalty goals", value: positiveValue(player.penalty_goals) },
    { label: "Assists recorded", value: positiveValue(player.assists) },
  ].filter((metric) => hasValue(metric.value));

  const missingAppearances = Number(player.goals) > 0 && Number(player.appearances) === 0;

  return (
    <aside className="detail-panel player-detail-card">
      <span className="eyebrow">PLAYER PROFILE</span>
      <h2>{player.player}</h2>
      <div className="player-metric-grid">
        {metrics.map((metric) => (
          <div className="player-metric" key={metric.label}>
            <span>{metric.label}</span>
            <strong>{formatNumber(metric.value)}</strong>
          </div>
        ))}
      </div>

      {missingAppearances && (
        <div className="player-coverage-note">The goal events are stored, but no match-by-match appearance rows are available for this historical player. No appearance rate is calculated.</div>
      )}

      <h3>Tournaments</h3>
      {(detail.tournaments || []).length ? (
        <div className="chip-list">
          {detail.tournaments.map((row) => (
            <span key={`${row.year}-${row.team}`}>{row.year} · {row.team} · {formatNumber(row.goals)} goals</span>
          ))}
        </div>
      ) : <p className="empty-history">No tournament participation row is available.</p>}

      <h3>Recorded match history</h3>
      {(detail.match_history || []).length ? (
        <div className="history player-history-list">
          {detail.match_history.slice(0, 8).map((match) => (
            <p key={match.match_id}><b>{match.year}</b><span>{match.home_team} {match.home_score}:{match.away_score} {match.away_team}</span>{Number(match.goals) > 0 && <small>{formatNumber(match.goals)} goals</small>}</p>
          ))}
        </div>
      ) : <p className="empty-history">No recorded match-by-match appearance history is available.</p>}
    </aside>
  );
}

function positiveValue(value) {
  return Number(value) > 0 ? Number(value) : null;
}

function initials(name) {
  return String(name || "")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase();
}
