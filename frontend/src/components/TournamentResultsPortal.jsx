import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../services/api";
import { formatNumber, hasValue } from "../utils/format";
import "../tournament-results.css";

const FINAL_SHOOTOUT_WINNERS = {
  1994: "Brazil",
  2006: "Italy",
  2022: "Argentina",
};

export default function TournamentResultsPortal() {
  const [target, setTarget] = useState(null);
  const [year, setYear] = useState(null);
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    function syncPortal() {
      const workspace = document.querySelector(".tournament-workspace");
      const select = document.querySelector(".edition-select-control select");
      const selectedYear = Number(select?.value);

      if (Number.isFinite(selectedYear)) {
        setYear((current) => current === selectedYear ? current : selectedYear);
      }

      if (!workspace) {
        setTarget(null);
        return;
      }

      let slot = workspace.querySelector(":scope > .tournament-results-portal-slot");
      if (!slot) {
        slot = document.createElement("div");
        slot.className = "tournament-results-portal-slot";
        const tabs = workspace.querySelector(":scope > .tournament-tabs");
        workspace.insertBefore(slot, tabs || null);
      }
      setTarget((current) => current === slot ? current : slot);
    }

    const observer = new MutationObserver(syncPortal);
    observer.observe(document.body, { childList: true, subtree: true });
    document.addEventListener("change", syncPortal, true);
    syncPortal();

    return () => {
      observer.disconnect();
      document.removeEventListener("change", syncPortal, true);
    };
  }, []);

  useEffect(() => {
    if (!year) return;
    let cancelled = false;
    setDetail(null);
    setError("");
    api.tournament(year)
      .then((payload) => {
        if (!cancelled) setDetail(payload);
      })
      .catch((requestError) => {
        if (!cancelled) setError(requestError.message);
      });
    return () => {
      cancelled = true;
    };
  }, [year]);

  if (!target) return null;
  return createPortal(
    <TournamentResultsPanel year={year} detail={detail} error={error} />,
    target,
  );
}

