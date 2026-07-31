#!/usr/bin/env python3
"""Backfill men's World Cup starting lineups for 1930-1966.

The Fjelstul player-appearance table starts in 1970, while historical goals
cover earlier tournaments. This idempotent migration reads the CC0
OpenFootball worldcup.more lineup files and inserts only verified starting-XI
appearances. It never resets tables, deletes existing data, or invents minutes.
"""

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
from typing import Iterable

from dotenv import load_dotenv
from psycopg2.extras import Json, execute_values

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from load_database import canonical_team_name, normalize_person_name  # noqa: E402
from load_player_data import connect, find_match, load_maps  # noqa: E402

SOURCE_ID = "openfootball_more"
SOURCE_NAME = "OpenFootball worldcup.more"
SOURCE_COMMIT = "092f6b7a97b1b2cea4b2fe2b7706894a8866878b"
YEARS = (1930, 1934, 1938, 1950, 1954, 1958, 1962, 1966)
DATASET_PREFIX = "historical_starting_lineups"
URL_TEMPLATE = (
    "https://raw.githubusercontent.com/openfootball/worldcup.more/"
    f"{SOURCE_COMMIT}/worldcup/{{year}}_worldcup.txt"
)
USER_AGENT = "WorldCupDataExplorer/1.0"

DATE_RE = re.compile(
    r"^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+"
    r"(?P<month>[A-Z][a-z]{2})/(?P<day>\d{1,2})(?:\s+(?P<year>\d{4}))?\s+@"
)
MATCH_RE = re.compile(
    r"^\s{2,}(?P<home>.+?)\s+v\s+(?P<away>.+?)\s{2,}"
    r"(?P<home_score>\d+)\s*-\s*(?P<away_score>\d+)(?:\s|$)"
)
METADATA_PREFIXES = (
    "Sent off:", "Penalty", "Penalties:", "Referee:", "Coach:",
    "Coaches:", "Attendance:", "Booked:", "Bookings:",
)


@dataclass(frozen=True)
class ParsedMatch:
    year: int
    match_date: str
    home_team: str
    away_team: str
    lineups: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class Candidate:
    player_id: int
    canonical_name: str
    normalized_names: tuple[str, ...]


def log(message: str) -> None:
    print(f"[historical_backfill] {message}", flush=True)


def source_url(year: int) -> str:
    return URL_TEMPLATE.format(year=year)


def download_text(year: int, attempts: int = 3, timeout: int = 30) -> str:
    request = urllib.request.Request(source_url(year), headers={"User-Agent": USER_AGENT})
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8-sig")
        except (urllib.error.URLError, TimeoutError, UnicodeError) as exc:
            if attempt == attempts:
                raise RuntimeError(f"Could not download historical lineups for {year}: {exc}") from exc
            delay = 2 ** (attempt - 1)
            log(f"download failed for {year}; retrying in {delay}s")
            time.sleep(delay)
    raise AssertionError("unreachable")


def parse_date_line(line: str, fallback_year: int) -> str | None:
    match = DATE_RE.match(line.strip())
    if not match:
        return None
    year = int(match.group("year") or fallback_year)
    parsed = datetime.strptime(
        f"{year}-{match.group('month')}-{match.group('day')}", "%Y-%b-%d"
    ).date()
    return parsed.isoformat()


def clean_lineup_name(value: str) -> str:
    value = re.sub(r"\s+", " ", value.strip().strip(","))
    return re.sub(r"\s*\((?:c|captain|gk)\)\s*$", "", value, flags=re.I).strip()


def split_lineup(value: str) -> tuple[str, ...]:
    return tuple(
        name for part in value.split(",")
        if (name := clean_lineup_name(part))
    )


