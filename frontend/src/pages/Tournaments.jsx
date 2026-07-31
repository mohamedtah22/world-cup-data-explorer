import { useEffect, useMemo, useState } from "react";
import DataTable from "../components/DataTable";
import SectionHeading from "../components/SectionHeading";
import Icon from "../components/Icon";
import { ErrorState, LoadingState, EmptyState } from "../components/StateView";
import { api } from "../services/api";
import { formatDate, formatDecimal, formatNumber, hasValue } from "../utils/format";
import "../responsive-fixes.css";

const tabs = [
  { key: "overview", label: "Overview" },
  { key: "groups", label: "Group stage" },
  { key: "bracket", label: "Knockout bracket" },
  { key: "scorers", label: "Top scorers" },
  { key: "matches", label: "All matches" },
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
          <p>Open one edition, inspect every group table, and follow its knockout path round by round.</p>
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
  const groupData = useMemo(() => buildGroups(detail.matches || []), [detail.matches]);
  const bracketData = useMemo(() => buildBracket(detail.matches || []), [detail.matches]);

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
              <p>Group standings, knockout rounds, scorers, teams, and the complete match archive.</p>
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
            {tab.key === "groups" && groupData.length > 0 && <span>{groupData.length}</span>}
            {tab.key === "bracket" && bracketData.rounds.length > 0 && <span>{bracketData.rounds.length}</span>}
            {tab.key === "matches" && <span>{detail.matches?.length || 0}</span>}
            {tab.key === "teams" && <span>{detail.teams?.length || 0}</span>}
          </button>
        ))}
      </div>

      <div className="tournament-tab-content">
        {activeTab === "overview" && (
          <TournamentOverview detail={detail} goalsPerMatch={goalsPerMatch} leadingScorer={leadingScorer} groupCount={groupData.length} roundCount={bracketData.rounds.length} />
        )}
        {activeTab === "groups" && <TournamentGroups groups={groupData} />}
        {activeTab === "bracket" && <TournamentBracket data={bracketData} />}
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

function TournamentOverview({ detail, goalsPerMatch, leadingScorer, groupCount, roundCount }) {
  const latestMatches = [...(detail.matches || [])].slice(-6).reverse();
  return (
    <div className="tournament-overview-grid">
      <article className="panel tournament-feature-card">
        <span className="eyebrow">EDITION SNAPSHOT</span>
        <h3>{detail.tournament.year} in numbers</h3>
        <div className="snapshot-grid">
          <Snapshot label="Total goals" value={detail.tournament.goals} note={`${formatDecimal(goalsPerMatch, 2)} per match`} />
          <Snapshot label="Participating teams" value={detail.teams?.length} note="National teams" />
          <Snapshot label="Group tables" value={groupCount} note={groupCount ? "Calculated from match results" : "No separate groups recorded"} />
          <Snapshot label="Knockout rounds" value={roundCount} note={roundCount ? "Displayed as a bracket" : "No knockout rounds recorded"} />
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
      <div className="fixture-meta"><span>{formatDate(match.match_date)}</span><small>{match.group_name || match.stage}</small></div>
      <div className="fixture-scoreline">
        <strong>{match.home_team}</strong>
        <span>{match.home_score ?? "–"}<b>:</b>{match.away_score ?? "–"}</span>
        <strong>{match.away_team}</strong>
      </div>
      {(hasValue(match.stadium) || hasValue(match.city)) && <small className="fixture-venue">{[match.stadium, match.city].filter(Boolean).join(" · ")}</small>}
    </div>
  );
}

