import argparse
import os
from collections import defaultdict

import psycopg2
from dotenv import load_dotenv

from load_database import normalize_person_name
from load_player_data import ROOT, connect, progress, safe_close, safe_rollback

VERIFIED_ALIAS_TARGETS = {
    "messi": "lionel messi",
}


def fetchall(cursor, sql, params=()):
    cursor.execute(sql, params)
    return cursor.fetchall()


def player_facts(cursor):
    rows = fetchall(
        cursor,
        """
        SELECT p.player_id, p.canonical_name, p.birth_date, p.external_fjelstul_id, p.external_statsbomb_id,
               ARRAY_REMOVE(ARRAY_AGG(DISTINCT pa.normalized_name), NULL) AS aliases,
               ARRAY_REMOVE(ARRAY_AGG(DISTINCT pt.team_id), NULL) AS teams,
               ARRAY_REMOVE(ARRAY_AGG(DISTINCT pt.tournament_id), NULL) AS tournaments,
               ARRAY_REMOVE(ARRAY_AGG(DISTINCT app.match_id), NULL) AS matches
        FROM players p
        LEFT JOIN player_aliases pa ON pa.player_id = p.player_id
        LEFT JOIN player_tournaments pt ON pt.player_id = p.player_id
        LEFT JOIN player_appearances app ON app.player_id = p.player_id
        GROUP BY p.player_id
        """,
    )
    facts = {}
    for row in rows:
        player_id, name, birth_date, fjelstul_id, statsbomb_id, aliases, teams, tournaments, matches = row
        normalized = normalize_person_name(name)
        facts[player_id] = {
            "player_id": player_id,
            "name": name,
            "normalized": normalized,
            "birth_date": birth_date,
            "external_ids": {value for value in (fjelstul_id, statsbomb_id) if value},
            "aliases": set(aliases or []) | {normalized},
            "teams": set(teams or []),
            "tournaments": set(tournaments or []),
            "matches": set(matches or []),
        }
    return facts


def has_supporting_evidence(left, right):
    if left["external_ids"] & right["external_ids"]:
        return True
    if left["birth_date"] and right["birth_date"] and left["birth_date"] == right["birth_date"]:
        return True
    if left["teams"] & right["teams"] and (left["tournaments"] & right["tournaments"] or left["matches"] & right["matches"]):
        return True
    if left["matches"] & right["matches"]:
        return True
    return False


def candidate_groups(cursor):
    facts = player_facts(cursor)
    by_normalized = defaultdict(list)
    for fact in facts.values():
        keys = set(fact["aliases"]) | {fact["normalized"]}
        for alias, target in VERIFIED_ALIAS_TARGETS.items():
            if alias in keys:
                keys.add(target)
        for key in keys:
            by_normalized[key].append(fact["player_id"])

    groups = []
    for key, player_ids in sorted(by_normalized.items()):
        unique_ids = sorted(set(player_ids))
        if len(unique_ids) < 2:
            continue
        supported = []
        for player_id in unique_ids:
            fact = facts[player_id]
            if key == fact["normalized"] or key in fact["aliases"] or any(alias in fact["aliases"] and target == key for alias, target in VERIFIED_ALIAS_TARGETS.items()):
                supported.append(player_id)
        if len(supported) < 2:
            continue
        if any(has_supporting_evidence(facts[a], facts[b]) for index, a in enumerate(supported) for b in supported[index + 1 :]):
            groups.append((key, supported))
    return groups, facts


def choose_canonical(player_ids, facts):
    def score(player_id):
        fact = facts[player_id]
        return (
            1 if fact["external_ids"] else 0,
            len(fact["matches"]),
            len(fact["tournaments"]),
            len(fact["name"].split()),
            -player_id,
        )

    return max(player_ids, key=score)


