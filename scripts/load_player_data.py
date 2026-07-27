import argparse
import csv
import json
import os
import re
import time
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import Json, execute_values

from load_database import canonical_team_name, fetch_id, normalize_person_name, upsert_player, upsert_team
from player_identity import VERIFIED_PLAYER_ALIASES

ROOT = Path(__file__).resolve().parents[1]
FJELSTUL_DIR = ROOT / "data" / "raw" / "fjelstul"
STATSBOMB_DIR = ROOT / "data" / "raw" / "statsbomb"
ESPN_2026_DIR = ROOT / "data" / "raw" / "espn_2026"
METADATA_FILE = ROOT / "data" / "raw" / "source_metadata.json"
PLAYER_CANONICAL_ALIASES = VERIFIED_PLAYER_ALIASES
BATCH_SIZE = int(os.getenv("PLAYER_LOAD_BATCH_SIZE", "1000"))
MAX_PHASE_ATTEMPTS = 3
STORE_RAW_EVENT_JSON = os.getenv("STORE_RAW_EVENT_JSON", "false").casefold() in {"1", "true", "yes", "on"}
STORE_PLAYER_EVENTS = os.getenv("STORE_PLAYER_EVENTS", "false").casefold() in {"1", "true", "yes", "on"}
STATEMENT_TIMEOUT_MS = int(os.getenv("PGSTATEMENT_TIMEOUT_MS", "300000"))


def progress(message):
    print(f"[load_player_data] {message}", flush=True)


def connect(database_url):
    return psycopg2.connect(
        database_url,
        connect_timeout=int(os.getenv("PGCONNECT_TIMEOUT", "15")),
        keepalives=1,
        keepalives_idle=int(os.getenv("PGKEEPALIVES_IDLE", "30")),
        keepalives_interval=int(os.getenv("PGKEEPALIVES_INTERVAL", "10")),
        keepalives_count=int(os.getenv("PGKEEPALIVES_COUNT", "5")),
    )


def safe_close(connection):
    if not connection:
        return
    try:
        if not connection.closed:
            connection.close()
    except psycopg2.InterfaceError:
        pass


def safe_rollback(connection):
    if not connection:
        return
    try:
        if not connection.closed:
            connection.rollback()
    except psycopg2.InterfaceError:
        pass


def execute_phase(database_url, phase_name, phase_func, stats, resume=False):
    for attempt in range(1, MAX_PHASE_ATTEMPTS + 1):
        connection = None
        try:
            progress(f"starting phase: {phase_name} (attempt {attempt}/{MAX_PHASE_ATTEMPTS})")
            connection = connect(database_url)
            with connection.cursor() as cursor:
                cursor.execute("SET statement_timeout = %s", (STATEMENT_TIMEOUT_MS,))
                result = phase_func(cursor, stats)
            connection.commit()
            progress(f"completed phase: {phase_name}; {format_phase_counts(result)}")
            return result
        except psycopg2.OperationalError as exc:
            safe_rollback(connection)
            safe_close(connection)
            if attempt >= MAX_PHASE_ATTEMPTS:
                progress(f"failed phase after retries: {phase_name}: {exc}")
                raise
            delay = 2 ** (attempt - 1)
            progress(f"database connection lost in phase {phase_name}; retrying in {delay}s")
            time.sleep(delay)
        except Exception:
            safe_rollback(connection)
            safe_close(connection)
            raise
        finally:
            safe_close(connection)


def format_phase_counts(result):
    if not result:
        return "0 rows"
    return ", ".join(f"{key}={value}" for key, value in sorted(result.items()))


def chunks(rows, size=BATCH_SIZE):
    for index in range(0, len(rows), size):
        yield index, rows[index : index + size]


