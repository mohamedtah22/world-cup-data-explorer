import { useEffect, useMemo, useState } from "react";
import DataTable from "../components/DataTable";
import SectionHeading from "../components/SectionHeading";
import Icon from "../components/Icon";
import { ErrorState, LoadingState, EmptyState } from "../components/StateView";
import { api } from "../services/api";
import { formatDate, formatDecimal, formatNumber, hasValue } from "../utils/format";

const tabs = [
  { key: "overview", label: "Overview" },
  { key: "scorers", label: "Top scorers" },
  { key: "matches", label: "Matches" },
  { key: "teams", label: "Teams" },
];

export default function Tournaments() {
  const [editions, setEditions] = useState([]);
  const [selectedYear, setSelectedYear] = useState(null);
  const [detail, setDetail] = useState(null);
  const [activeTab, setActiveTab] = useState("overview");
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setError("");
    api.tournaments()
      .then((data) => {
        setEditions(data);
        if (data.length) setSelectedYear(data[data.length - 1].year);
      })
      .catch((err) => setError(err.message));
  }, []);

  useEffect(() => {
    if (!selectedYear) return;
    setLoadingDetail(true);
    setError("");
    setDetail(null);
    api.tournament(selectedYear)
      .then(setDetail)
      .catch((err) => setError(err.message))
      .finally(() => setLoadingDetail(false));
  }, [selectedYear]);

  const selectedIndex = useMemo(
    () => editions.findIndex((edition) => Number(edition.year) === Number(selectedYear)),
    [editions, selectedYear],
  );
  const editionSummary = editions[selectedIndex] || null;

  function selectYear(year) {
    setSelectedYear(Number(year));
    setActiveTab("overview");
  }

  function move(direction) {
    const nextIndex = selectedIndex + direction;
    if (nextIndex >= 0 && nextIndex < editions.length) selectYear(editions[nextIndex].year);
  }

  if (error && !editions.length) return <ErrorState message={error} />;
  if (!editions.length) return <LoadingState label="Loading World Cup editions" />;

  return (
    <div className="page-stack tournament-page">
      <section className="tournament-selector-panel">
        <div className="selector-copy">
          <span className="eyebrow">TOURNAMENT CENTER</span>
          <h2>Choose a World Cup edition</h2>
          <p>Pick a year to load that tournament&apos;s statistics, teams, scorers, and complete fixture list.</p>
        </div>

        <div className="edition-select-row">
          <button className="edition-arrow" onClick={() => move(-1)} disabled={selectedIndex <= 0} aria-label="Previous edition">
            <Icon name="arrowLeft" size={20} />
          </button>
          <label className="edition-select-control">
            <span>Selected edition</span>
            <select value={selectedYear || ""} onChange={(event) => selectYear(event.target.value)}>
              {editions.map((edition) => (
                <option key={edition.year} value={edition.year}>{edition.year} · {edition.name}</option>
              ))}
            </select>
          </label>
          <button className="edition-arrow" onClick={() => move(1)} disabled={selectedIndex >= editions.length - 1} aria-label="Next edition">
            <Icon name="arrowRight" size={20} />
          </button>
        </div>

        <div className="edition-timeline" role="list" aria-label="World Cup editions">
          {editions.map((edition) => (
            <button
              role="listitem"
              key={edition.year}
              className={Number(selectedYear) === Number(edition.year) ? "active" : ""}
              onClick={() => selectYear(edition.year)}
            >
              <strong>{edition.year}</strong>
              <small>{formatNumber(edition.matches)} matches</small>
            </button>
          ))}
        </div>
      </section>

      {error && <ErrorState message={error} />}
      {loadingDetail && <LoadingState label={`Loading the ${selectedYear} World Cup`} />}
      {!loadingDetail && detail && (
        <TournamentWorkspace
          detail={detail}
          summary={editionSummary}
          activeTab={activeTab}
          setActiveTab={setActiveTab}
        />
      )}
    </div>
  );
}

