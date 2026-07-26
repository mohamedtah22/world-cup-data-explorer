import csv
import json
import os
import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import Json, execute_batch

from load_database import canonical_team_name, fetch_id, normalize_person_name, upsert_player, upsert_team

ROOT = Path(__file__).resolve().parents[1]
FJELSTUL_DIR = ROOT / "data" / "raw" / "fjelstul"
STATSBOMB_DIR = ROOT / "data" / "raw" / "statsbomb"
ESPN_2026_DIR = ROOT / "data" / "raw" / "espn_2026"
METADATA_FILE = ROOT / "data" / "raw" / "source_metadata.json"
PLAYER_CANONICAL_ALIASES = {
    "lionel andrés messi cuccittini": "lionel messi",
}


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


def parse_stat_int(stats, name):
    for stat in stats or []:
        if stat.get("name") == name:
            value = stat.get("value")
            if value is None:
                return None
            return int(value)
    return None


def parse_display_minute(value):
    text = clean_text(value)
    if not text:
        return None
    text = text.replace("'", "")
    if "+" in text:
        text = text.split("+", 1)[0]
    try:
        return int(text)
    except ValueError:
        return None


def parse_date(value):
    value = clean_text(value)
    return date.fromisoformat(value) if value else None


def tournament_year(row):
    match = re.search(r"(19|20)\d{2}", row.get("tournament_name", "") or row.get("tournament_id", ""))
    return int(match.group(0)) if match else None


def is_mens_world_cup(row):
    name = row.get("tournament_name") or row.get("tournament_id") or ""
    return "Women's" not in name and "Women" not in name


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


def find_match(match_map, year, match_date, home, away, allow_adjacent_date=False):
    dates = [match_date]
    if allow_adjacent_date:
        base = date.fromisoformat(match_date)
        dates.extend([(base - timedelta(days=1)).isoformat(), (base + timedelta(days=1)).isoformat()])
    home = canonical_team_name(home)
    away = canonical_team_name(away)
    for candidate_date in dates:
        key = (year, candidate_date, home, away)
        if key in match_map:
            return match_map[key], False, candidate_date != match_date
        reversed_key = (key[0], key[1], key[3], key[2])
        if reversed_key in match_map:
            return match_map[reversed_key], True, candidate_date != match_date
    return None, False, False


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
    mens_match_source_ids = {row.get("match_id") for row in matches if is_mens_world_cup(row)}
    dependent_appearances = Counter(row.get("match_id") for row in appearances if row.get("match_id") in mens_match_source_ids)

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
        if not is_mens_world_cup(row):
            continue
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
        if row.get("match_id") not in mens_match_source_ids:
            continue
        key = match_key_for_fjelstul(row)
        match_id, reversed_teams, shifted_date = find_match(match_map, *key)
        if match_id:
            fjelstul_match_ids[row["match_id"]] = match_id
            cursor.execute("UPDATE matches SET external_fjelstul_id = %s WHERE match_id = %s", (row["match_id"], match_id))
            if reversed_teams:
                record_issue(
                    cursor,
                    "fjelstul",
                    "reversed_match_link_resolved",
                    "Linked Fjelstul match after detecting reversed home/away teams",
                    "match",
                    row.get("match_id"),
                    row,
                    severity="info",
                )
            if shifted_date:
                record_issue(cursor, "fjelstul", "date_shift_match_link_resolved", "Linked Fjelstul match after adjacent-date normalization", "match", row.get("match_id"), row, severity="info")
        else:
            skipped = dependent_appearances.get(row.get("match_id"), 0)
            stats["unmatched_fjelstul_matches"] += 1
            stats["skipped_fjelstul_appearances"] += skipped
            record_issue(cursor, "fjelstul", "unmatched_match", f"Could not link Fjelstul match to canonical match; {skipped} dependent appearances skipped", "match", row.get("match_id"), row)

    goal_counts = Counter()
    penalty_counts = Counter()
    card_counts = Counter()

    # Fjelstul is authoritative only where its match is safely linked. Keep
    # OpenFootball goals for unmatched historical matches and 2026.
    linked_canonical_ids = sorted(set(fjelstul_match_ids.values()))
    if linked_canonical_ids:
        cursor.execute(
            "DELETE FROM goals WHERE source_goal_key NOT LIKE 'fjelstul:%%' AND match_id = ANY(%s)",
            (linked_canonical_ids,),
        )

    for row in goals:
        if row.get("match_id") not in mens_match_source_ids:
            continue
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
        if row.get("match_id") not in mens_match_source_ids:
            continue
        if parse_bool(row.get("converted")):
            match_id = fjelstul_match_ids.get(row.get("match_id"))
            player_id = player_ids.get(row.get("player_id"))
            if match_id and player_id:
                penalty_counts[(player_id, match_id)] += 1

    for row in bookings:
        if row.get("match_id") not in mens_match_source_ids:
            continue
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
        if row.get("match_id") not in mens_match_source_ids:
            continue
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
        if row.get("match_id") not in mens_match_source_ids:
            continue
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
            ON CONFLICT DO NOTHING
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
                                "SELECT player_id FROM players WHERE external_statsbomb_id = %s",
                                (str(item["player_id"]),),
                            )
                            owner = cursor.fetchone()
                            if owner and owner[0] != player_id:
                                record_issue(cursor, "statsbomb", "ambiguous_statsbomb_player_id", "StatsBomb external player ID is already linked to another canonical player", "player", str(item["player_id"]), item)
                            else:
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