def commit_cursor_connection(cursor):
    connection = getattr(cursor, "connection", None)
    if connection and not connection.closed:
        connection.commit()


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
        SELECT %s, %s, %s, %s, %s, %s, %s
        WHERE NOT EXISTS (
          SELECT 1
          FROM data_quality_issues
          WHERE source_id = %s
            AND issue_type = %s
            AND COALESCE(entity_type, '') = COALESCE(%s, '')
            AND COALESCE(external_id, '') = COALESCE(%s, '')
            AND description = %s
        )
        """,
        (
            source_id,
            issue_type,
            severity,
            entity_type,
            external_id,
            description,
            Json(raw_payload) if raw_payload is not None else None,
            source_id,
            issue_type,
            entity_type,
            external_id,
            description,
        ),
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


def preferred_position(row):
    for flag, label in (("goal_keeper", "Goalkeeper"), ("defender", "Defender"), ("midfielder", "Midfielder"), ("forward", "Forward")):
        if parse_bool(row.get(flag)):
            return label
    return None


def load_fjelstul_players_and_aliases(cursor, rows):
    player_rows = [
        (
            player_name(row),
            parse_date(row.get("birth_date")),
            preferred_position(row),
            row["player_id"],
            normalize_person_name(player_name(row)),
        )
        for row in rows
        if row.get("player_id")
    ]
    for batch_index, batch in chunks(player_rows):
        execute_values(
            cursor,
            """
            UPDATE players AS p
            SET canonical_name = v.canonical_name,
                birth_date = COALESCE(v.birth_date, p.birth_date),
                preferred_position = COALESCE(v.preferred_position, p.preferred_position),
                external_fjelstul_id = v.external_fjelstul_id
            FROM (VALUES %s) AS v(canonical_name, birth_date, preferred_position, external_fjelstul_id, normalized_name)
            JOIN player_aliases pa ON pa.normalized_name = v.normalized_name
            WHERE p.player_id = pa.player_id
              AND p.external_fjelstul_id IS NULL
              AND NOT EXISTS (
                SELECT 1 FROM players owner WHERE owner.external_fjelstul_id = v.external_fjelstul_id
              )
            """,
            batch,
            page_size=BATCH_SIZE,
        )
        execute_values(
            cursor,
            """
            INSERT INTO players (canonical_name, birth_date, preferred_position, external_fjelstul_id)
            VALUES %s
            ON CONFLICT (external_fjelstul_id) DO UPDATE SET
              canonical_name = EXCLUDED.canonical_name,
              birth_date = COALESCE(EXCLUDED.birth_date, players.birth_date),
              preferred_position = COALESCE(EXCLUDED.preferred_position, players.preferred_position)
            """,
            [row[:4] for row in batch],
            page_size=BATCH_SIZE,
        )
        progress(f"fjelstul players batch {batch_index // BATCH_SIZE + 1}: upserted {len(batch)} players")

    external_ids = [row[3] for row in player_rows]
    player_ids = {}
    if external_ids:
        cursor.execute(
            "SELECT external_fjelstul_id, player_id FROM players WHERE external_fjelstul_id = ANY(%s)",
            (external_ids,),
        )
        player_ids = {external_id: player_id for external_id, player_id in cursor.fetchall()}

    alias_rows = [
        (player_ids[row["player_id"]], "fjelstul", player_name(row), normalize_person_name(player_name(row)))
        for row in rows
        if row.get("player_id") in player_ids
    ]
    for batch_index, batch in chunks(alias_rows):
        execute_values(
            cursor,
            """
            INSERT INTO player_aliases (player_id, source_id, original_name, normalized_name)
            VALUES %s
            ON CONFLICT (source_id, normalized_name, player_id) DO NOTHING
            """,
            batch,
            page_size=BATCH_SIZE,
        )
        progress(f"fjelstul aliases batch {batch_index // BATCH_SIZE + 1}: inserted/upserted {len(batch)} aliases")
    return player_ids, {"players": len(player_rows), "aliases": len(alias_rows)}


def fetch_fjelstul_player_ids(cursor):
    cursor.execute("SELECT external_fjelstul_id, player_id FROM players WHERE external_fjelstul_id IS NOT NULL")
    return {external_id: player_id for external_id, player_id in cursor.fetchall()}


def fetch_fjelstul_match_ids(cursor):
    cursor.execute("SELECT external_fjelstul_id, match_id FROM matches WHERE external_fjelstul_id IS NOT NULL")
    return {external_id: match_id for external_id, match_id in cursor.fetchall()}


def load_fjelstul(cursor, stats, phase="all"):
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
    mens_match_source_ids = {row.get("match_id") for row in matches if is_mens_world_cup(row)}
    dependent_appearances = Counter(row.get("match_id") for row in appearances if row.get("match_id") in mens_match_source_ids)
    if phase in {"all", "players"}:
        player_ids, player_counts = load_fjelstul_players_and_aliases(cursor, players)
        stats.update({f"fjelstul_{key}": value for key, value in player_counts.items()})
        if phase == "players":
            return player_counts
    else:
        player_ids = fetch_fjelstul_player_ids(cursor)
        player_counts = {"players": len(player_ids), "aliases": 0}

    squad_rows = []
    fjelstul_match_ids = {}
    match_link_rows = []
    if phase in {"all", "squads_links"}:
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
            squad_rows.append((pid, tournaments[year], team_id, parse_int(row.get("shirt_number")), clean_text(row.get("position_name")), "squad"))
        for batch_index, batch in chunks(squad_rows):
            execute_values(
                cursor,
                """
                INSERT INTO player_tournaments (player_id, tournament_id, team_id, shirt_number, position, squad_status)
                VALUES %s
                ON CONFLICT (player_id, tournament_id, team_id) DO UPDATE SET
                  shirt_number = EXCLUDED.shirt_number,
                  position = EXCLUDED.position,
                  squad_status = EXCLUDED.squad_status
                """,
                batch,
                page_size=BATCH_SIZE,
            )
            progress(f"fjelstul squads batch {batch_index // BATCH_SIZE + 1}: upserted {len(batch)} tournament rows")
        stats["fjelstul_squad_rows"] += len(squad_rows)

        for row in matches:
            if row.get("match_id") not in mens_match_source_ids:
                continue
            key = match_key_for_fjelstul(row)
            match_id, reversed_teams, shifted_date = find_match(match_map, *key)
            if match_id:
                fjelstul_match_ids[row["match_id"]] = match_id
                match_link_rows.append((row["match_id"], match_id))
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
        if match_link_rows:
            execute_values(
                cursor,
                """
                UPDATE matches AS m
                SET external_fjelstul_id = v.external_fjelstul_id
                FROM (VALUES %s) AS v(external_fjelstul_id, match_id)
                WHERE m.match_id = v.match_id
                """,
                match_link_rows,
                page_size=BATCH_SIZE,
            )
            progress(f"fjelstul match links: updated {len(match_link_rows)} canonical matches")
        stats["fjelstul_linked_matches"] += len(match_link_rows)
        if phase == "squads_links":
            return {"squads": len(squad_rows), "matches": len(match_link_rows)}
    else:
        fjelstul_match_ids = fetch_fjelstul_match_ids(cursor)

    goal_counts = Counter()
    penalty_counts = Counter()

    # Fjelstul is authoritative only where its match is safely linked. Keep
    # OpenFootball goals for unmatched historical matches and 2026.
    linked_canonical_ids = sorted(set(fjelstul_match_ids.values()))
    if linked_canonical_ids:
        cursor.execute(
            "DELETE FROM goals WHERE source_goal_key NOT LIKE 'fjelstul:%%' AND match_id = ANY(%s)",
            (linked_canonical_ids,),
        )

    goal_rows = []
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
        goal_rows.append(
            (
                f"fjelstul:{row['goal_id']}",
                match_id,
                player_id,
                team_id,
                parse_int(row.get("minute_regulation")),
                parse_int(row.get("minute_stoppage")),
                parse_bool(row.get("penalty")),
                parse_bool(row.get("own_goal")),
            )
        )
    for batch_index, batch in chunks(goal_rows):
        execute_values(
            cursor,
            """
            INSERT INTO goals (source_goal_key, match_id, player_id, team_id, tournament_id, minute, stoppage_minute, is_penalty, is_own_goal)
            SELECT v.source_goal_key, v.match_id, v.player_id, v.team_id, m.tournament_id, v.minute, v.stoppage_minute, v.is_penalty, v.is_own_goal
            FROM (VALUES %s) AS v(source_goal_key, match_id, player_id, team_id, minute, stoppage_minute, is_penalty, is_own_goal)
            JOIN matches m ON m.match_id = v.match_id
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
            batch,
            page_size=BATCH_SIZE,
        )
        progress(f"fjelstul goals batch {batch_index // BATCH_SIZE + 1}: upserted {len(batch)} goals")
    stats["fjelstul_goal_rows"] += len(goal_rows)

    for row in penalty_kicks:
        if row.get("match_id") not in mens_match_source_ids:
            continue
        if parse_bool(row.get("converted")):
            match_id = fjelstul_match_ids.get(row.get("match_id"))
            player_id = player_ids.get(row.get("player_id"))
            if match_id and player_id:
                penalty_counts[(player_id, match_id)] += 1

    booking_rows = []
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
        booking_rows.append((row["booking_id"], match_id, player_id, team_id, parse_int(row.get("minute_regulation")), card_type, "fjelstul"))
    for batch_index, batch in chunks(booking_rows):
        execute_values(
            cursor,
            """
            INSERT INTO bookings (external_booking_id, match_id, player_id, team_id, minute, card_type, source_id)
            VALUES %s
            ON CONFLICT (source_id, external_booking_id) DO NOTHING
            """,
            batch,
            page_size=BATCH_SIZE,
        )
        progress(f"fjelstul bookings batch {batch_index // BATCH_SIZE + 1}: inserted/upserted {len(batch)} bookings")
    stats["fjelstul_booking_rows"] += len(booking_rows)

    appearance_rows = []
    stat_rows = []
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
        appearance_rows.append((player_id, match_id, team_id, started, clean_text(row.get("position_name")) == "goalkeeper", "fjelstul"))
        stat_rows.append(
            (
                player_id,
                match_id,
                goal_counts.get((player_id, match_id), 0),
                penalty_counts.get((player_id, match_id), 0),
                "fjelstul",
            )
        )
    for batch_index, batch in chunks(appearance_rows):
        execute_values(
            cursor,
            """
            INSERT INTO player_appearances (player_id, match_id, team_id, started, goalkeeper, source_id)
            VALUES %s
            ON CONFLICT (player_id, match_id, team_id, source_id) DO UPDATE SET
              started = EXCLUDED.started,
              goalkeeper = EXCLUDED.goalkeeper
            """,
            batch,
            page_size=BATCH_SIZE,
        )
        progress(f"fjelstul appearances batch {batch_index // BATCH_SIZE + 1}: upserted {len(batch)} appearances")
    for batch_index, batch in chunks(stat_rows):
        execute_values(
            cursor,
            """
            INSERT INTO player_match_stats (
              player_id, match_id, minutes_played, goals, penalties_scored,
              source_id
            )
            VALUES %s
            ON CONFLICT (player_id, match_id, source_id) DO UPDATE SET
              goals = EXCLUDED.goals,
              penalties_scored = EXCLUDED.penalties_scored
            """,
            batch,
            template="(%s, %s, NULL, %s, %s, %s)",
            page_size=BATCH_SIZE,
        )
        progress(f"fjelstul player stats batch {batch_index // BATCH_SIZE + 1}: upserted {len(batch)} stat rows")
    stats["fjelstul_appearance_rows"] += len(appearance_rows)
    stats["fjelstul_match_stat_rows"] += len(stat_rows)

    substitution_rows = []
    appearance_minute_updates = []
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
        minute = parse_int(row.get("minute_regulation"))
        substitution_rows.append((row["substitution_id"], match_id, team_id, out_id, in_id, minute, "fjelstul"))
        if in_id:
            appearance_minute_updates.append((minute, None, player_id, match_id, team_id))
        if out_id:
            appearance_minute_updates.append((None, minute, player_id, match_id, team_id))
    for batch_index, batch in chunks(substitution_rows):
        execute_values(
            cursor,
            """
            INSERT INTO substitutions (external_substitution_id, match_id, team_id, player_out_id, player_in_id, minute, source_id)
            VALUES %s
            ON CONFLICT DO NOTHING
            """,
            batch,
            page_size=BATCH_SIZE,
        )
        progress(f"fjelstul substitutions batch {batch_index // BATCH_SIZE + 1}: inserted/upserted {len(batch)} substitutions")
    for batch_index, batch in chunks(appearance_minute_updates):
        execute_values(
            cursor,
            """
            UPDATE player_appearances AS pa
            SET entered_minute = COALESCE(v.entered_minute, pa.entered_minute),
                exited_minute = COALESCE(v.exited_minute, pa.exited_minute)
            FROM (VALUES %s) AS v(entered_minute, exited_minute, player_id, match_id, team_id)
            WHERE pa.player_id = v.player_id
              AND pa.match_id = v.match_id
              AND pa.team_id = v.team_id
              AND pa.source_id = 'fjelstul'
            """,
            batch,
            page_size=BATCH_SIZE,
        )
        progress(f"fjelstul substitution minute batch {batch_index // BATCH_SIZE + 1}: updated {len(batch)} appearances")
    stats["fjelstul_substitution_rows"] += len(substitution_rows)

    metadata_rows = [
        ("fjelstul", "Fjelstul World Cup Database", dataset, len(rows), f"data/raw/fjelstul/{dataset}.csv", "Authoritative historical player dataset")
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
        )
    ]
    execute_values(
        cursor,
        """
        INSERT INTO source_metadata (source_id, source_name, dataset_name, match_count, file_path, notes)
        VALUES %s
        ON CONFLICT (source_id, dataset_name, COALESCE(coverage_year, 0), COALESCE(competition_id, 0), COALESCE(season_id, 0))
        DO UPDATE SET match_count = EXCLUDED.match_count, file_path = EXCLUDED.file_path, downloaded_at = NOW()
        """,
        metadata_rows,
        page_size=BATCH_SIZE,
    )
    return {
        "players": player_counts.get("players", 0),
        "aliases": player_counts.get("aliases", 0),
        "squads": len(squad_rows),
        "matches": len(match_link_rows),
        "goals": len(goal_rows),
        "bookings": len(booking_rows),
        "appearances": len(appearance_rows),
        "player_stats": len(stat_rows),
        "substitutions": len(substitution_rows),
        "metadata": len(metadata_rows),
    }


