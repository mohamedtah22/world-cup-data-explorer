import { useEffect, useMemo, useState } from "react";
import { EmptyState, ErrorState, LoadingState } from "../components/StateView";
import { api } from "../services/api";
import { formatDecimal, formatNumber, hasValue } from "../utils/format";
import "../leaderboards.css";

const boardDefinitions = [
  { key: "goals", title: "Top scorers", description: "All-time non-own-goal totals", value: "goals", unit: "goals", format: formatNumber },
  { key: "appearances", title: "Most appearances", description: "Recorded World Cup match appearances", value: "appearances", unit: "apps", format: formatNumber },
  { key: "starts", title: "Most starts", description: "Recorded starts in the available sources", value: "starts", unit: "starts", format: formatNumber },
  { key: "substitute_appearances", title: "Most substitute appearances", description: "Recorded appearances from the bench", value: "substitute_appearances", unit: "sub apps", format: formatNumber },
  { key: "minutes_played", title: "Most minutes", description: "Shown only where minute data is recorded", value: "minutes_played", unit: "min", format: formatNumber },
  { key: "goals_per_match", title: "Goals per match", description: "Requires the selected minimum appearances", value: "goals_per_match", unit: "per match", format: (value) => formatDecimal(value, 3) },
  { key: "assists", title: "Most assists", description: "Shown only where assist data is recorded", value: "assists", unit: "assists", format: formatNumber },
];

export default function PlayerLeaderboards() {
  const [minimum, setMinimum] = useState(5);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setError("");
    setData(null);
    api.playerLeaderboards({ minimum_appearances: minimum })
      .then(setData)
      .catch((err) => setError(err.message));
  }, [minimum]);

  const visibleBoards = useMemo(() => {
    if (!data) return [];
    return boardDefinitions
      .map((board) => ({
        ...board,
        rows: sanitizeRows(data[board.key], board.value),
      }))
      .filter((board) => board.rows.length > 0);
  }, [data]);

  if (error) return <ErrorState message={error} />;
  if (!data) return <LoadingState label="Loading player leaderboards" />;

  return (
    <div className="page-stack leaderboards-page">
      <section className="leaderboard-toolbar">
        <div>
          <span className="eyebrow">RECORDED VALUES ONLY</span>
          <h2>World Cup player records</h2>
          <p>Missing values are removed rather than displayed as N/A. A leaderboard is hidden when its source contains no usable values.</p>
        </div>
        <label className="leaderboard-minimum-control">
          <span>Minimum appearances for rate rankings</span>
          <input
            type="number"
            min="1"
            max="100"
            value={minimum}
            onChange={(event) => setMinimum(clampMinimum(event.target.value))}
            inputMode="numeric"
          />
        </label>
      </section>

      {visibleBoards.length ? (
        <div className="leaderboards-grid">
          {visibleBoards.map((board) => <Board key={board.key} {...board} />)}
        </div>
      ) : (
        <EmptyState label="No leaderboard contains recorded values for the selected filters." />
      )}
    </div>
  );
}

function sanitizeRows(rows, valueKey) {
  return (Array.isArray(rows) ? rows : [])
    .filter((row) => hasValue(row?.[valueKey]))
    .filter((row) => {
      const value = Number(row[valueKey]);
      return Number.isFinite(value) && value > 0;
    })
    .slice(0, 10);
}

function clampMinimum(rawValue) {
  const value = Number(rawValue);
  if (!Number.isFinite(value)) return 5;
  return Math.min(100, Math.max(1, Math.trunc(value)));
}

function Board({ title, description, rows, value, unit, format }) {
  const rankedRows = addDenseRanks(rows, value);
  const leader = rankedRows[0];

  return (
    <article className="leaderboard-card">
      <header className="leaderboard-card-header">
        <div>
          <span className="leaderboard-kicker">TOP {rows.length}</span>
          <h3>{title}</h3>
          <p>{description}</p>
        </div>
        <div className="leaderboard-leader-value">
          <strong>{format(leader[value])}</strong>
          <span>{unit}</span>
        </div>
      </header>

      <ol className="leaderboard-list">
        {rankedRows.map((row, index) => (
          <li key={`${title}-${row.player_id}`} className={index < 3 ? `leaderboard-top leaderboard-top-${index + 1}` : ""}>
            <span className="leaderboard-rank">{String(row.rank).padStart(2, "0")}</span>
            <span className="leaderboard-player">
              <strong>{row.player}</strong>
              {index === 0 && <small>Leader</small>}
            </span>
            <span className="leaderboard-value">
              <strong>{format(row[value])}</strong>
              <small>{unit}</small>
            </span>
          </li>
        ))}
      </ol>
    </article>
  );
}

function addDenseRanks(rows, valueKey) {
  let rank = 0;
  let previousValue = null;
  return rows.map((row) => {
    const currentValue = Number(row[valueKey]);
    if (previousValue === null || currentValue !== previousValue) rank += 1;
    previousValue = currentValue;
    return { ...row, rank };
  });
}