def parse_espn_clock(item):
    for play in item.get("plays") or []:
        if play.get("substitution"):
            return parse_display_minute((play.get("clock") or {}).get("displayValue"))
    return None


def upsert_espn_player(cursor, teams, team_id, item):
    athlete = item.get("athlete") or {}
    external_id = str(athlete.get("id") or "").strip()
    name = clean_text(athlete.get("fullName")) or clean_text(athlete.get("displayName")) or "Unknown player"
    normalized = normalize_person_name(name)
    lookup_normalized = PLAYER_CANONICAL_ALIASES.get(normalized, normalized)

    if external_id:
        cursor.execute(
            "SELECT player_id FROM player_external_ids WHERE source_id = %s AND external_player_id = %s",
            ("espn_2026", external_id),
        )
        row = cursor.fetchone()
        if row:
            player_id = row[0]
        else:
            cursor.execute(
                """
                SELECT p.player_id
                FROM players p
                JOIN player_aliases pa ON pa.player_id = p.player_id
                LEFT JOIN player_tournaments pt ON pt.player_id = p.player_id
                WHERE pa.normalized_name = %s AND (pt.team_id = %s OR pt.team_id IS NULL)
                ORDER BY CASE WHEN pt.team_id = %s THEN 0 ELSE 1 END
                LIMIT 1
                """,
                (lookup_normalized, team_id, team_id),
            )
            existing = cursor.fetchone()
            if existing:
                player_id = existing[0]
            else:
                player_id = fetch_id(
                    cursor,
                    "INSERT INTO players (canonical_name) VALUES (%s) RETURNING player_id",
                    (name,),
                )
            cursor.execute(
                """
                INSERT INTO player_external_ids (source_id, external_player_id, player_id, original_name, team_id)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (source_id, external_player_id) DO UPDATE SET
                  player_id = EXCLUDED.player_id,
                  original_name = EXCLUDED.original_name,
                  team_id = EXCLUDED.team_id
                """,
                ("espn_2026", external_id, player_id, name, team_id),
            )
    else:
        cursor.execute(
            """
            SELECT p.player_id
            FROM players p
            JOIN player_aliases pa ON pa.player_id = p.player_id
            JOIN player_tournaments pt ON pt.player_id = p.player_id
            WHERE pt.team_id = %s AND pa.normalized_name = %s
            LIMIT 1
            """,
            (team_id, lookup_normalized),
        )
        row = cursor.fetchone()
        player_id = row[0] if row else fetch_id(cursor, "INSERT INTO players (canonical_name) VALUES (%s) RETURNING player_id", (name,))

    insert_alias(cursor, player_id, "espn_2026", name)
    for alias in (athlete.get("displayName"), athlete.get("shortName"), athlete.get("lastName")):
        if clean_text(alias):
            insert_alias(cursor, player_id, "espn_2026", alias)
    position = (item.get("position") or {}).get("displayName") or (item.get("position") or {}).get("name")
    return player_id, name, position, parse_int(item.get("jersey")), external_id