def merge_players(cursor, target_id, duplicate_id):
    cursor.execute(
        """
        UPDATE players target
        SET external_fjelstul_id = COALESCE(target.external_fjelstul_id, duplicate.external_fjelstul_id),
            external_statsbomb_id = COALESCE(target.external_statsbomb_id, duplicate.external_statsbomb_id),
            birth_date = COALESCE(target.birth_date, duplicate.birth_date),
            preferred_position = COALESCE(target.preferred_position, duplicate.preferred_position)
        FROM players duplicate
        WHERE target.player_id = %s
          AND duplicate.player_id = %s
        """,
        (target_id, duplicate_id),
    )

    cursor.execute(
        """
        INSERT INTO player_aliases (player_id, source_id, original_name, normalized_name)
        SELECT %s, source_id, original_name, normalized_name
        FROM player_aliases
        WHERE player_id = %s
        ON CONFLICT (source_id, normalized_name, player_id) DO NOTHING
        """,
        (target_id, duplicate_id),
    )
    cursor.execute("DELETE FROM player_aliases WHERE player_id = %s", (duplicate_id,))

    cursor.execute(
        """
        UPDATE player_external_ids e
        SET player_id = %s
        WHERE player_id = %s
          AND NOT EXISTS (
            SELECT 1 FROM player_external_ids existing
            WHERE existing.source_id = e.source_id
              AND existing.external_player_id = e.external_player_id
              AND existing.player_id = %s
          )
        """,
        (target_id, duplicate_id, target_id),
    )
    cursor.execute("DELETE FROM player_external_ids WHERE player_id = %s", (duplicate_id,))

    cursor.execute(
        """
        INSERT INTO player_tournaments (player_id, tournament_id, team_id, shirt_number, position, squad_status)
        SELECT %s, tournament_id, team_id, shirt_number, position, squad_status
        FROM player_tournaments
        WHERE player_id = %s
        ON CONFLICT (player_id, tournament_id, team_id) DO UPDATE SET
          shirt_number = COALESCE(player_tournaments.shirt_number, EXCLUDED.shirt_number),
          position = COALESCE(player_tournaments.position, EXCLUDED.position),
          squad_status = COALESCE(player_tournaments.squad_status, EXCLUDED.squad_status)
        """,
        (target_id, duplicate_id),
    )
    cursor.execute("DELETE FROM player_tournaments WHERE player_id = %s", (duplicate_id,))

    cursor.execute(
        """
        INSERT INTO player_appearances (
          player_id, match_id, team_id, started, entered_minute, exited_minute,
          minutes_played, captain, goalkeeper, source_id
        )
        SELECT %s, match_id, team_id, started, entered_minute, exited_minute,
               minutes_played, captain, goalkeeper, source_id
        FROM player_appearances
        WHERE player_id = %s
        ON CONFLICT (player_id, match_id, team_id, source_id) DO UPDATE SET
          started = COALESCE(player_appearances.started, EXCLUDED.started),
          entered_minute = COALESCE(player_appearances.entered_minute, EXCLUDED.entered_minute),
          exited_minute = COALESCE(player_appearances.exited_minute, EXCLUDED.exited_minute),
          minutes_played = COALESCE(player_appearances.minutes_played, EXCLUDED.minutes_played),
          captain = COALESCE(player_appearances.captain, EXCLUDED.captain),
          goalkeeper = COALESCE(player_appearances.goalkeeper, EXCLUDED.goalkeeper)
        """,
        (target_id, duplicate_id),
    )
    cursor.execute("DELETE FROM player_appearances WHERE player_id = %s", (duplicate_id,))

    cursor.execute("UPDATE goals SET player_id = %s WHERE player_id = %s", (target_id, duplicate_id))

    cursor.execute(
        """
        INSERT INTO player_match_stats (
          player_id, match_id, minutes_played, goals, penalties_scored, assists,
          shots, shots_on_target, passes_attempted, passes_completed,
          chances_created, tackles, interceptions, yellow_cards, red_cards, source_id
        )
        SELECT %s, match_id, minutes_played, goals, penalties_scored, assists,
               shots, shots_on_target, passes_attempted, passes_completed,
               chances_created, tackles, interceptions, yellow_cards, red_cards, source_id
        FROM player_match_stats
        WHERE player_id = %s
        ON CONFLICT (player_id, match_id, source_id) DO UPDATE SET
          minutes_played = COALESCE(player_match_stats.minutes_played, EXCLUDED.minutes_played),
          goals = GREATEST(COALESCE(player_match_stats.goals, 0), COALESCE(EXCLUDED.goals, 0)),
          penalties_scored = GREATEST(COALESCE(player_match_stats.penalties_scored, 0), COALESCE(EXCLUDED.penalties_scored, 0)),
          assists = GREATEST(COALESCE(player_match_stats.assists, 0), COALESCE(EXCLUDED.assists, 0))
        """,
        (target_id, duplicate_id),
    )
    cursor.execute("DELETE FROM player_match_stats WHERE player_id = %s", (duplicate_id,))

    cursor.execute("UPDATE bookings SET player_id = %s WHERE player_id = %s", (target_id, duplicate_id))
    cursor.execute(
        """
        INSERT INTO substitutions (external_substitution_id, match_id, team_id, player_out_id, player_in_id, minute, source_id)
        SELECT external_substitution_id, match_id, team_id,
               CASE WHEN player_out_id = %s THEN %s ELSE player_out_id END,
               CASE WHEN player_in_id = %s THEN %s ELSE player_in_id END,
               minute, source_id
        FROM substitutions
        WHERE player_out_id = %s OR player_in_id = %s
        ON CONFLICT DO NOTHING
        """,
        (duplicate_id, target_id, duplicate_id, target_id, duplicate_id, duplicate_id),
    )
    cursor.execute("DELETE FROM substitutions WHERE player_out_id = %s OR player_in_id = %s", (duplicate_id, duplicate_id))
    cursor.execute("UPDATE player_events SET player_id = %s WHERE player_id = %s", (target_id, duplicate_id))
    cursor.execute("DELETE FROM players WHERE player_id = %s", (duplicate_id,))