def parse_historical_lineups(text: str, year: int) -> list[ParsedMatch]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    current_date: str | None = None
    current: dict | None = None
    active_team: str | None = None
    results: list[ParsedMatch] = []

    def finish_active_lineup() -> None:
        nonlocal active_team
        if not current or not active_team:
            active_team = None
            return
        raw = " ".join(current["lineup_parts"].pop(active_team, []))
        current["lineups"][active_team] = split_lineup(raw)
        active_team = None

    def finish_match() -> None:
        nonlocal current, active_team
        if not current:
            return
        finish_active_lineup()
        home = current["home_team"]
        away = current["away_team"]
        if current.get("match_date") and home in current["lineups"] and away in current["lineups"]:
            results.append(
                ParsedMatch(
                    year=year,
                    match_date=current["match_date"],
                    home_team=home,
                    away_team=away,
                    lineups={home: tuple(current["lineups"][home]), away: tuple(current["lineups"][away])},
                )
            )
        current = None
        active_team = None

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()

        parsed_date = parse_date_line(stripped, year)
        if parsed_date:
            finish_active_lineup()
            current_date = parsed_date
            continue

        match = MATCH_RE.match(line)
        if match:
            finish_match()
            current = {
                "match_date": current_date,
                "home_team": canonical_team_name(match.group("home").strip()),
                "away_team": canonical_team_name(match.group("away").strip()),
                "lineups": {},
                "lineup_parts": defaultdict(list),
            }
            continue

        if not current:
            continue

        home = current["home_team"]
        away = current["away_team"]
        started = False
        for team, prefix in ((home, f"{home}:"), (away, f"{away}:")):
            if stripped.startswith(prefix):
                finish_active_lineup()
                active_team = team
                current["lineup_parts"][team].append(stripped[len(prefix):].strip())
                started = True
                break
        if started:
            continue

        generic_label = re.match(r"^(?P<label>[^:]{2,80}):\s*(?P<body>.*)$", stripped)
        if generic_label:
            label = canonical_team_name(generic_label.group("label").strip())
            if label in {home, away}:
                finish_active_lineup()
                active_team = label
                current["lineup_parts"][label].append(generic_label.group("body").strip())
                continue

        if active_team:
            if not stripped or stripped.startswith(METADATA_PREFIXES):
                finish_active_lineup()
            elif line[:1].isspace():
                current["lineup_parts"][active_team].append(stripped)
            else:
                finish_active_lineup()

    finish_match()
    return results


def migration_complete(cursor) -> bool:
    cursor.execute(
        """
        SELECT COUNT(DISTINCT coverage_year)::int
        FROM source_metadata
        WHERE source_id = %s
          AND dataset_name LIKE %s
          AND coverage_year = ANY(%s)
          AND notes LIKE 'status=complete%%'
        """,
        (SOURCE_ID, f"{DATASET_PREFIX}_%", list(YEARS)),
    )
    return cursor.fetchone()[0] == len(YEARS)


def fetch_player_candidates(cursor) -> dict[tuple[int, int], list[Candidate]]:
    cursor.execute(
        """
        SELECT tr.year, pt.team_id, p.player_id, p.canonical_name
        FROM player_tournaments pt
        JOIN tournaments tr ON tr.tournament_id = pt.tournament_id
        JOIN players p ON p.player_id = pt.player_id
        WHERE tr.year = ANY(%s)
        ORDER BY tr.year, pt.team_id, p.player_id
        """,
        (list(YEARS),),
    )
    base_rows = cursor.fetchall()
    player_ids = sorted({row[2] for row in base_rows})
    aliases: dict[int, set[str]] = defaultdict(set)
    if player_ids:
        cursor.execute(
            "SELECT player_id, original_name, normalized_name FROM player_aliases WHERE player_id = ANY(%s)",
            (player_ids,),
        )
        for player_id, original_name, normalized_name in cursor.fetchall():
            aliases[player_id].add(normalize_person_name(original_name))
            aliases[player_id].add(normalize_person_name(normalized_name))

    result: dict[tuple[int, int], list[Candidate]] = defaultdict(list)
    for year, team_id, player_id, canonical_name in base_rows:
        names = {normalize_person_name(canonical_name), *aliases.get(player_id, set())}
        result[(year, team_id)].append(
            Candidate(player_id, canonical_name, tuple(sorted(name for name in names if name)))
        )
    return result


def match_player(source_name: str, candidates: Iterable[Candidate]) -> tuple[Candidate | None, str]:
    normalized = normalize_person_name(source_name)
    if not normalized:
        return None, "empty"
    exact = [candidate for candidate in candidates if normalized in candidate.normalized_names]
    if len(exact) == 1:
        return exact[0], "exact"
    if len(exact) > 1:
        return None, "ambiguous_exact"
    if len(normalized.split()) < 2:
        return None, "unmatched_single_name"

    scored: list[tuple[float, Candidate]] = []
    for candidate in candidates:
        best = max(
            (difflib.SequenceMatcher(None, normalized, name).ratio() for name in candidate.normalized_names),
            default=0.0,
        )
        scored.append((best, candidate))
    scored.sort(key=lambda item: (-item[0], item[1].player_id))
    if not scored or scored[0][0] < 0.91:
        return None, "unmatched"
    if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.07:
        return None, "ambiguous_fuzzy"
    return scored[0][1], "fuzzy"