def reconcile_espn_openfootball_goals(cursor):
    cursor.execute(
        """
        SELECT g.goal_id, g.team_id, p.canonical_name
        FROM goals g
        JOIN matches m ON m.match_id = g.match_id
        JOIN tournaments tr ON tr.tournament_id = m.tournament_id
        JOIN players p ON p.player_id = g.player_id
        WHERE tr.year = 2026
          AND g.source_goal_key NOT LIKE 'fjelstul:%%'
          AND g.source_goal_key NOT LIKE 'espn_2026:%%'
        """
    )
    for goal_id, team_id, scorer_name in cursor.fetchall():
        normalized = normalize_person_name(scorer_name)
        cursor.execute(
            """
            SELECT DISTINCT pa.player_id
            FROM player_aliases pa
            JOIN player_tournaments pt ON pt.player_id = pa.player_id
            WHERE pa.source_id = 'espn_2026'
              AND pa.normalized_name = %s
              AND pt.team_id = %s
            """,
            (normalized, team_id),
        )
        candidates = [row[0] for row in cursor.fetchall()]
        if len(candidates) == 1:
            cursor.execute("UPDATE goals SET player_id = %s WHERE goal_id = %s", (candidates[0], goal_id))
    cursor.execute(
        """
        DELETE FROM players p
        WHERE NOT EXISTS (SELECT 1 FROM player_tournaments pt WHERE pt.player_id = p.player_id)
          AND NOT EXISTS (SELECT 1 FROM player_appearances pa WHERE pa.player_id = p.player_id)
          AND NOT EXISTS (SELECT 1 FROM goals g WHERE g.player_id = p.player_id)
          AND NOT EXISTS (SELECT 1 FROM player_match_stats pms WHERE pms.player_id = p.player_id)
        """
    )