function TournamentGroups({ groups }) {
  if (!groups.length) {
    return <EmptyState label="This edition has no separately recorded group stage. Older World Cups used different tournament formats." />;
  }

  return (
    <section className="group-stage-section">
      <SectionHeading eyebrow="GROUP STAGE" title="Standings and fixtures" description="Tables are calculated directly from the recorded group-match scores: three points for a win and one for a draw." />
      <div className="groups-grid">
        {groups.map((group) => (
          <article className="group-card" key={group.name}>
            <header className="group-card-header">
              <div><span>GROUP</span><h3>{cleanGroupName(group.name)}</h3></div>
              <small>{group.matches.length} matches</small>
            </header>
            <div className="group-table-wrap">
              <table className="group-table">
                <thead><tr><th>#</th><th>Team</th><th>P</th><th>W</th><th>D</th><th>L</th><th>GD</th><th>Pts</th></tr></thead>
                <tbody>
                  {group.standings.map((team, index) => (
                    <tr key={team.team} className={index < 2 ? "qualification-row" : ""}>
                      <td><span className="group-position">{index + 1}</span></td>
                      <td><strong>{team.team}</strong></td>
                      <td>{team.played}</td><td>{team.wins}</td><td>{team.draws}</td><td>{team.losses}</td>
                      <td className={team.goalDifference > 0 ? "positive-stat" : team.goalDifference < 0 ? "negative-stat" : ""}>{team.goalDifference > 0 ? "+" : ""}{team.goalDifference}</td>
                      <td><b>{team.points}</b></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="group-fixtures">
              {group.matches.map((match) => (
                <div className="group-fixture" key={match.match_id}>
                  <small>{formatDate(match.match_date)}</small>
                  <span>{match.home_team}</span>
                  <b>{match.home_score ?? "–"} : {match.away_score ?? "–"}</b>
                  <span>{match.away_team}</span>
                </div>
              ))}
            </div>
          </article>
        ))}
      </div>
      <p className="standings-note">Teams are ordered by points, then goal difference, then goals scored. This is a visual calculation from the available match data and does not add or modify database rows.</p>
    </section>
  );
}

function TournamentBracket({ data }) {
  if (!data.rounds.length) {
    return <EmptyState label="This edition has no separately recorded knockout bracket. Its historical format may have ended with a final group." />;
  }

  return (
    <section className="knockout-section">
      <SectionHeading eyebrow="KNOCKOUT STAGE" title="Road to the final" description="Each column represents one recorded knockout round. Scroll horizontally on a phone." />
      <div className="bracket-scroll">
        <div className="bracket-grid" style={{ gridTemplateColumns: `repeat(${data.rounds.length}, minmax(220px, 1fr))` }}>
          {data.rounds.map((round) => (
            <section className="bracket-round" key={round.key}>
              <header><span>{round.matches.length} matches</span><h3>{round.label}</h3></header>
              <div className="bracket-round-matches">
                {round.matches.map((match) => <BracketMatch key={match.match_id} match={match} />)}
              </div>
            </section>
          ))}
        </div>
      </div>

      {data.thirdPlace.length > 0 && (
        <article className="third-place-panel">
          <div><span className="eyebrow">PLACEMENT MATCH</span><h3>Third-place play-off</h3></div>
          <div className="third-place-matches">{data.thirdPlace.map((match) => <BracketMatch key={match.match_id} match={match} compact />)}</div>
        </article>
      )}
    </section>
  );
}

function BracketMatch({ match, compact = false }) {
  const winner = getWinner(match);
  return (
    <article className={compact ? "bracket-match compact" : "bracket-match"}>
      <div className="bracket-match-meta"><span>{formatDate(match.match_date)}</span>{match.city && <small>{match.city}</small>}</div>
      <div className={winner === "home" ? "bracket-team winner" : "bracket-team"}><span>{match.home_team}</span><b>{match.home_score ?? "–"}</b></div>
      <div className={winner === "away" ? "bracket-team winner" : "bracket-team"}><span>{match.away_team}</span><b>{match.away_score ?? "–"}</b></div>
    </article>
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
    { key: "stage", label: "Stage", render: (row) => <span className="soft-badge">{row.group_name || row.stage}</span> },
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

function buildGroups(matches) {
  const grouped = new Map();
  matches.forEach((match) => {
    const groupName = hasValue(match.group_name)
      ? String(match.group_name).trim()
      : isGroupStage(match.stage) ? String(match.stage).trim() : null;
    if (!groupName) return;
    if (!grouped.has(groupName)) grouped.set(groupName, []);
    grouped.get(groupName).push(match);
  });

  return [...grouped.entries()]
    .sort(([left], [right]) => left.localeCompare(right, undefined, { numeric: true }))
    .map(([name, groupMatches]) => ({
      name,
      matches: [...groupMatches].sort(sortMatches),
      standings: calculateStandings(groupMatches),
    }));
}

function calculateStandings(matches) {
  const table = new Map();
  function getTeam(name) {
    if (!table.has(name)) table.set(name, { team: name, played: 0, wins: 0, draws: 0, losses: 0, goalsFor: 0, goalsAgainst: 0, goalDifference: 0, points: 0 });
    return table.get(name);
  }

  matches.forEach((match) => {
    const home = getTeam(match.home_team);
    const away = getTeam(match.away_team);
    const homeScore = Number(match.home_score);
    const awayScore = Number(match.away_score);
    if (!Number.isFinite(homeScore) || !Number.isFinite(awayScore)) return;

    home.played += 1; away.played += 1;
    home.goalsFor += homeScore; home.goalsAgainst += awayScore;
    away.goalsFor += awayScore; away.goalsAgainst += homeScore;
    if (homeScore > awayScore) { home.wins += 1; home.points += 3; away.losses += 1; }
    else if (awayScore > homeScore) { away.wins += 1; away.points += 3; home.losses += 1; }
    else { home.draws += 1; away.draws += 1; home.points += 1; away.points += 1; }
  });

  return [...table.values()]
    .map((team) => ({ ...team, goalDifference: team.goalsFor - team.goalsAgainst }))
    .sort((left, right) => right.points - left.points || right.goalDifference - left.goalDifference || right.goalsFor - left.goalsFor || left.team.localeCompare(right.team));
}

function buildBracket(matches) {
  const stages = new Map();
  const thirdPlace = [];

  matches.forEach((match) => {
    if (hasValue(match.group_name) || isGroupStage(match.stage)) return;
    const stage = classifyKnockoutStage(match.stage);
    if (!stage) return;
    if (stage.key === "third-place") {
      thirdPlace.push(match);
      return;
    }
    if (!stages.has(stage.key)) stages.set(stage.key, { ...stage, matches: [] });
    stages.get(stage.key).matches.push(match);
  });

  const rounds = [...stages.values()]
    .map((round) => ({ ...round, matches: round.matches.sort(sortMatches) }))
    .sort((left, right) => left.order - right.order);
  return { rounds, thirdPlace: thirdPlace.sort(sortMatches) };
}

function classifyKnockoutStage(stageValue) {
  const raw = String(stageValue || "").trim();
  if (!raw) return null;
  const stage = raw.toLowerCase().replace(/[–—]/g, "-");
  if (stage.includes("third") || stage.includes("3rd")) return { key: "third-place", label: "Third place", order: 90 };
  if (stage.includes("round of 32") || stage.includes("last 32")) return { key: "round-32", label: "Round of 32", order: 10 };
  if (stage.includes("round of 16") || stage.includes("last 16") || stage.includes("eighth")) return { key: "round-16", label: "Round of 16", order: 20 };
  if (stage.includes("quarter")) return { key: "quarter-final", label: "Quarter-finals", order: 30 };
  if (stage.includes("semi")) return { key: "semi-final", label: "Semi-finals", order: 40 };
  if (stage === "final" || (stage.includes("final") && !stage.includes("group"))) return { key: "final", label: "Final", order: 50 };
  if (stage.includes("knockout") || stage.includes("play-off") || stage.includes("playoff")) return { key: stage, label: raw, order: 25 };
  return null;
}

function isGroupStage(stageValue) {
  const stage = String(stageValue || "").toLowerCase();
  return stage.includes("group") || stage.includes("pool");
}

function getWinner(match) {
  const home = Number(match.home_score);
  const away = Number(match.away_score);
  if (!Number.isFinite(home) || !Number.isFinite(away) || home === away) return null;
  return home > away ? "home" : "away";
}

function cleanGroupName(name) {
  return String(name).replace(/^group\s*/i, "").trim() || name;
}

function sortMatches(left, right) {
  return String(left.match_date || "").localeCompare(String(right.match_date || "")) || Number(left.match_id) - Number(right.match_id);
}
