#!/usr/bin/env python3
"""Idempotently add verified 1930-1966 World Cup starting-XI appearances."""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from psycopg2.extras import execute_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from load_database import canonical_team_name, normalize_person_name  # noqa: E402
from load_player_data import connect, find_match, load_maps  # noqa: E402

SOURCE_ID = "openfootball_more"
SOURCE_NAME = "OpenFootball worldcup.more"
SOURCE_COMMIT = "092f6b7a97b1b2cea4b2fe2b7706894a8866878b"
YEARS = (1930, 1934, 1938, 1950, 1954, 1958, 1962, 1966)
URL = (
    "https://raw.githubusercontent.com/openfootball/worldcup.more/"
    f"{SOURCE_COMMIT}/worldcup/{{year}}_worldcup.txt"
)
DATE_RE = re.compile(
    r"^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(?P<month>[A-Z][a-z]{2})/"
    r"(?P<day>\d{1,2})(?:\s+(?P<year>\d{4}))?\s+@"
)
MATCH_RE = re.compile(
    r"^\s{2,}(?P<home>.+?)\s+v\s+(?P<away>.+?)\s{2,}"
    r"\d+\s*-\s*\d+(?:\s|$)"
)
STOP_PREFIXES = (
    "Sent off:", "Penalty", "Penalties:", "Referee:", "Coach:",
    "Coaches:", "Attendance:", "Booked:", "Bookings:",
)


@dataclass(frozen=True)
class MatchLineup:
    year: int
    match_date: str
    home: str
    away: str
    lineups: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class PlayerCandidate:
    player_id: int
    names: tuple[str, ...]


def log(message: str) -> None:
    print(f"[historical_backfill] {message}", flush=True)


def download(year: int, attempts: int = 3) -> str:
    request = urllib.request.Request(
        URL.format(year=year), headers={"User-Agent": "WorldCupDataExplorer/1.0"}
    )
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read().decode("utf-8-sig")
        except (urllib.error.URLError, TimeoutError, UnicodeError) as exc:
            if attempt == attempts:
                raise RuntimeError(f"Failed to download {year} lineups: {exc}") from exc
            time.sleep(2 ** (attempt - 1))
    raise AssertionError("unreachable")


def parse_date(line: str, fallback_year: int) -> str | None:
    match = DATE_RE.match(line.strip())
    if not match:
        return None
    year = int(match.group("year") or fallback_year)
    return datetime.strptime(
        f"{year}-{match.group('month')}-{match.group('day')}", "%Y-%b-%d"
    ).date().isoformat()


def split_players(raw: str) -> tuple[str, ...]:
    result = []
    for part in raw.split(","):
        name = re.sub(r"\s+", " ", part.strip().strip(","))
        name = re.sub(r"\s*\((?:c|captain|gk)\)\s*$", "", name, flags=re.I).strip()
        if name:
            result.append(name)
    return tuple(result)


def parse_lineups(text: str, year: int) -> list[MatchLineup]:
    current_date = None
    current = None
    active_team = None
    rows: list[MatchLineup] = []

    def finish_lineup() -> None:
        nonlocal active_team
        if current and active_team:
            raw = " ".join(current["parts"].pop(active_team, []))
            current["lineups"][active_team] = split_players(raw)
        active_team = None

    def finish_match() -> None:
        nonlocal current, active_team
        if not current:
            return
        finish_lineup()
        if current["date"] and all(
            team in current["lineups"] for team in (current["home"], current["away"])
        ):
            rows.append(
                MatchLineup(
                    year,
                    current["date"],
                    current["home"],
                    current["away"],
                    dict(current["lineups"]),
                )
            )
        current = None
        active_team = None

    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.rstrip()
        stripped = line.strip()
        parsed_date = parse_date(stripped, year)
        if parsed_date:
            finish_lineup()
            current_date = parsed_date
            continue

        match = MATCH_RE.match(line)
        if match:
            finish_match()
            current = {
                "date": current_date,
                "home": canonical_team_name(match.group("home").strip()),
                "away": canonical_team_name(match.group("away").strip()),
                "lineups": {},
                "parts": defaultdict(list),
            }
            continue
        if not current:
            continue

        label_match = re.match(r"^(?P<label>[^:]{2,80}):\s*(?P<body>.*)$", stripped)
        if label_match:
            label = canonical_team_name(label_match.group("label").strip())
            if label in {current["home"], current["away"]}:
                finish_lineup()
                active_team = label
                current["parts"][label].append(label_match.group("body").strip())
                continue

        if active_team:
            if not stripped or stripped.startswith(STOP_PREFIXES):
                finish_lineup()
            elif line[:1].isspace():
                current["parts"][active_team].append(stripped)
            else:
                finish_lineup()

    finish_match()
    return rows