def load_espn_2026(cursor, stats):
    scoreboard_path = ESPN_2026_DIR / "scoreboard_20260611_20260719.json"
    summaries_dir = ESPN_2026_DIR / "summaries"
    if not scoreboard_path.exists() or not summaries_dir.exists():
        return

    scoreboard = json.loads(scoreboard_path.read_text(encoding="utf-8"))
    tournaments, teams, match_map = load_maps(cursor)
    tournament_id = tournaments.get(2026)
    if not tournament_id:
        record_issue(cursor, "espn_2026", "missing_tournament", "Cannot load ESPN 2026 data because tournament 2026 is not loaded", "tournament", "2026", severity="error")
        return

    event_match = {}
    event_team_ids = {}
    linked = 0
    for event in scoreboard.get("events", []):
        competitions = event.get("competitions") or []
        if not competitions:
            continue
        competition = competitions[0]
        status = (competition.get("status") or {}).get("type") or {}
        if not status.get("completed"):
            continue
        competitors = competition.get("competitors") or []
        home = next((row for row in competitors if row.get("homeAway") == "home"), None)
        away = next((row for row in competitors if row.get("homeAway") == "away"), None)
        if not home or not away:
            record_issue(cursor, "espn_2026", "missing_match_teams", "ESPN event has no clear home/away competitors", "match", str(event.get("id")), event)
            continue
        match_date = (competition.get("date") or event.get("date") or "")[:10]
        home_name = canonical_team_name((home.get("team") or {}).get("displayName"))
        away_name = canonical_team_name((away.get("team") or {}).get("displayName"))
        match_id, reversed_teams, shifted_date = find_match(match_map, 2026, match_date, home_name, away_name, allow_adjacent_date=True)
        if not match_id:
            record_issue(cursor, "espn_2026", "unmatched_espn_match", "Could not link ESPN event to canonical OpenFootball match", "match", str(event.get("id")), event)
            continue
        linked += 1
        home_team_id = teams.get(home_name)
        away_team_id = teams.get(away_name)
        event_id = str(event["id"])
        event_match[event_id] = match_id
        event_team_ids[event_id] = {
            str(home["team"]["id"]): home_team_id,
            str(away["team"]["id"]): away_team_id,
            home_name: home_team_id,
            away_name: away_team_id,
        }
        if reversed_teams:
            record_issue(cursor, "espn_2026", "reversed_match_link_resolved", "Linked ESPN match after detecting reversed home/away teams", "match", event_id, event, severity="info")
        if shifted_date:
            record_issue(cursor, "espn_2026", "date_shift_match_link_resolved", "Linked ESPN match after adjacent-date normalization", "match", event_id, event, severity="info")
        if home.get("score") is not None and away.get("score") is not None:
            cursor.execute(
                """
                UPDATE matches
                SET home_score = COALESCE(home_score, %s),
                    away_score = COALESCE(away_score, %s)
                WHERE match_id = %s
                """,
                (int(home["score"]), int(away["score"]), match_id),
            )

    appearances_loaded = 0
    goal_events_loaded = 0
    for summary_file in sorted(summaries_dir.glob("*.json")):
        event_id = summary_file.stem
        match_id = event_match.get(event_id)
        if not match_id:
            continue
        summary = json.loads(summary_file.read_text(encoding="utf-8"))
        team_lookup = event_team_ids.get(event_id, {})
        cursor.execute("SELECT COUNT(*) FROM goals WHERE match_id = %s", (match_id,))
        match_already_has_goals = cursor.fetchone()[0] > 0

        for roster in summary.get("rosters") or []:
            espn_team = roster.get("team") or {}
            team_id = team_lookup.get(str(espn_team.get("id"))) or teams.get(canonical_team_name(espn_team.get("displayName")))
            if not team_id:
                record_issue(cursor, "espn_2026", "unmatched_espn_team", "Could not map ESPN roster team", "team", str(espn_team.get("id")), roster)
                continue
            for item in roster.get("roster") or []:
                if parse_stat_int(item.get("stats"), "appearances") != 1:
                    continue
                player_id, _, position, shirt_number, external_id = upsert_espn_player(cursor, teams, team_id, item)
                cursor.execute(
                    """
                    INSERT INTO player_tournaments (player_id, tournament_id, team_id, shirt_number, position, squad_status)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (player_id, tournament_id, team_id) DO UPDATE SET
                      shirt_number = COALESCE(EXCLUDED.shirt_number, player_tournaments.shirt_number),
                      position = COALESCE(EXCLUDED.position, player_tournaments.position)
                    """,
                    (player_id, tournament_id, team_id, shirt_number, position, "squad"),
                )
                entered = parse_espn_clock(item) if item.get("subbedIn") else None
                exited = parse_espn_clock(item) if item.get("subbedOut") else None
                cursor.execute(
                    """
                    INSERT INTO player_appearances (player_id, match_id, team_id, started, entered_minute, exited_minute, goalkeeper, source_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (player_id, match_id, team_id, source_id) DO UPDATE SET
                      started = EXCLUDED.started,
                      entered_minute = EXCLUDED.entered_minute,
                      exited_minute = EXCLUDED.exited_minute,
                      goalkeeper = EXCLUDED.goalkeeper
                    """,
                    (player_id, match_id, team_id, bool(item.get("starter")), entered, exited, (position or "").casefold() == "goalkeeper", "espn_2026"),
                )
                appearances_loaded += 1
                cursor.execute(
                    """
                    INSERT INTO player_match_stats (
                      player_id, match_id, goals, penalties_scored, assists, shots, shots_on_target,
                      yellow_cards, red_cards, source_id
                    )
                    VALUES (%s, %s, %s, NULL, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (player_id, match_id, source_id) DO UPDATE SET
                      goals = EXCLUDED.goals,
                      assists = EXCLUDED.assists,
                      shots = EXCLUDED.shots,
                      shots_on_target = EXCLUDED.shots_on_target,
                      yellow_cards = EXCLUDED.yellow_cards,
                      red_cards = EXCLUDED.red_cards
                    """,
                    (
                        player_id,
                        match_id,
                        parse_stat_int(item.get("stats"), "totalGoals"),
                        parse_stat_int(item.get("stats"), "goalAssists"),
                        parse_stat_int(item.get("stats"), "totalShots"),
                        parse_stat_int(item.get("stats"), "shotsOnTarget"),
                        parse_stat_int(item.get("stats"), "yellowCards"),
                        parse_stat_int(item.get("stats"), "redCards"),
                        "espn_2026",
                    ),
                )
                for play in item.get("plays") or []:
                    external_play_id = play.get("id")
                    if not external_play_id:
                        continue
                    minute = parse_espn_clock({"plays": [play]}) or parse_display_minute((play.get("clock") or {}).get("displayValue"))
                    if play.get("yellowCard") or play.get("redCard"):
                        cursor.execute(
                            """
                            INSERT INTO bookings (external_booking_id, match_id, player_id, team_id, minute, card_type, source_id)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (source_id, external_booking_id) DO NOTHING
                            """,
                            (str(external_play_id), match_id, player_id, team_id, minute, "red" if play.get("redCard") else "yellow", "espn_2026"),
                        )
                    if play.get("substitution") and item.get("subbedIn"):
                        out_id = None
                        subbed_for = item.get("subbedInFor") or {}
                        out_external = str(((subbed_for.get("athlete") or {}).get("id")) or "").strip()
                        if out_external:
                            cursor.execute("SELECT player_id FROM player_external_ids WHERE source_id = %s AND external_player_id = %s", ("espn_2026", out_external))
                            row = cursor.fetchone()
                            out_id = row[0] if row else None
                        cursor.execute(
                            """
                            INSERT INTO substitutions (external_substitution_id, match_id, team_id, player_out_id, player_in_id, minute, source_id)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT DO NOTHING
                            """,
                            (f"{event_id}:{external_play_id}", match_id, team_id, out_id, player_id, minute, "espn_2026"),
                        )

        if not match_already_has_goals:
            for event in summary.get("keyEvents") or []:
                event_type = (event.get("type") or {}).get("type") or ""
                if event_type != "goal":
                    continue
                participants = event.get("participants") or []
                athlete = (participants[0].get("athlete") if participants else {}) or {}
                external_id = str(athlete.get("id") or "").strip()
                player_id = None
                if external_id:
                    cursor.execute("SELECT player_id FROM player_external_ids WHERE source_id = %s AND external_player_id = %s", ("espn_2026", external_id))
                    row = cursor.fetchone()
                    player_id = row[0] if row else None
                team_id = team_lookup.get(str((event.get("team") or {}).get("id"))) or teams.get(canonical_team_name((event.get("team") or {}).get("displayName")))
                if not team_id:
                    continue
                minute = parse_display_minute((event.get("clock") or {}).get("displayValue"))
                cursor.execute(
                    """
                    INSERT INTO goals (source_goal_key, match_id, player_id, team_id, tournament_id, minute, is_penalty, is_own_goal)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (source_goal_key) DO UPDATE SET
                      player_id = EXCLUDED.player_id,
                      team_id = EXCLUDED.team_id,
                      minute = EXCLUDED.minute,
                      is_penalty = EXCLUDED.is_penalty,
                      is_own_goal = EXCLUDED.is_own_goal
                    """,
                    (f"espn_2026:{event_id}:goal:{event.get('id')}", match_id, player_id, team_id, tournament_id, minute, bool(event.get("penaltyKick")), bool(event.get("ownGoal"))),
                )
                goal_events_loaded += 1

    stats["espn_2026_appearances"] = appearances_loaded
    stats["espn_2026_fallback_goals"] = goal_events_loaded
    reconcile_espn_openfootball_goals(cursor)

    if METADATA_FILE.exists():
        metadata = json.loads(METADATA_FILE.read_text(encoding="utf-8"))
        for coverage in metadata.get("espn_2026_coverage", []):
            cursor.execute(
                """
                INSERT INTO source_metadata (
                  source_id, source_name, dataset_name, coverage_year, match_count, file_path, notes
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (source_id, dataset_name, COALESCE(coverage_year, 0), COALESCE(competition_id, 0), COALESCE(season_id, 0))
                DO UPDATE SET match_count = EXCLUDED.match_count, file_path = EXCLUDED.file_path, notes = EXCLUDED.notes, downloaded_at = NOW()
                """,
                (
                    coverage.get("source_id"),
                    coverage.get("source_name"),
                    coverage.get("dataset_name"),
                    coverage.get("coverage_year"),
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
                cursor.execute("DELETE FROM data_quality_issues WHERE source_id IN ('fjelstul', 'statsbomb', 'espn_2026')")
                load_fjelstul(cursor, stats)
                load_statsbomb(cursor, stats)
                load_espn_2026(cursor, stats)
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