function TournamentWorkspace({ detail, summary, activeTab, setActiveTab }) {
  const tournament = detail.tournament;
  const goalsPerMatch = summary?.goals_per_match ?? (
    Number(tournament.matches) > 0 ? Number(tournament.goals) / Number(tournament.matches) : null
  );
  const leadingScorer = detail.top_scorers?.[0];

  return (
    <section className="tournament-workspace">
      <article className="tournament-hero">
        <div className="tournament-hero-pattern" aria-hidden="true" />
        <div className="tournament-hero-copy">
          <span className="tournament-kicker">FIFA WORLD CUP</span>
          <div className="tournament-title-row">
            <strong className="tournament-year">{tournament.year}</strong>
            <div>
              <h2>{tournament.name}</h2>
              <p>Every recorded match, participant, and scoring leader for this edition.</p>
            </div>
          </div>
        </div>
        <div className="tournament-hero-stats">
          <HeroStat label="Matches" value={tournament.matches} />
          <HeroStat label="Goals" value={tournament.goals} />
          <HeroStat label="Teams" value={detail.teams?.length} />
          <HeroStat label="Goals / match" value={goalsPerMatch} decimal />
        </div>
      </article>

      <div className="tournament-tabs" role="tablist" aria-label="Tournament sections">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            role="tab"
            aria-selected={activeTab === tab.key}
            className={activeTab === tab.key ? "active" : ""}
            onClick={() => setActiveTab(tab.key)}
          >
            {tab.label}
            {tab.key === "matches" && <span>{detail.matches?.length || 0}</span>}
            {tab.key === "teams" && <span>{detail.teams?.length || 0}</span>}
          </button>
        ))}
      </div>

      <div className="tournament-tab-content">
        {activeTab === "overview" && (
          <TournamentOverview detail={detail} goalsPerMatch={goalsPerMatch} leadingScorer={leadingScorer} />
        )}
        {activeTab === "scorers" && <TournamentScorers rows={detail.top_scorers || []} />}
        {activeTab === "matches" && <TournamentMatches rows={detail.matches || []} />}
        {activeTab === "teams" && <TournamentTeams rows={detail.teams || []} />}
      </div>
    </section>
  );
}

function HeroStat({ label, value, decimal = false }) {
  if (!hasValue(value)) return null;
  return (
    <div>
      <strong>{decimal ? formatDecimal(value, 2) : formatNumber(value)}</strong>
      <span>{label}</span>
    </div>
  );
}

function TournamentOverview({ detail, goalsPerMatch, leadingScorer }) {
  const latestMatches = [...(detail.matches || [])].slice(-6).reverse();
  return (
    <div className="tournament-overview-grid">
      <article className="panel tournament-feature-card">
        <span className="eyebrow">EDITION SNAPSHOT</span>
        <h3>{detail.tournament.year} in numbers</h3>
        <div className="snapshot-grid">
          <Snapshot label="Total goals" value={detail.tournament.goals} note={`${formatDecimal(goalsPerMatch, 2)} per match`} />
          <Snapshot label="Participating teams" value={detail.teams?.length} note="National teams" />
          <Snapshot label="Recorded matches" value={detail.tournament.matches} note="Group and knockout stages" />
          {leadingScorer && <Snapshot label="Leading scorer" value={leadingScorer.player} note={`${leadingScorer.goals} goals · ${leadingScorer.team}`} text />}
        </div>
      </article>

      <article className="panel tournament-feature-card">
        <SectionHeading eyebrow="LEADING PLAYERS" title="Top scorers" description="The five leading scorers in this edition." />
        {detail.top_scorers?.length ? (
          <ol className="premium-rank-list">
            {detail.top_scorers.slice(0, 5).map((row, index) => (
              <li key={`${row.player_id}-${row.team}`}>
                <span className="premium-rank-number">{String(index + 1).padStart(2, "0")}</span>
                <div><strong>{row.player}</strong><small>{row.team}</small></div>
                <b>{row.goals}<small> goals</small></b>
              </li>
            ))}
          </ol>
        ) : <EmptyState label="No scorer data is available for this edition." />}
      </article>

      <article className="panel tournament-feature-card tournament-recent-card">
        <SectionHeading eyebrow="MATCHES" title="Latest fixtures" description="The final six recorded matches from this edition." />
        {latestMatches.length ? (
          <div className="fixture-card-list">
            {latestMatches.map((match) => <FixtureCard key={match.match_id} match={match} />)}
          </div>
        ) : <EmptyState label="No matches were found for this edition." />}
      </article>
    </div>
  );
}