def record_issue(cursor, issue_type: str, description: str, external_id: str, payload: dict, severity: str = "warning") -> None:
    cursor.execute(
        """
        INSERT INTO data_quality_issues
          (source_id, issue_type, severity, entity_type, external_id, description, raw_payload)
        SELECT %s, %s, %s, 'historical_appearance', %s, %s, %s
        WHERE NOT EXISTS (
          SELECT 1 FROM data_quality_issues
          WHERE source_id = %s AND issue_type = %s
            AND COALESCE(external_id, '') = COALESCE(%s, '') AND description = %s
        )
        """,
        (SOURCE_ID, issue_type, severity, external_id, description, Json(payload),
         SOURCE_ID, issue_type, external_id, description),
    )


def collect_rows(cursor, parsed_by_year: dict[int, list[ParsedMatch]]) -> tuple[list[tuple], list[tuple], dict]:
    _tournaments, teams, match_map = load_maps(cursor)
    candidates = fetch_player_candidates(cursor)
    appearance_rows: list[tuple] = []
    alias_rows: list[tuple] = []
    stats = defaultdict(int)
    per_year = defaultdict(lambda: defaultdict(int))

    for year in YEARS:
        for parsed in parsed_by_year.get(year, []):
            match_id, reversed_teams, shifted_date = find_match(
                match_map, year, parsed.match_date, parsed.home_team, parsed.away_team,
                allow_adjacent_date=True,
            )
            match_key = f"{year}:{parsed.match_date}:{parsed.home_team}:{parsed.away_team}"
            if not match_id:
                stats["unmatched_matches"] += 1
                per_year[year]["unmatched_matches"] += 1
                record_issue(cursor, "historical_lineup_unmatched_match",
                             "Could not link historical lineup to a canonical match", match_key,
                             {"year": year, "date": parsed.match_date,
                              "home": parsed.home_team, "away": parsed.away_team})
                continue

            stats["matched_matches"] += 1
            per_year[year]["matched_matches"] += 1
            stats["reversed_matches"] += int(reversed_teams)
            stats["shifted_dates"] += int(shifted_date)

            for team_name, lineup in parsed.lineups.items():
                team_id = teams.get(canonical_team_name(team_name))
                if not team_id:
                    stats["unmatched_teams"] += 1
                    continue
                squad = candidates.get((year, team_id), [])
                if len(lineup) != 11:
                    stats["nonstandard_lineups"] += 1
                    record_issue(cursor, "historical_lineup_nonstandard_size",
                                 f"Parsed {len(lineup)} players instead of 11",
                                 f"{match_key}:{team_name}", {"lineup": list(lineup)}, "info")

                for source_name in lineup:
                    player, method = match_player(source_name, squad)
                    if not player:
                        stats["unmatched_players"] += 1
                        per_year[year]["unmatched_players"] += 1
                        record_issue(
                            cursor, f"historical_lineup_{method}",
                            f"Could not safely link '{source_name}' inside the {year} {team_name} squad",
                            f"{match_key}:{team_name}:{normalize_person_name(source_name)}",
                            {"year": year, "team": team_name, "player": source_name,
                             "candidate_count": len(squad)},
                        )
                        continue
                    appearance_rows.append((player.player_id, match_id, team_id, True, None, SOURCE_ID))
                    alias_rows.append((player.player_id, SOURCE_ID, source_name,
                                       normalize_person_name(source_name)))
                    stats[f"player_match_{method}"] += 1
                    per_year[year]["appearance_rows"] += 1

    stats["appearance_rows"] = len(appearance_rows)
    stats["alias_rows"] = len(alias_rows)
    stats["per_year"] = {year: dict(counts) for year, counts in per_year.items()}
    return appearance_rows, alias_rows, dict(stats)


def apply_rows(cursor, appearance_rows: list[tuple], alias_rows: list[tuple]) -> None:
    execute_values(
        cursor,
        """
        INSERT INTO player_appearances
          (player_id, match_id, team_id, started, goalkeeper, source_id)
        VALUES %s
        ON CONFLICT (player_id, match_id, team_id, source_id) DO UPDATE SET started = TRUE
        """,
        appearance_rows,
        page_size=1000,
    )
    execute_values(
        cursor,
        """
        INSERT INTO player_aliases (player_id, source_id, original_name, normalized_name)
        VALUES %s
        ON CONFLICT (source_id, normalized_name, player_id) DO NOTHING
        """,
        alias_rows,
        page_size=1000,
    )


