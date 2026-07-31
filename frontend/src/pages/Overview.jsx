import { useEffect, useState } from "react";
import { api } from "../services/api";
import { ErrorState, LoadingState } from "../components/StateView";
import Icon from "../components/Icon";
import SectionHeading from "../components/SectionHeading";
import { formatNumber, hasValue } from "../utils/format";

export default function Overview() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  function load() {
    setError("");
    setData(null);
    api.dashboard().then(setData).catch((err) => setError(err.message));
  }

  useEffect(load, []);

  if (error) return <ErrorState message={error} onRetry={load} />;
  if (!data) return <LoadingState label="Loading the World Cup archive" />;

  const counts = data.counts || {};
  const tournamentGoals = data.goals_by_tournament || [];
  const maxGoals = Math.max(...tournamentGoals.map((row) => Number(row.goals) || 0), 1);
  const topScorer = data.player_highlights?.top_scorer;
  const appearances = data.player_highlights?.most_appearances;
  const singleEdition = data.player_highlights?.most_goals_one_tournament;

  return (
    <div className="page-stack overview-page">
      <section className="home-hero">
        <div className="home-hero-grid" aria-hidden="true" />
        <div className="home-hero-copy">
          <span className="hero-label"><span className="status-dot" /> LIVE RELATIONAL ARCHIVE</span>
          <h2>Every tournament.<br /><em>Every era.</em></h2>
          <p>Explore nearly a century of World Cup matches, players, teams, goals, venues, and tournament records through one connected PostgreSQL database.</p>
          <div className="hero-actions">
            <a href="#tournaments" className="primary-action">Explore tournaments <Icon name="arrowRight" size={17} /></a>
            <a href="#leaderboards" className="secondary-action">View all-time records</a>
          </div>
        </div>
        <div className="hero-record-card">
          <span className="eyebrow">ALL-TIME TOP SCORER</span>
          <div className="record-number">{topScorer?.goals ?? "—"}</div>
          <h3>{topScorer?.player || "World Cup archive"}</h3>
          <p>{topScorer ? "recorded tournament goals" : "Loading record"}</p>
          <div className="record-ball" aria-hidden="true"><Icon name="goal" size={42} /></div>
        </div>
      </section>

      <section className="home-kpi-grid">
        <Kpi label="World Cups" value={counts.tournament_count} icon="tournaments" note="1930—2026" />
        <Kpi label="Matches" value={counts.match_count} icon="matches" note="Complete fixture archive" />
        <Kpi label="Goals" value={counts.goal_count} icon="goal" note="Linked to matches and players" />
        <Kpi label="Players" value={counts.player_count} icon="players" note="Canonical identities" />
        <Kpi label="National teams" value={counts.team_count} icon="teams" note="Historical aliases resolved" />
        <Kpi label="Player appearances" value={counts.player_appearance_count} icon="database" note="Across all editions" />
      </section>

      <section className="home-main-grid">
        <article className="panel goals-chart-panel">
          <SectionHeading eyebrow="TOURNAMENT TREND" title="Goals by edition" description="The scoring total for every World Cup in the archive." />
          <div className="modern-bar-chart" aria-label="Goals by tournament">
            {tournamentGoals.map((row) => (
              <div key={row.year} className="modern-bar-column" title={`${row.year}: ${row.goals} goals`}>
                <span className="modern-bar-value">{row.goals}</span>
                <div className="modern-bar-track">
                  <i style={{ height: `${Math.max(8, (Number(row.goals) / maxGoals) * 100)}%` }} />
                </div>
                <small>{String(row.year).slice(2)}</small>
              </div>
            ))}
          </div>
          <div className="chart-axis"><span>1930</span><span>World Cup editions</span><span>2026</span></div>
        </article>

        <article className="panel record-highlights-panel">
          <SectionHeading eyebrow="DATABASE HIGHLIGHTS" title="Records at a glance" />
          <div className="record-highlight-list">
            {topScorer && <RecordHighlight number={topScorer.goals} label="All-time goals" name={topScorer.player} />}
            {appearances && <RecordHighlight number={appearances.appearances} label="Most appearances" name={appearances.player} />}
            {singleEdition && <RecordHighlight number={singleEdition.goals} label={`Goals in ${singleEdition.year}`} name={singleEdition.player} />}
          </div>
        </article>
      </section>

      <section className="home-rank-grid">
        <RankPanel title="Most wins" eyebrow="NATIONAL TEAMS" rows={data.teams_with_most_wins} nameKey="team" valueKey="wins" valueSuffix="wins" />
        <RankPanel title="All-time scorers" eyebrow="PLAYERS" rows={data.top_scorers} nameKey="player" valueKey="goals" subKey="team" valueSuffix="goals" />
        <RankPanel title="Most-used venues" eyebrow="STADIUMS" rows={data.stadiums_with_most_matches} nameKey="name" valueKey="matches" subKey="city" valueSuffix="matches" />
      </section>
    </div>
  );
}

function Kpi({ label, value, icon, note }) {
  return (
    <article className="home-kpi-card">
      <div className="home-kpi-icon"><Icon name={icon} size={21} /></div>
      <div>
        <span>{label}</span>
        <strong>{formatNumber(value || 0)}</strong>
        <small>{note}</small>
      </div>
    </article>
  );
}

function RecordHighlight({ number, label, name }) {
  return (
    <div>
      <strong>{formatNumber(number)}</strong>
      <span>{label}</span>
      <small>{name}</small>
    </div>
  );
}

function RankPanel({ title, eyebrow, rows = [], nameKey, valueKey, subKey, valueSuffix }) {
  const visibleRows = rows.filter((row) => hasValue(row[nameKey]) && hasValue(row[valueKey])).slice(0, 7);
  if (!visibleRows.length) return null;

  return (
    <article className="panel premium-rank-panel">
      <SectionHeading eyebrow={eyebrow} title={title} />
      <ol className="premium-rank-list">
        {visibleRows.map((row, index) => (
          <li key={`${title}-${row[nameKey]}-${row[valueKey]}`}>
            <span className="premium-rank-number">{String(index + 1).padStart(2, "0")}</span>
            <div>
              <strong>{row[nameKey]}</strong>
              {subKey && hasValue(row[subKey]) && <small>{row[subKey]}</small>}
            </div>
            <b>{formatNumber(row[valueKey])}<small> {valueSuffix}</small></b>
          </li>
        ))}
      </ol>
    </article>
  );
}
