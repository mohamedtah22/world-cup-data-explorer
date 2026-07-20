import csv
import json
import os
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import Json, execute_batch

from load_database import canonical_team_name, fetch_id, normalize_person_name, upsert_player, upsert_team

ROOT = Path(__file__).resolve().parents[1]
FJELSTUL_DIR = ROOT / "data" / "raw" / "fjelstul"
STATSBOMB_DIR = ROOT / "data" / "raw" / "statsbomb"
METADATA_FILE = ROOT / "data" / "raw" / "source_metadata.json"


def read_csv(name):
    path = FJELSTUL_DIR / f"{name}.csv"
    if not path.exists():
        raise FileNotFoundError(f"Missing {path}. Run scripts/download_player_sources.py first.")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def clean_text(value):
    value = (value or "").strip()
    return None if value in {"", "NA", "not applicable", "Not Applicable", "not available", "Not Available"} else value


def player_name(row):
    given = clean_text(row.get("given_name"))
    family = clean_text(row.get("family_name"))
    return " ".join(part for part in (given, family) if part) or "Unknown player"


def parse_bool(value):
    return str(value or "").strip() in {"1", "TRUE", "True", "true"}


def parse_int(value):
    value = clean_text(value)
    return int(value) if value is not None else None


def parse_date(value):
    value = clean_text(value)
    return date.fromisoformat(value) if value else None


def tournament_year(row):
    match = re.search(r"(19|20)\d{2}", row.get("tournament_name", "") or row.get("tournament_id", ""))
    return int(match.group(0)) if match else None


def source_match_key_from_row(row):
    year = tournament_year(row)
    home = canonical_team_name(row.get("home_team_name") or row.get("team_name") if parse_bool(row.get("home_team")) else row.get("home_team_name"))
    away = canonical_team_name(row.get("away_team_name") if row.get("away_team_name") else row.get("team_name"))
    return year, row.get("match_date"), home, away


def load_maps(cursor):
    cursor.execute("SELECT tournament_id, year FROM tournaments")
    tournaments = {year: tid for tid, year in cursor.fetchall()}
    cursor.execute("SELECT team_id, canonical_name FROM teams")
    teams = {name: tid for tid, name in cursor.fetchall()}
    cursor.execute(
        """
        SELECT m.match_id, tr.year, m.match_date, h.canonical_name, a.canonical_name
        FROM matches m
        JOIN tournaments tr ON tr.tournament_id = m.tournament_id
        JOIN teams h ON h.team_id = m.home_team_id
        JOIN teams a ON a.team_id = m.away_team_id
        """
    )
    matches = {(year, match_date.isoformat(), home, away): match_id for match_id, year, match_date, home, away in cursor.fetchall()}
    return tournaments, teams, matches


def insert_alias(cursor, player_id, source_id, original_name):
    cursor.execute(
        """
        INSERT INTO player_aliases (player_id, source_id, original_name, normalized_name)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (source_id, normalized_name, player_id) DO NOTHING
        """,
        (player_id, source_id, original_name, normalize_person_name(original_name)),
    )