def write_metadata(cursor, parsed_by_year: dict[int, list[ParsedMatch]], stats: dict) -> None:
    for year in YEARS:
        year_stats = stats.get("per_year", {}).get(year, {})
        dataset_name = f"{DATASET_PREFIX}_{year}"
        notes = (
            "status=complete; "
            f"source_commit={SOURCE_COMMIT}; parsed_matches={len(parsed_by_year.get(year, []))}; "
            f"matched_matches={year_stats.get('matched_matches', 0)}; "
            f"appearance_rows={year_stats.get('appearance_rows', 0)}; "
            f"unmatched_players={year_stats.get('unmatched_players', 0)}; "
            "minutes_not_inferred=true"
        )
        cursor.execute(
            "DELETE FROM source_metadata WHERE source_id=%s AND dataset_name=%s AND coverage_year=%s",
            (SOURCE_ID, dataset_name, year),
        )
        cursor.execute(
            """
            INSERT INTO source_metadata
              (source_id, source_name, dataset_name, coverage_year, match_count, file_path, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (SOURCE_ID, SOURCE_NAME, dataset_name, year,
             year_stats.get("matched_matches", 0), source_url(year), notes),
        )


def verification(cursor) -> dict:
    cursor.execute(
        """
        SELECT p.canonical_name,
               COUNT(DISTINCT pa.match_id)::int AS appearances,
               COUNT(DISTINCT g.goal_id) FILTER (WHERE NOT g.is_own_goal)::int AS goals
        FROM players p
        LEFT JOIN player_appearances pa ON pa.player_id=p.player_id
        LEFT JOIN goals g ON g.player_id=p.player_id
        WHERE normalize_person_name IS NULL
        GROUP BY p.player_id, p.canonical_name
        LIMIT 0
        """
    )
    cursor.execute(
        """
        SELECT p.canonical_name,
               COUNT(DISTINCT pa.match_id)::int AS appearances,
               COUNT(DISTINCT g.goal_id) FILTER (WHERE NOT g.is_own_goal)::int AS goals
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
        {"player": name, "appearances": appearances, "goals": goals}
        for name, appearances, goals in cursor.fetchall()
    ]
    cursor.execute(
        """
        SELECT COUNT(*)::int FROM (
          SELECT p.player_id
          FROM players p
          JOIN goals g ON g.player_id=p.player_id AND NOT g.is_own_goal
          LEFT JOIN player_appearances pa ON pa.player_id=p.player_id
          GROUP BY p.player_id HAVING COUNT(DISTINCT pa.match_id)=0
        ) unresolved
        """
    )
    return {"examples": examples,
            "scorers_with_zero_recorded_appearances": cursor.fetchone()[0]}


def run(database_url: str, *, apply: bool, force: bool = False) -> dict:
    connection = connect(database_url)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_xact_lock(%s, %s)", (2026, 731))
            if not cursor.fetchone()[0]:
                connection.rollback()
                return {"status": "another_backfill_is_running"}
            if not force and migration_complete(cursor):
                result = {"status": "already_complete", "verification": verification(cursor)}
                connection.rollback()
                return result

            parsed_by_year: dict[int, list[ParsedMatch]] = {}
            for year in YEARS:
                parsed = parse_historical_lineups(download_text(year), year)
                if not parsed:
                    raise RuntimeError(f"No historical lineups parsed for {year}")
                parsed_by_year[year] = parsed
                log(f"{year}: parsed {len(parsed)} matches")

            appearance_rows, alias_rows, stats = collect_rows(cursor, parsed_by_year)
            expected_matches = sum(len(rows) for rows in parsed_by_year.values())
            if stats.get("matched_matches", 0) < int(expected_matches * 0.95):
                raise RuntimeError(
                    f"Safety stop: linked only {stats.get('matched_matches', 0)}/{expected_matches} matches"
                )
            if not appearance_rows:
                raise RuntimeError("Safety stop: no historical appearance rows produced")

            if apply:
                apply_rows(cursor, appearance_rows, alias_rows)
                write_metadata(cursor, parsed_by_year, stats)
                verify = verification(cursor)
                connection.commit()
                status = "applied"
            else:
                verify = verification(cursor)
                connection.rollback()
                status = "dry_run"
            return {"status": status, "stats": stats, "verification": verify}
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--startup-safe", action="store_true")
    args = parser.parse_args()

    load_dotenv(ROOT / "backend" / ".env")
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        if args.startup_safe:
            log("skipped: DATABASE_URL is missing")
            return 0
        raise SystemExit("DATABASE_URL is missing")
    try:
        result = run(database_url, apply=args.apply, force=args.force)
        log(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        if args.startup_safe:
            log(f"startup-safe failure: {type(exc).__name__}: {exc}")
            return 0
        raise


if __name__ == "__main__":
    raise SystemExit(main())