def already_done(cursor) -> bool:
    cursor.execute(
        """
        SELECT COUNT(DISTINCT coverage_year)::int
        FROM source_metadata
        WHERE source_id=%s
          AND dataset_name LIKE 'historical_starting_lineups_%%'
          AND coverage_year=ANY(%s)
          AND notes LIKE 'status=complete%%'
        """,
        (SOURCE_ID, list(YEARS)),
    )
    return cursor.fetchone()[0] == len(YEARS)


def load_candidates(cursor) -> dict[tuple[int, int], list[PlayerCandidate]]:
    cursor.execute(
        """
        SELECT tr.year, pt.team_id, p.player_id, p.canonical_name
        FROM player_tournaments pt
        JOIN tournaments tr ON tr.tournament_id=pt.tournament_id
        JOIN players p ON p.player_id=pt.player_id
        WHERE tr.year=ANY(%s)
        """,
        (list(YEARS),),
    )
    base = cursor.fetchall()
    ids = sorted({row[2] for row in base})
    aliases: dict[int, set[str]] = defaultdict(set)
    if ids:
        cursor.execute(
            """
            SELECT player_id, original_name, normalized_name
            FROM player_aliases WHERE player_id=ANY(%s)
            """,
            (ids,),
        )
        for player_id, original, normalized in cursor.fetchall():
            aliases[player_id].update(
                (normalize_person_name(original), normalize_person_name(normalized))
            )

    result: dict[tuple[int, int], list[PlayerCandidate]] = defaultdict(list)
    for year, team_id, player_id, canonical in base:
        names = {normalize_person_name(canonical), *aliases.get(player_id, set())}
        result[(year, team_id)].append(
            PlayerCandidate(player_id, tuple(sorted(n for n in names if n)))
        )
    return result


def resolve_player(name: str, candidates: list[PlayerCandidate]) -> tuple[int | None, str]:
    normalized = normalize_person_name(name)
    exact = [candidate for candidate in candidates if normalized in candidate.names]
    if len(exact) == 1:
        return exact[0].player_id, "exact"
    if len(exact) > 1:
        return None, "ambiguous_exact"
    if len(normalized.split()) < 2:
        return None, "unmatched_single"

    scored = []
    for candidate in candidates:
        score = max(
            (
                difflib.SequenceMatcher(None, normalized, value).ratio()
                for value in candidate.names
            ),
            default=0,
        )
        scored.append((score, candidate.player_id))
    scored.sort(reverse=True)
    if not scored or scored[0][0] < 0.91:
        return None, "unmatched"
    if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.07:
        return None, "ambiguous_fuzzy"
    return scored[0][1], "fuzzy"


def verify(cursor) -> dict:
    cursor.execute(
        """
        SELECT p.canonical_name,
               COUNT(DISTINCT pa.match_id)::int,
               COUNT(DISTINCT g.goal_id) FILTER (WHERE NOT g.is_own_goal)::int
        FROM players p
        LEFT JOIN player_appearances pa ON pa.player_id=p.player_id
        LEFT JOIN goals g ON g.player_id=p.player_id
        WHERE LOWER(p.canonical_name) IN
          ('pelé','pele','just fontaine','sándor kocsis','sandor kocsis','helmut rahn')
        GROUP BY p.player_id, p.canonical_name
        ORDER BY p.canonical_name
        """
    )
    examples = [
        {"player": name, "appearances": apps, "goals": goals}
        for name, apps, goals in cursor.fetchall()
    ]
    cursor.execute(
        """
        SELECT COUNT(*)::int FROM (
          SELECT p.player_id
          FROM players p
          JOIN goals g ON g.player_id=p.player_id AND NOT g.is_own_goal
          LEFT JOIN player_appearances pa ON pa.player_id=p.player_id
          GROUP BY p.player_id HAVING COUNT(DISTINCT pa.match_id)=0
        ) x
        """
    )
    return {
        "examples": examples,
        "scorers_with_zero_appearances": cursor.fetchone()[0],
    }