def statsbomb_match_key(match):
    return (
        int(match["season"]["season_name"]),
        match["match_date"],
        canonical_team_name(match["home_team"]["home_team_name"]),
        canonical_team_name(match["away_team"]["away_team_name"]),
    )


def load_statsbomb(cursor, stats, coverage_filter=None):
    if not METADATA_FILE.exists():
        return {"seasons": 0, "matches": 0, "events_parsed": 0, "events_stored": 0, "player_stats": 0}
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

    coverages = [coverage_filter] if coverage_filter else metadata.get("statsbomb_coverage", [])
    total_events_parsed = 0
    total_events_stored = 0
    total_stats = 0
    total_linked = 0
    seasons_loaded = 0
    for coverage in coverages:
        season_dir = ROOT / coverage["file_path"]
        matches_path = season_dir / "matches.json"
        if not matches_path.exists():
            continue
        sb_matches = json.loads(matches_path.read_text(encoding="utf-8"))
        linked = 0
        seasons_loaded += 1
        total_matches = len(sb_matches)
        for match_number, sb_match in enumerate(sb_matches, start=1):
            canonical_match_id = match_map.get(statsbomb_match_key(sb_match))
            if not canonical_match_id:
                stats["unmatched_players"] += 1
                record_issue(cursor, "statsbomb", "unmatched_statsbomb_match", "Could not link StatsBomb match to canonical match", "match", str(sb_match.get("match_id")), sb_match)
                percent = (match_number / total_matches * 100) if total_matches else 100
                progress(f"statsbomb season {coverage.get('coverage_year')}: match {match_number}/{total_matches} ({percent:.1f}%) skipped unmatched")
                commit_cursor_connection(cursor)
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

            aggregates = defaultdict(lambda: {"assists": 0})
            if events_path.exists():
                events = json.loads(events_path.read_text(encoding="utf-8"))
                total_events_parsed += len(events)
                for event in events:
                    if event.get("type", {}).get("name") != "Pass" or not event.get("pass", {}).get("goal_assist"):
                        continue
                    player = event.get("player")
                    team = event.get("team")
                    player_id = team_id = None
                    if player and player.get("id") in lineup_player_ids:
                        player_id, team_id = lineup_player_ids[player["id"]]
                    elif player and team:
                        team_id = teams.get(canonical_team_name(team["name"]))
                        if team_id:
                            player_id = player_lookup.get((team_id, normalize_person_name(player["name"])))
                    if player_id:
                        aggregates[(player_id, canonical_match_id)]["assists"] += 1

            stat_rows = [
                (
                    player_id,
                    match_id,
                    values["assists"],
                    "statsbomb",
                )
                for (player_id, match_id), values in aggregates.items()
            ]
            if stat_rows:
                execute_values(
                    cursor,
                    """
                    INSERT INTO player_match_stats (
                      player_id, match_id, assists, source_id
                    )
                    VALUES %s
                    ON CONFLICT (player_id, match_id, source_id) DO UPDATE SET
                      assists = EXCLUDED.assists
                    """,
                    stat_rows,
                    page_size=BATCH_SIZE,
                )
                total_stats += len(stat_rows)
            percent = (match_number / total_matches * 100) if total_matches else 100
            progress(
                f"statsbomb season {coverage.get('coverage_year')}: match {match_number}/{total_matches} "
                f"({percent:.1f}%) linked={linked}, events_parsed={total_events_parsed}, "
                f"events_stored={total_events_stored}, player_stats={total_stats}"
            )
            commit_cursor_connection(cursor)
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
        total_linked += linked
        progress(
            f"statsbomb season {coverage.get('coverage_year')}: linked_matches={linked}, "
            f"events_parsed={total_events_parsed}, events_stored={total_events_stored}, player_stats={total_stats}"
        )
    return {"seasons": seasons_loaded, "matches": total_linked, "events_parsed": total_events_parsed, "events_stored": total_events_stored, "player_stats": total_stats}


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
        return {"linked_matches": 0, "appearances": 0, "fallback_goals": 0}

    scoreboard = json.loads(scoreboard_path.read_text(encoding="utf-8"))
    tournaments, teams, match_map = load_maps(cursor)
    tournament_id = tournaments.get(2026)
    if not tournament_id:
        record_issue(cursor, "espn_2026", "missing_tournament", "Cannot load ESPN 2026 data because tournament 2026 is not loaded", "tournament", "2026", severity="error")
        return {"linked_matches": 0, "appearances": 0, "fallback_goals": 0}

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
                      player_id, match_id, goals, penalties_scored, assists, source_id
                    )
                    VALUES (%s, %s, %s, NULL, %s, %s)
                    ON CONFLICT (player_id, match_id, source_id) DO UPDATE SET
                      goals = EXCLUDED.goals,
                      assists = EXCLUDED.assists
                    """,
                    (
                        player_id,
                        match_id,
                        parse_stat_int(item.get("stats"), "totalGoals"),
                        parse_stat_int(item.get("stats"), "goalAssists"),
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
    return {"linked_matches": linked, "appearances": appearances_loaded, "fallback_goals": goal_events_loaded}


def update_quality_metrics(cursor, stats):
    cursor.execute("SELECT COUNT(*) FROM player_aliases")
    player_aliases = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(DISTINCT player_id) FROM player_match_stats WHERE source_id = 'statsbomb' AND assists IS NOT NULL")
    statsbomb_players = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM players WHERE player_id NOT IN (SELECT DISTINCT player_id FROM player_match_stats WHERE source_id = 'statsbomb' AND assists IS NOT NULL)")
    no_statsbomb_assists = cursor.fetchone()[0]
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
            no_statsbomb_assists,
            stats["conflicting_goal_records"],
            stats["conflicting_appearance_records"],
        ),
    )
    return {
        "player_aliases": player_aliases,
        "statsbomb_players": statsbomb_players,
        "players_without_statsbomb_assists": no_statsbomb_assists,
        "ambiguous_issues": ambiguous,
    }


def clear_source_quality_issues(cursor, stats):
    cursor.execute("DELETE FROM data_quality_issues WHERE source_id IN ('fjelstul', 'statsbomb', 'espn_2026')")
    return {"deleted_quality_issues": cursor.rowcount}


def clear_statsbomb_player_events_when_disabled(cursor, stats):
    cursor.execute("DELETE FROM player_events WHERE source_id = %s", ("statsbomb",))
    return {"deleted_player_events": cursor.rowcount}


def clear_statsbomb_match_stats(cursor, stats):
    cursor.execute("DELETE FROM player_match_stats WHERE source_id = %s", ("statsbomb",))
    return {"deleted_statsbomb_match_stats": cursor.rowcount}


def statsbomb_coverages():
    if not METADATA_FILE.exists():
        return []
    metadata = json.loads(METADATA_FILE.read_text(encoding="utf-8"))
    return metadata.get("statsbomb_coverage", [])


def load_player_data(database_url=None, resume=False):
    database_url = database_url or os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/worldcup")
    stats = Counter()
    phases = []
    if not resume:
        phases.append(("clear source quality issues", clear_source_quality_issues))
    phases.extend(
        [
            ("Fjelstul players and aliases", lambda cursor, stats: load_fjelstul(cursor, stats, phase="players")),
            ("Fjelstul squads and match-player links", lambda cursor, stats: load_fjelstul(cursor, stats, phase="squads_links")),
            ("Fjelstul appearances, goals, bookings, and substitutions", lambda cursor, stats: load_fjelstul(cursor, stats, phase="events")),
        ]
    )
    phases.append(("clear StatsBomb player_events", clear_statsbomb_player_events_when_disabled))
    if not resume:
        phases.append(("clear StatsBomb player_match_stats", clear_statsbomb_match_stats))
    for coverage in statsbomb_coverages():
        label = f"StatsBomb season {coverage.get('coverage_year') or coverage.get('season_id')}"
        phases.append((label, lambda cursor, stats, coverage=coverage: load_statsbomb(cursor, stats, coverage)))
    phases.append(("ESPN 2026 data", load_espn_2026))
    phases.append(("final quality metrics", update_quality_metrics))

    for phase_name, phase_func in phases:
        execute_phase(database_url, phase_name, phase_func, stats, resume=resume)
    return stats


def main():
    parser = argparse.ArgumentParser(description="Load player data into an existing World Cup database.")
    parser.add_argument("--resume", action="store_true", help="Continue an interrupted idempotent load without clearing source quality issues.")
    args = parser.parse_args()
    load_dotenv(ROOT / "backend" / ".env")
    stats = load_player_data(resume=args.resume)
    print("Player data loaded")
    for key in sorted(stats):
        print(f"- {key}: {stats[key]}")


if __name__ == "__main__":
    main()