def record_issue(cursor, source_id, issue_type, description, entity_type=None, external_id=None, raw_payload=None, severity="warning"):
    cursor.execute(
        """
        INSERT INTO data_quality_issues (source_id, issue_type, severity, entity_type, external_id, description, raw_payload)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (source_id, issue_type, severity, entity_type, external_id, description, Json(raw_payload) if raw_payload is not None else None),
    )


def match_key_for_fjelstul(row):
    year = tournament_year(row)
    home = canonical_team_name(row.get("home_team_name"))
    away = canonical_team_name(row.get("away_team_name"))
    return year, row.get("match_date"), home, away


def load_fjelstul(cursor, stats):
    players = read_csv("players")
    squads = read_csv("squads")
    appearances = read_csv("player_appearances")
    matches = read_csv("matches")
    goals = read_csv("goals")
    penalty_kicks = read_csv("penalty_kicks")
    bookings = read_csv("bookings")
    substitutions = read_csv("substitutions")
    awards = read_csv("awards")
    award_winners = read_csv("award_winners")

    tournaments, teams, match_map = load_maps(cursor)
    player_ids = {}

    for row in players:
        pid = upsert_player(cursor, player_name(row), external_fjelstul_id=row["player_id"])
        player_ids[row["player_id"]] = pid
        preferred = None
        for flag, label in (("goal_keeper", "Goalkeeper"), ("defender", "Defender"), ("midfielder", "Midfielder"), ("forward", "Forward")):
            if parse_bool(row.get(flag)):
                preferred = label
                break
        cursor.execute(
            """
            UPDATE players
            SET birth_date = COALESCE(%s, birth_date),
                preferred_position = COALESCE(%s, preferred_position)
            WHERE player_id = %s
            """,
            (parse_date(row.get("birth_date")), preferred, pid),
        )
        insert_alias(cursor, pid, "fjelstul", player_name(row))

    for row in squads:
        year = tournament_year(row)
        if year not in tournaments:
            continue
        team_name = canonical_team_name(row.get("team_name"))
        team_id = teams.get(team_name) or upsert_team(cursor, team_name)
        teams[team_name] = team_id
        pid = player_ids.get(row["player_id"])
        if not pid:
            continue
        cursor.execute(
            """
            INSERT INTO player_tournaments (player_id, tournament_id, team_id, shirt_number, position, squad_status)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (player_id, tournament_id, team_id) DO UPDATE SET
              shirt_number = EXCLUDED.shirt_number,
              position = EXCLUDED.position,
              squad_status = EXCLUDED.squad_status
            """,
            (pid, tournaments[year], team_id, parse_int(row.get("shirt_number")), clean_text(row.get("position_name")), "squad"),
        )

    fjelstul_match_ids = {}
    for row in matches:
        key = match_key_for_fjelstul(row)
        match_id = match_map.get(key)
        if match_id:
            fjelstul_match_ids[row["match_id"]] = match_id
            cursor.execute("UPDATE matches SET external_fjelstul_id = %s WHERE match_id = %s", (row["match_id"], match_id))
        else:
            record_issue(cursor, "fjelstul", "unmatched_match", "Could not link Fjelstul match to canonical match", "match", row.get("match_id"), row)

    goal_counts = Counter()
    penalty_counts = Counter()
    card_counts = Counter()

    # Fjelstul is authoritative for player goal identity. OpenFootball goal rows
    # are useful before player data is loaded, but keeping both sources creates
    # duplicate scorers such as "Harry Kane" and "Kane" for the same tournament.
    cursor.execute("DELETE FROM goals WHERE source_goal_key NOT LIKE 'fjelstul:%'")

    for row in goals:
        match_id = fjelstul_match_ids.get(row.get("match_id"))
        player_id = player_ids.get(row.get("player_id"))
        team_name = canonical_team_name(row.get("player_team_name") or row.get("team_name"))
        team_id = teams.get(team_name)
        if not match_id or not player_id or not team_id:
            stats["unmatched_players"] += 1
            record_issue(cursor, "fjelstul", "unmatched_goal_player", "Could not link goal to canonical player/match/team", "goal", row.get("goal_id"), row)
            continue
        goal_counts[(player_id, match_id)] += 1
        if parse_bool(row.get("penalty")):
            penalty_counts[(player_id, match_id)] += 1
        cursor.execute(
            """
            INSERT INTO goals (source_goal_key, match_id, player_id, team_id, tournament_id, minute, stoppage_minute, is_penalty, is_own_goal)
            SELECT %s, %s, %s, %s, m.tournament_id, %s, %s, %s, %s
            FROM matches m WHERE m.match_id = %s
            ON CONFLICT (source_goal_key) DO UPDATE SET
              match_id = EXCLUDED.match_id,
              player_id = EXCLUDED.player_id,
              team_id = EXCLUDED.team_id,
              tournament_id = EXCLUDED.tournament_id,
              minute = EXCLUDED.minute,
              stoppage_minute = EXCLUDED.stoppage_minute,
              is_penalty = EXCLUDED.is_penalty,
              is_own_goal = EXCLUDED.is_own_goal
            """,
            (
                f"fjelstul:{row['goal_id']}",
                match_id,
                player_id,
                team_id,
                parse_int(row.get("minute_regulation")),
                parse_int(row.get("minute_stoppage")),
                parse_bool(row.get("penalty")),
                parse_bool(row.get("own_goal")),
                match_id,
            ),
        )

    for row in penalty_kicks:
        if parse_bool(row.get("converted")):
            match_id = fjelstul_match_ids.get(row.get("match_id"))
            player_id = player_ids.get(row.get("player_id"))
            if match_id and player_id:
                penalty_counts[(player_id, match_id)] += 1

    for row in bookings:
        match_id = fjelstul_match_ids.get(row.get("match_id"))
        player_id = player_ids.get(row.get("player_id"))
        team_name = canonical_team_name(row.get("team_name"))
        team_id = teams.get(team_name)
        if not match_id or not player_id or not team_id:
            record_issue(cursor, "fjelstul", "unmatched_booking_player", "Could not link booking to canonical player/match/team", "booking", row.get("booking_id"), row)
            continue
        card_type = "second_yellow" if parse_bool(row.get("second_yellow_card")) else ("red" if parse_bool(row.get("red_card")) else "yellow")
        card_counts[(player_id, match_id, card_type)] += 1
        cursor.execute(
            """
            INSERT INTO bookings (external_booking_id, match_id, player_id, team_id, minute, card_type, source_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (source_id, external_booking_id) DO NOTHING
            """,
            (row["booking_id"], match_id, player_id, team_id, parse_int(row.get("minute_regulation")), card_type, "fjelstul"),
        )

    appearance_rows = {}
    for row in appearances:
        match_id = fjelstul_match_ids.get(row.get("match_id"))
        player_id = player_ids.get(row.get("player_id"))
        team_name = canonical_team_name(row.get("team_name"))
        team_id = teams.get(team_name)
        if not match_id or not player_id or not team_id:
            stats["unmatched_players"] += 1
            record_issue(cursor, "fjelstul", "unmatched_appearance_player", "Could not link appearance to canonical player/match/team", "appearance", row.get("key_id"), row)
            continue
        started = parse_bool(row.get("starter"))
        cursor.execute(
            """
            INSERT INTO player_appearances (player_id, match_id, team_id, started, goalkeeper, source_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (player_id, match_id, team_id, source_id) DO UPDATE SET
              started = EXCLUDED.started,
              goalkeeper = EXCLUDED.goalkeeper
            """,
            (player_id, match_id, team_id, started, clean_text(row.get("position_name")) == "goalkeeper", "fjelstul"),
        )
        appearance_rows[(player_id, match_id)] = True
        cursor.execute(
            """
            INSERT INTO player_match_stats (
              player_id, match_id, minutes_played, goals, penalties_scored,
              yellow_cards, red_cards, source_id
            )
            VALUES (%s, %s, NULL, %s, %s, %s, %s, %s)
            ON CONFLICT (player_id, match_id, source_id) DO UPDATE SET
              goals = EXCLUDED.goals,
              penalties_scored = EXCLUDED.penalties_scored,
              yellow_cards = EXCLUDED.yellow_cards,
              red_cards = EXCLUDED.red_cards
            """,
            (
                player_id,
                match_id,
                goal_counts.get((player_id, match_id), 0),
                penalty_counts.get((player_id, match_id), 0),
                card_counts.get((player_id, match_id, "yellow"), 0) + card_counts.get((player_id, match_id, "second_yellow"), 0),
                card_counts.get((player_id, match_id, "red"), 0) + card_counts.get((player_id, match_id, "second_yellow"), 0),
                "fjelstul",
            ),
        )

    for row in substitutions:
        match_id = fjelstul_match_ids.get(row.get("match_id"))
        team_name = canonical_team_name(row.get("team_name"))
        team_id = teams.get(team_name)
        player_id = player_ids.get(row.get("player_id"))
        if not match_id or not player_id or not team_id:
            continue
        out_id = player_id if parse_bool(row.get("going_off")) else None
        in_id = player_id if parse_bool(row.get("coming_on")) else None
        cursor.execute(
            """
            INSERT INTO substitutions (external_substitution_id, match_id, team_id, player_out_id, player_in_id, minute, source_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (source_id, external_substitution_id, player_out_id, player_in_id) DO NOTHING
            """,
            (row["substitution_id"], match_id, team_id, out_id, in_id, parse_int(row.get("minute_regulation")), "fjelstul"),
        )
        if in_id:
            cursor.execute(
                "UPDATE player_appearances SET entered_minute = %s WHERE player_id = %s AND match_id = %s AND team_id = %s",
                (parse_int(row.get("minute_regulation")), player_id, match_id, team_id),
            )
        if out_id:
            cursor.execute(
                "UPDATE player_appearances SET exited_minute = %s WHERE player_id = %s AND match_id = %s AND team_id = %s",
                (parse_int(row.get("minute_regulation")), player_id, match_id, team_id),
            )

    for dataset, rows in (
        ("players", players),
        ("squads", squads),
        ("player_appearances", appearances),
        ("goals", goals),
        ("penalty_kicks", penalty_kicks),
        ("bookings", bookings),
        ("substitutions", substitutions),
        ("awards", awards),
        ("award_winners", award_winners),
    ):
        cursor.execute(
            """
            INSERT INTO source_metadata (source_id, source_name, dataset_name, match_count, file_path, notes)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (source_id, dataset_name, COALESCE(coverage_year, 0), COALESCE(competition_id, 0), COALESCE(season_id, 0))
            DO UPDATE SET match_count = EXCLUDED.match_count, file_path = EXCLUDED.file_path, downloaded_at = NOW()
            """,
            ("fjelstul", "Fjelstul World Cup Database", dataset, len(rows), f"data/raw/fjelstul/{dataset}.csv", "Authoritative historical player dataset"),
        )


def statsbomb_match_key(match):
    return (
        int(match["season"]["season_name"]),
        match["match_date"],
        canonical_team_name(match["home_team"]["home_team_name"]),
        canonical_team_name(match["away_team"]["away_team_name"]),
    )


def load_statsbomb(cursor, stats):
    if not METADATA_FILE.exists():
        return
    metadata = json.loads(METADATA_FILE.read_text(encoding="utf-8"))
    tournaments, teams, match_map = load_maps(cursor)
    player_lookup = {}

    cursor.execute(
        """
        SELECT p.player_id, pa.normalized_name, pt.team_id
        FROM players p
        JOIN player_aliases pa ON pa.player_id = p.player_id
        LEFT JOIN player_tournaments pt ON pt.player_id = p.player_id
        """
    )
    for player_id, normalized, team_id in cursor.fetchall():
        if team_id:
            player_lookup[(team_id, normalized)] = player_id

    for coverage in metadata.get("statsbomb_coverage", []):
        season_dir = ROOT / coverage["file_path"]
        matches_path = season_dir / "matches.json"
        if not matches_path.exists():
            continue
        sb_matches = json.loads(matches_path.read_text(encoding="utf-8"))
        linked = 0
        for sb_match in sb_matches:
            canonical_match_id = match_map.get(statsbomb_match_key(sb_match))
            if not canonical_match_id:
                stats["unmatched_players"] += 1
                record_issue(cursor, "statsbomb", "unmatched_statsbomb_match", "Could not link StatsBomb match to canonical match", "match", str(sb_match.get("match_id")), sb_match)
                continue
            linked += 1
            cursor.execute("UPDATE matches SET external_statsbomb_id = %s WHERE match_id = %s", (str(sb_match["match_id"]), canonical_match_id))
            lineups_path = season_dir / "lineups" / f"{sb_match['match_id']}.json"
            events_path = season_dir / "events" / f"{sb_match['match_id']}.json"
            lineup_player_ids = {}
            if lineups_path.exists():
                for team_lineup in json.loads(lineups_path.read_text(encoding="utf-8")):
                    team_name = canonical_team_name(team_lineup["team_name"])
                    team_id = teams.get(team_name)
                    if not team_id:
                        continue
                    for item in team_lineup.get("lineup", []):
                        normalized = normalize_person_name(item["player_name"])
                        player_id = player_lookup.get((team_id, normalized))
                        if not player_id:
                            player_id = upsert_player(cursor, item["player_name"], external_statsbomb_id=str(item["player_id"]))
                            insert_alias(cursor, player_id, "statsbomb", item["player_name"])
                            player_lookup[(team_id, normalized)] = player_id
                            stats["player_aliases_resolved"] += 1
                        else:
                            insert_alias(cursor, player_id, "statsbomb", item["player_name"])
                            cursor.execute(
                                "UPDATE players SET external_statsbomb_id = COALESCE(external_statsbomb_id, %s) WHERE player_id = %s",
                                (str(item["player_id"]), player_id),
                            )
                        lineup_player_ids[item["player_id"]] = (player_id, team_id)

            aggregates = defaultdict(lambda: {
                "shots": 0,
                "shots_on_target": 0,
                "passes_attempted": 0,
                "passes_completed": 0,
                "chances_created": 0,
                "tackles": 0,
                "interceptions": 0,
            })
            if events_path.exists():
                event_rows = []
                for event in json.loads(events_path.read_text(encoding="utf-8")):
                    player = event.get("player")
                    team = event.get("team")
                    player_id = team_id = None
                    if player and player.get("id") in lineup_player_ids:
                        player_id, team_id = lineup_player_ids[player["id"]]
                    elif player and team:
                        team_id = teams.get(canonical_team_name(team["name"]))
                        if team_id:
                            player_id = player_lookup.get((team_id, normalize_person_name(player["name"])))
                    event_type = event.get("type", {}).get("name", "Unknown")
                    outcome = None
                    if event_type == "Shot":
                        outcome = event.get("shot", {}).get("outcome", {}).get("name")
                    elif event_type == "Pass":
                        outcome = event.get("pass", {}).get("outcome", {}).get("name")
                    elif event_type == "Duel":
                        outcome = event.get("duel", {}).get("outcome", {}).get("name")
                    if event.get("id"):
                        event_rows.append(
                            (
                                "statsbomb",
                                event["id"],
                                canonical_match_id,
                                player_id,
                                team_id,
                                event_type,
                                event.get("minute"),
                                event.get("second"),
                                outcome,
                                Json(event),
                            )
                        )
                    if player_id:
                        key = (player_id, canonical_match_id)
                        if event_type == "Shot":
                            aggregates[key]["shots"] += 1
                            if outcome in {"Goal", "Saved", "Saved to Post"}:
                                aggregates[key]["shots_on_target"] += 1
                        elif event_type == "Pass":
                            aggregates[key]["passes_attempted"] += 1
                            if not event.get("pass", {}).get("outcome"):
                                aggregates[key]["passes_completed"] += 1
                            if event.get("pass", {}).get("shot_assist") or event.get("pass", {}).get("goal_assist"):
                                aggregates[key]["chances_created"] += 1
                        elif event_type == "Duel" and event.get("duel", {}).get("type", {}).get("name") == "Tackle":
                            aggregates[key]["tackles"] += 1
                        elif event_type == "Interception":
                            aggregates[key]["interceptions"] += 1
                if event_rows:
                    execute_batch(
                        cursor,
                        """
                        INSERT INTO player_events (
                          source_id, external_event_id, match_id, player_id, team_id,
                          event_type, minute, second, outcome, raw_event_json
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (source_id, external_event_id) DO NOTHING
                        """,
                        event_rows,
                        page_size=1000,
                    )

            for (player_id, match_id), values in aggregates.items():
                cursor.execute(
                    """
                    INSERT INTO player_match_stats (
                      player_id, match_id, shots, shots_on_target, passes_attempted,
                      passes_completed, chances_created, tackles, interceptions, source_id
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (player_id, match_id, source_id) DO UPDATE SET
                      shots = EXCLUDED.shots,
                      shots_on_target = EXCLUDED.shots_on_target,
                      passes_attempted = EXCLUDED.passes_attempted,
                      passes_completed = EXCLUDED.passes_completed,
                      chances_created = EXCLUDED.chances_created,
                      tackles = EXCLUDED.tackles,
                      interceptions = EXCLUDED.interceptions
                    """,
                    (
                        player_id,
                        match_id,
                        values["shots"],
                        values["shots_on_target"],
                        values["passes_attempted"],
                        values["passes_completed"],
                        values["chances_created"],
                        values["tackles"],
                        values["interceptions"],
                        "statsbomb",
                    ),
                )
        cursor.execute(
            """
            INSERT INTO source_metadata (
              source_id, source_name, dataset_name, coverage_year, competition_id, season_id, match_count, file_path, notes
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (source_id, dataset_name, COALESCE(coverage_year, 0), COALESCE(competition_id, 0), COALESCE(season_id, 0))
            DO UPDATE SET match_count = EXCLUDED.match_count, file_path = EXCLUDED.file_path, downloaded_at = NOW()
            """,
            (
                "statsbomb",
                "StatsBomb Open Data",
                "matches_lineups_events",
                coverage.get("coverage_year"),
                coverage.get("competition_id"),
                coverage.get("season_id"),
                linked,
                coverage.get("file_path"),
                coverage.get("notes"),
            ),
        )


def update_quality_metrics(cursor, stats):
    cursor.execute("SELECT COUNT(*) FROM player_aliases")
    player_aliases = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(DISTINCT player_id) FROM player_match_stats WHERE source_id = 'statsbomb'")
    statsbomb_players = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM players WHERE player_id NOT IN (SELECT DISTINCT player_id FROM player_match_stats WHERE source_id = 'statsbomb')")
    no_advanced = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM data_quality_issues WHERE issue_type ILIKE '%ambiguous%'")
    ambiguous = cursor.fetchone()[0]
    cursor.execute(
        """
        UPDATE data_quality_metrics
        SET player_aliases_resolved = %s,
            unmatched_players = %s,
            ambiguous_player_matches = %s,
            players_with_statsbomb_coverage = %s,
            players_without_advanced_coverage = %s,
            conflicting_goal_records = %s,
            conflicting_appearance_records = %s,
            loaded_at = NOW()
        WHERE metric_id = 1
        """,
        (
            player_aliases,
            stats["unmatched_players"],
            ambiguous,
            statsbomb_players,
            no_advanced,
            stats["conflicting_goal_records"],
            stats["conflicting_appearance_records"],
        ),
    )


def load_player_data(database_url=None):
    database_url = database_url or os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/worldcup")
    connection = psycopg2.connect(database_url)
    stats = Counter()
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM data_quality_issues WHERE source_id IN ('fjelstul', 'statsbomb')")
                load_fjelstul(cursor, stats)
                load_statsbomb(cursor, stats)
                update_quality_metrics(cursor, stats)
        return stats
    finally:
        connection.close()


def main():
    load_dotenv(ROOT / "backend" / ".env")
    stats = load_player_data()
    print("Player data loaded")
    for key in sorted(stats):
        print(f"- {key}: {stats[key]}")


if __name__ == "__main__":
    main()