def run(database_url: str, force: bool = False) -> dict:
    connection = connect(database_url)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_xact_lock(%s,%s)", (2026, 731))
            if not cursor.fetchone()[0]:
                connection.rollback()
                return {"status": "busy"}
            if not force and already_done(cursor):
                result = {"status": "already_complete", "verification": verify(cursor)}
                connection.rollback()
                return result

            parsed = {}
            for year in YEARS:
                parsed[year] = parse_lineups(download(year), year)
                if not parsed[year]:
                    raise RuntimeError(f"No matches parsed for {year}")
                log(f"{year}: parsed {len(parsed[year])} matches")

            _tournaments, teams, match_map = load_maps(cursor)
            candidates = load_candidates(cursor)
            appearances = []
            aliases = []
            stats = defaultdict(int)
            by_year = defaultdict(lambda: defaultdict(int))

            for year, matches in parsed.items():
                for item in matches:
                    match_id, reversed_teams, shifted_date = find_match(
                        match_map,
                        year,
                        item.match_date,
                        item.home,
                        item.away,
                        allow_adjacent_date=True,
                    )
                    stats["reversed_matches"] += int(reversed_teams)
                    stats["shifted_dates"] += int(shifted_date)
                    if not match_id:
                        stats["unmatched_matches"] += 1
                        continue
                    stats["matched_matches"] += 1
                    by_year[year]["matched_matches"] += 1

                    for team_name, lineup in item.lineups.items():
                        team_id = teams.get(canonical_team_name(team_name))
                        if not team_id:
                            stats["unmatched_teams"] += 1
                            continue
                        squad = candidates.get((year, team_id), [])
                        stats["nonstandard_lineups"] += int(len(lineup) != 11)
                        for source_name in lineup:
                            player_id, method = resolve_player(source_name, squad)
                            if not player_id:
                                stats[method] += 1
                                by_year[year]["unmatched_players"] += 1
                                continue
                            appearances.append(
                                (player_id, match_id, team_id, True, None, SOURCE_ID)
                            )
                            aliases.append(
                                (
                                    player_id,
                                    SOURCE_ID,
                                    source_name,
                                    normalize_person_name(source_name),
                                )
                            )
                            stats[f"matched_{method}"] += 1
                            by_year[year]["appearance_rows"] += 1

            total_parsed = sum(len(rows) for rows in parsed.values())
            if stats["matched_matches"] < int(total_parsed * 0.95):
                raise RuntimeError(
                    f"Safety stop: linked {stats['matched_matches']}/{total_parsed} matches"
                )
            if len(appearances) < 3500:
                raise RuntimeError(
                    f"Safety stop: produced only {len(appearances)} appearance rows"
                )

            execute_values(
                cursor,
                """
                INSERT INTO player_appearances
                  (player_id,match_id,team_id,started,goalkeeper,source_id)
                VALUES %s
                ON CONFLICT (player_id,match_id,team_id,source_id)
                DO UPDATE SET started=TRUE
                """,
                appearances,
                page_size=1000,
            )
            execute_values(
                cursor,
                """
                INSERT INTO player_aliases
                  (player_id,source_id,original_name,normalized_name)
                VALUES %s
                ON CONFLICT (source_id,normalized_name,player_id) DO NOTHING
                """,
                aliases,
                page_size=1000,
            )

            for year in YEARS:
                dataset = f"historical_starting_lineups_{year}"
                notes = (
                    "status=complete; "
                    f"source_commit={SOURCE_COMMIT}; "
                    f"parsed_matches={len(parsed[year])}; "
                    f"matched_matches={by_year[year]['matched_matches']}; "
                    f"appearance_rows={by_year[year]['appearance_rows']}; "
                    f"unmatched_players={by_year[year]['unmatched_players']}; "
                    "minutes_not_inferred=true"
                )
                cursor.execute(
                    """
                    DELETE FROM source_metadata
                    WHERE source_id=%s AND dataset_name=%s AND coverage_year=%s
                    """,
                    (SOURCE_ID, dataset, year),
                )
                cursor.execute(
                    """
                    INSERT INTO source_metadata
                      (source_id,source_name,dataset_name,coverage_year,
                       match_count,file_path,notes)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        SOURCE_ID,
                        SOURCE_NAME,
                        dataset,
                        year,
                        by_year[year]["matched_matches"],
                        URL.format(year=year),
                        notes,
                    ),
                )

            result = {
                "status": "applied",
                "stats": dict(stats),
                "verification": verify(cursor),
            }
            connection.commit()
            return result
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--startup-safe", action="store_true")
    args = parser.parse_args()
    load_dotenv(ROOT / "backend" / ".env")
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        if args.startup_safe:
            log("skipped: DATABASE_URL missing")
            return 0
        raise SystemExit("DATABASE_URL missing")
    try:
        log(json.dumps(run(database_url, force=args.force), ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        if args.startup_safe:
            log(f"startup-safe failure: {type(exc).__name__}: {exc}")
            return 0
        raise


if __name__ == "__main__":
    raise SystemExit(main())