function Snapshot({ label, value, note, text = false }) {
  if (!hasValue(value)) return null;
  return (
    <div className={text ? "snapshot-card text-value" : "snapshot-card"}>
      <span>{label}</span>
      <strong>{text ? value : formatNumber(value)}</strong>
      <small>{note}</small>
    </div>
  );
}

function FixtureCard({ match }) {
  return (
    <div className="fixture-card">
      <div className="fixture-meta"><span>{formatDate(match.match_date)}</span><small>{match.stage}</small></div>
      <div className="fixture-scoreline">
        <strong>{match.home_team}</strong>
        <span>{match.home_score ?? "–"}<b>:</b>{match.away_score ?? "–"}</span>
        <strong>{match.away_team}</strong>
      </div>
      {(hasValue(match.stadium) || hasValue(match.city)) && <small className="fixture-venue">{[match.stadium, match.city].filter(Boolean).join(" · ")}</small>}
    </div>
  );
}

function TournamentScorers({ rows }) {
  if (!rows.length) return <EmptyState label="No scorer data is available for this edition." />;
  return (
    <article className="panel tournament-full-panel">
      <SectionHeading eyebrow="SCORING TABLE" title="Top scorers" description="Players ranked by non-own-goal tournament goals." />
      <div className="scorer-podium">
        {rows.slice(0, 3).map((row, index) => (
          <article key={`${row.player_id}-${row.team}`} className={`podium-card podium-${index + 1}`}>
            <span>#{index + 1}</span>
            <strong>{row.player}</strong>
            <small>{row.team}</small>
            <b>{row.goals} goals</b>
          </article>
        ))}
      </div>
      {rows.length > 3 && (
        <ol className="premium-rank-list extended-rank-list">
          {rows.slice(3).map((row, index) => (
            <li key={`${row.player_id}-${row.team}`}>
              <span className="premium-rank-number">{String(index + 4).padStart(2, "0")}</span>
              <div><strong>{row.player}</strong><small>{row.team}</small></div>
              <b>{row.goals}<small> goals</small></b>
            </li>
          ))}
        </ol>
      )}
    </article>
  );
}

function TournamentMatches({ rows }) {
  const columns = [
    { key: "match_date", label: "Date", render: (row) => formatDate(row.match_date) },
    { key: "stage", label: "Stage", render: (row) => <span className="soft-badge">{row.stage}</span> },
    { key: "home_team", label: "Home" },
    { key: "score", label: "Score", render: (row) => <span className="score-pill">{row.home_score ?? "–"}<b>:</b>{row.away_score ?? "–"}</span> },
    { key: "away_team", label: "Away" },
    {
      key: "venue",
      label: "Venue",
      optional: true,
      isAvailable: (row) => hasValue(row.stadium) || hasValue(row.city),
      render: (row) => <span className="venue-cell">{row.stadium}{row.stadium && row.city ? <small>{row.city}</small> : row.city}</span>,
    },
  ];
  return (
    <article className="panel tournament-full-panel">
      <SectionHeading eyebrow="FIXTURE LIST" title="All matches" description={`${rows.length} recorded matches in this edition.`} />
      <DataTable columns={columns} rows={rows} getKey={(row) => row.match_id} emptyLabel="No matches were found for this edition." />
    </article>
  );
}

function TournamentTeams({ rows }) {
  if (!rows.length) return <EmptyState label="No participating teams were found." />;
  return (
    <article className="panel tournament-full-panel">
      <SectionHeading eyebrow="PARTICIPANTS" title="National teams" description={`${rows.length} teams represented in the match archive.`} />
      <div className="premium-team-grid">
        {rows.map((team, index) => (
          <div key={team.team_id}>
            <span>{String(index + 1).padStart(2, "0")}</span>
            <strong>{team.team}</strong>
          </div>
        ))}
      </div>
    </article>
  );
}