function TournamentResultsPanel({ year, detail, error }) {
  const result = useMemo(
    () => detail ? buildTournamentResult(Number(year), detail.matches || [], detail.teams || []) : null,
    [year, detail],
  );

  if (error) {
    return <section className="tournament-results-error">Tournament result data could not be calculated.</section>;
  }
  if (!detail || !result) {
    return <section className="tournament-results-loading"><span /> Calculating champion and final ranking…</section>;
  }

  return (
    <section className="tournament-results-section">
      <header className="tournament-results-heading">
        <div>
          <span className="eyebrow">FINAL RESULT</span>
          <h2>{year} champion and tournament ranking</h2>
          <p>{result.explanation}</p>
        </div>
        <div className="champion-badge">
          <span>CHAMPION</span>
          <strong>{result.placements[0]?.team || "Pending"}</strong>
        </div>
      </header>

      <div className="tournament-podium" aria-label={`${year} final top four`}>
        {result.placements.slice(0, 4).map((entry) => (
          <article key={`${entry.position}-${entry.team}`} className={`tournament-place tournament-place-${entry.position}`}>
            <span className="place-number">{entry.position}</span>
            <div>
              <small>{entry.label}</small>
              <strong>{entry.team}</strong>
              <span>{entry.note}</span>
            </div>
          </article>
        ))}
      </div>

      <article className="tournament-ranking-card">
        <div className="tournament-ranking-title">
          <div>
            <span className="eyebrow">COMPLETE TABLE</span>
            <h3>Final tournament ranking</h3>
          </div>
          <small>{result.ranking.length} teams</small>
        </div>
        <div className="tournament-ranking-scroll">
          <table className="tournament-ranking-table">
            <thead>
              <tr>
                <th>#</th><th>Team</th><th>Result</th><th>P</th><th>W</th><th>D</th><th>L</th><th>GF</th><th>GA</th><th>GD</th><th>Pts</th>
              </tr>
            </thead>
            <tbody>
              {result.ranking.map((team) => (
                <tr key={team.team} className={team.position <= 4 ? `ranking-finalist ranking-finalist-${team.position}` : ""}>
                  <td><span className="ranking-position">{team.position}</span></td>
                  <td><strong>{team.team}</strong></td>
                  <td><span className="ranking-stage">{team.resultLabel}</span></td>
                  <td>{team.played}</td><td>{team.wins}</td><td>{team.draws}</td><td>{team.losses}</td>
                  <td>{team.goalsFor}</td><td>{team.goalsAgainst}</td>
                  <td className={team.goalDifference > 0 ? "positive-stat" : team.goalDifference < 0 ? "negative-stat" : ""}>
                    {team.goalDifference > 0 ? "+" : ""}{team.goalDifference}
                  </td>
                  <td><b>{team.points}</b></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="tournament-ranking-note">
          Places 1–4 are taken from the final, the final-round table, and the third-place match where available. Remaining teams are ordered by the furthest recorded stage, then points, goal difference, and goals scored. Points use the rule of the edition: two for a win before 1994 and three from 1994 onward.
        </p>
      </article>
    </section>
  );
}

function buildTournamentResult(year, matches, teams) {
  const completeMatches = matches.filter(hasScore);
  if (!completeMatches.length) return null;

  const stats = calculateTeamStats(year, completeMatches, teams);
  let placements = year === 1950
    ? placementsFromFinalGroup(year, completeMatches)
    : placementsFromKnockout(year, completeMatches, stats);

  placements = placements.filter((entry, index, rows) => entry?.team && rows.findIndex((item) => item.team === entry.team) === index);
  const placementByTeam = new Map(placements.map((entry) => [entry.team, entry]));

  const ranking = [...stats.values()]
    .map((team) => {
      const placement = placementByTeam.get(team.team);
      return {
        ...team,
        fixedPosition: placement?.position || null,
        resultLabel: placement?.label || stageLabel(team.bestStage),
      };
    })
    .sort((left, right) => {
      if (left.fixedPosition && right.fixedPosition) return left.fixedPosition - right.fixedPosition;
      if (left.fixedPosition) return -1;
      if (right.fixedPosition) return 1;
      return right.stageScore - left.stageScore
        || right.points - left.points
        || right.goalDifference - left.goalDifference
        || right.goalsFor - left.goalsFor
        || left.team.localeCompare(right.team);
    })
    .map((team, index) => ({ ...team, position: index + 1 }));

  return {
    placements,
    ranking,
    explanation: year === 1950
      ? "The 1950 champion was decided by the final-round group table rather than a separate final match."
      : "The champion and runner-up come from the recorded final; third and fourth come from the placement match when it exists.",
  };
}

function placementsFromFinalGroup(year, matches) {
  const finalGroupMatches = matches.filter((match) => {
    const stage = normalizeStage(`${match.stage || ""} ${match.group_name || ""}`);
    return stage.includes("final") && (stage.includes("group") || stage.includes("round") || stage.includes("pool"));
  });
  const table = [...calculateTeamStats(year, finalGroupMatches, []).values()]
    .sort(comparePerformance);
  return table.slice(0, 4).map((team, index) => ({
    position: index + 1,
    team: team.team,
    label: ["Champion", "Runner-up", "Third place", "Fourth place"][index],
    note: "Final-round table",
  }));
}

function placementsFromKnockout(year, matches, stats) {
  const finalMatch = [...matches]
    .filter((match) => isFinalMatch(match))
    .sort(sortMatches)
    .at(-1);
  if (!finalMatch) return [];

  const champion = winnerTeam(finalMatch, year);
  const runnerUp = champion === finalMatch.home_team ? finalMatch.away_team : finalMatch.home_team;
  const placements = [
    { position: 1, team: champion, label: "Champion", note: finalMatchNote(finalMatch, year) },
    { position: 2, team: runnerUp, label: "Runner-up", note: "Finalist" },
  ];

  const thirdPlaceMatch = [...matches]
    .filter(isThirdPlaceMatch)
    .sort(sortMatches)
    .at(-1);
  if (thirdPlaceMatch) {
    const third = winnerTeam(thirdPlaceMatch, year);
    const fourth = third === thirdPlaceMatch.home_team ? thirdPlaceMatch.away_team : thirdPlaceMatch.home_team;
    placements.push(
      { position: 3, team: third, label: "Third place", note: "Won third-place match" },
      { position: 4, team: fourth, label: "Fourth place", note: "Third-place finalist" },
    );
    return placements;
  }

  const finalTeams = new Set([finalMatch.home_team, finalMatch.away_team]);
  const semiFinalists = new Set();
  matches.filter(isSemiFinalMatch).forEach((match) => {
    semiFinalists.add(match.home_team);
    semiFinalists.add(match.away_team);
  });
  const losingSemiFinalists = [...semiFinalists]
    .filter((team) => !finalTeams.has(team))
    .map((team) => stats.get(team))
    .filter(Boolean)
    .sort(comparePerformance);

  losingSemiFinalists.slice(0, 2).forEach((team, index) => {
    placements.push({
      position: index + 3,
      team: team.team,
      label: index === 0 ? "Third place" : "Fourth place",
      note: "Semi-finalist",
    });
  });
  return placements;
}

function calculateTeamStats(year, matches, teams) {
  const table = new Map();
  const winPoints = year >= 1994 ? 3 : 2;

  function teamRow(name) {
    if (!table.has(name)) {
      table.set(name, {
        team: name, played: 0, wins: 0, draws: 0, losses: 0,
        goalsFor: 0, goalsAgainst: 0, goalDifference: 0, points: 0,
        bestStage: "participant", stageScore: 0,
      });
    }
    return table.get(name);
  }

  teams.forEach((team) => teamRow(team.team));
  matches.forEach((match) => {
    const home = teamRow(match.home_team);
    const away = teamRow(match.away_team);
    const homeScore = Number(match.home_score);
    const awayScore = Number(match.away_score);
    const stage = classifyStage(match);

    home.played += 1; away.played += 1;
    home.goalsFor += homeScore; home.goalsAgainst += awayScore;
    away.goalsFor += awayScore; away.goalsAgainst += homeScore;
    if (homeScore > awayScore) {
      home.wins += 1; home.points += winPoints; away.losses += 1;
    } else if (awayScore > homeScore) {
      away.wins += 1; away.points += winPoints; home.losses += 1;
    } else {
      home.draws += 1; away.draws += 1; home.points += 1; away.points += 1;
    }

    [home, away].forEach((team) => {
      if (stage.score > team.stageScore) {
        team.stageScore = stage.score;
        team.bestStage = stage.key;
      }
    });
  });

  table.forEach((team) => {
    team.goalDifference = team.goalsFor - team.goalsAgainst;
  });
  return table;
}

function classifyStage(match) {
  const stage = normalizeStage(`${match.stage || ""} ${match.group_name || ""}`);
  if (isFinalMatch(match)) return { key: "final", score: 900 };
  if (isThirdPlaceMatch(match)) return { key: "third-place", score: 780 };
  if (stage.includes("semi")) return { key: "semi-final", score: 700 };
  if (stage.includes("quarter")) return { key: "quarter-final", score: 600 };
  if (stage.includes("round of 16") || stage.includes("last 16") || stage.includes("eighth")) return { key: "round-of-16", score: 500 };
  if (stage.includes("round of 32") || stage.includes("last 32")) return { key: "round-of-32", score: 450 };
  if (stage.includes("second") && stage.includes("group")) return { key: "second-group-stage", score: 400 };
  if (stage.includes("final") && (stage.includes("group") || stage.includes("round"))) return { key: "final-round", score: 850 };
  if (stage.includes("group") || stage.includes("pool")) return { key: "group-stage", score: 200 };
  return { key: "participant", score: 100 };
}

function winnerTeam(match, year) {
  const homeScore = Number(match.home_score);
  const awayScore = Number(match.away_score);
  if (homeScore > awayScore) return match.home_team;
  if (awayScore > homeScore) return match.away_team;
  const shootoutWinner = FINAL_SHOOTOUT_WINNERS[year];
  if (shootoutWinner && [match.home_team, match.away_team].includes(shootoutWinner)) return shootoutWinner;
  return comparePerformanceFallback(match.home_team, match.away_team);
}

function comparePerformanceFallback(homeTeam, awayTeam) {
  return [homeTeam, awayTeam].filter(Boolean).sort((left, right) => left.localeCompare(right))[0];
}

function finalMatchNote(match, year) {
  if (Number(match.home_score) === Number(match.away_score) && FINAL_SHOOTOUT_WINNERS[year]) return "Won final on penalties";
  return "Won the final";
}

function hasScore(match) {
  return Number.isFinite(Number(match.home_score)) && Number.isFinite(Number(match.away_score));
}

function isFinalMatch(match) {
  const stage = normalizeStage(match.stage);
  return !hasValue(match.group_name)
    && (stage === "final" || (stage.includes("final") && !stage.includes("semi") && !stage.includes("quarter") && !stage.includes("third") && !stage.includes("group") && !stage.includes("round")));
}

function isThirdPlaceMatch(match) {
  const stage = normalizeStage(match.stage);
  return stage.includes("third") || stage.includes("3rd") || stage.includes("bronze");
}

function isSemiFinalMatch(match) {
  return normalizeStage(match.stage).includes("semi");
}

function normalizeStage(value) {
  return String(value || "").toLowerCase().replace(/[–—]/g, "-").replace(/\s+/g, " ").trim();
}

function stageLabel(stage) {
  return {
    final: "Finalist",
    "third-place": "Third-place match",
    "semi-final": "Semi-finals",
    "quarter-final": "Quarter-finals",
    "round-of-16": "Round of 16",
    "round-of-32": "Round of 32",
    "second-group-stage": "Second group stage",
    "final-round": "Final round",
    "group-stage": "Group stage",
    participant: "Participant",
  }[stage] || "Participant";
}

function comparePerformance(left, right) {
  return right.points - left.points
    || right.goalDifference - left.goalDifference
    || right.goalsFor - left.goalsFor
    || left.team.localeCompare(right.team);
}

function sortMatches(left, right) {
  return String(left.match_date || "").localeCompare(String(right.match_date || ""))
    || Number(left.match_id) - Number(right.match_id);
}