def add_verified_aliases(cursor):
    for alias, target in VERIFIED_ALIAS_TARGETS.items():
        cursor.execute(
            """
            SELECT p.player_id
            FROM players p
            LEFT JOIN player_aliases pa ON pa.player_id = p.player_id
            WHERE LOWER(p.canonical_name) = LOWER(%s)
               OR pa.normalized_name = %s
            ORDER BY CASE WHEN LOWER(p.canonical_name) = LOWER(%s) THEN 0 ELSE 1 END, p.player_id
            LIMIT 1
            """,
            (target, target, target),
        )
        row = cursor.fetchone()
        if not row:
            continue
        cursor.execute(
            """
            INSERT INTO player_aliases (player_id, source_id, original_name, normalized_name)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (source_id, normalized_name, player_id) DO NOTHING
            """,
            (row[0], "verified", alias.title(), alias),
        )


def run(database_url, apply=False):
    connection = connect(database_url)
    try:
        with connection.cursor() as cursor:
            groups, facts = candidate_groups(cursor)
            plans = []
            for key, player_ids in groups:
                target_id = choose_canonical(player_ids, facts)
                duplicate_ids = [player_id for player_id in player_ids if player_id != target_id]
                plans.append((key, target_id, duplicate_ids))

            for key, target_id, duplicate_ids in plans:
                progress(f"{'merge' if apply else 'dry-run'} normalized={key}: target={target_id} duplicates={duplicate_ids}")
                if apply:
                    for duplicate_id in duplicate_ids:
                        merge_players(cursor, target_id, duplicate_id)
            if apply:
                add_verified_aliases(cursor)
                connection.commit()
            else:
                connection.rollback()
            return plans
    except Exception:
        safe_rollback(connection)
        raise
    finally:
        safe_close(connection)


def main():
    parser = argparse.ArgumentParser(description="Safely merge duplicate World Cup player entities.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Print duplicate merge plan without changing data.")
    mode.add_argument("--apply", action="store_true", help="Apply duplicate merges.")
    args = parser.parse_args()
    load_dotenv(ROOT / "backend" / ".env")
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is required")
    plans = run(database_url, apply=args.apply)
    progress(f"candidate groups={len(plans)}")


if __name__ == "__main__":
    main()
