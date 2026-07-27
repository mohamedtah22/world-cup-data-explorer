import argparse
import os
from collections import defaultdict

import psycopg2
from dotenv import load_dotenv

from player_identity import (
    VERIFIED_PLAYER_ALIASES,
    is_surname_only_name,
    normalize_player_name,
    player_name_parts,
)
from load_player_data import ROOT, connect, progress, safe_close, safe_rollback

VERIFIED_ALIAS_TARGETS = VERIFIED_PLAYER_ALIASES


def fetchall(cursor, sql, params=()):
    cursor.execute(sql, params)
    return cursor.fetchall()


def player_facts(cursor):
    rows = fetchall(
        cursor,
        """
        SELECT p.player_id, p.canonical_name, p.birth_date, p.country_of_birth,
               p.external_fjelstul_id, p.external_statsbomb_id,
               ARRAY(SELECT DISTINCT normalize_alias.normalized_name
                     FROM player_aliases normalize_alias
                     WHERE normalize_alias.player_id = p.player_id) AS aliases,
               ARRAY(SELECT DISTINCT original_alias.original_name
                     FROM player_aliases original_alias
                     WHERE original_alias.player_id = p.player_id) AS original_aliases,
               ARRAY(
                 SELECT DISTINCT team_id
                 FROM (
                   SELECT pt.team_id FROM player_tournaments pt WHERE pt.player_id = p.player_id
                   UNION
                   SELECT app.team_id FROM player_appearances app WHERE app.player_id = p.player_id
                   UNION
                   SELECT g.team_id FROM goals g WHERE g.player_id = p.player_id
                   UNION
                   SELECT pei.team_id FROM player_external_ids pei WHERE pei.player_id = p.player_id AND pei.team_id IS NOT NULL
                 ) team_facts
               ) AS teams,
               ARRAY(
                 SELECT DISTINCT tournament_id
                 FROM (
                   SELECT pt.tournament_id FROM player_tournaments pt WHERE pt.player_id = p.player_id
                   UNION
                   SELECT m.tournament_id
                   FROM player_appearances app
                   JOIN matches m ON m.match_id = app.match_id
                   WHERE app.player_id = p.player_id
                   UNION
                   SELECT g.tournament_id FROM goals g WHERE g.player_id = p.player_id
                   UNION
                   SELECT m.tournament_id
                   FROM player_match_stats pms
                   JOIN matches m ON m.match_id = pms.match_id
                   WHERE pms.player_id = p.player_id
                 ) tournament_facts
               ) AS tournaments,
               ARRAY(
                 SELECT DISTINCT match_id
                 FROM (
                   SELECT app.match_id FROM player_appearances app WHERE app.player_id = p.player_id
                   UNION
                   SELECT g.match_id FROM goals g WHERE g.player_id = p.player_id
                   UNION
                   SELECT pms.match_id FROM player_match_stats pms WHERE pms.player_id = p.player_id
                 ) match_facts
               ) AS matches,
               ARRAY(SELECT DISTINCT pei.source_id || ':' || pei.external_player_id
                     FROM player_external_ids pei
                     WHERE pei.player_id = p.player_id) AS mapped_external_ids,
               ARRAY(
                 SELECT DISTINCT tm.canonical_name
                 FROM (
                   SELECT pt.team_id FROM player_tournaments pt WHERE pt.player_id = p.player_id
                   UNION
                   SELECT app.team_id FROM player_appearances app WHERE app.player_id = p.player_id
                   UNION
                   SELECT g.team_id FROM goals g WHERE g.player_id = p.player_id
                   UNION
                   SELECT pei.team_id FROM player_external_ids pei WHERE pei.player_id = p.player_id AND pei.team_id IS NOT NULL
                 ) team_fact_names
                 JOIN teams tm ON tm.team_id = team_fact_names.team_id
               ) AS team_names,
               ARRAY(
                 SELECT DISTINCT tr.year
                 FROM (
                   SELECT pt.tournament_id FROM player_tournaments pt WHERE pt.player_id = p.player_id
                   UNION
                   SELECT m.tournament_id
                   FROM player_appearances app
                   JOIN matches m ON m.match_id = app.match_id
                   WHERE app.player_id = p.player_id
                   UNION
                   SELECT g.tournament_id FROM goals g WHERE g.player_id = p.player_id
                   UNION
                   SELECT m.tournament_id
                   FROM player_match_stats pms
                   JOIN matches m ON m.match_id = pms.match_id
                   WHERE pms.player_id = p.player_id
                 ) tournament_fact_years
                 JOIN tournaments tr ON tr.tournament_id = tournament_fact_years.tournament_id
               ) AS tournament_years,
               (SELECT COUNT(DISTINCT app.match_id) FROM player_appearances app WHERE app.player_id = p.player_id)::int AS appearances,
               (SELECT COUNT(DISTINCT app.match_id) FROM player_appearances app WHERE app.player_id = p.player_id AND app.started IS TRUE)::int AS starts,
               (SELECT COALESCE(SUM(app.minutes_played), 0) FROM player_appearances app WHERE app.player_id = p.player_id)::int AS minutes_played,
               (SELECT COUNT(*) FROM goals g WHERE g.player_id = p.player_id AND NOT g.is_own_goal)::int AS goals,
               (SELECT COUNT(*) FROM goals g WHERE g.player_id = p.player_id AND g.is_penalty IS TRUE AND NOT g.is_own_goal)::int AS penalty_goals,
               (SELECT COALESCE(SUM(pms.assists), 0) FROM player_match_stats pms WHERE pms.player_id = p.player_id AND pms.assists IS NOT NULL)::int AS assists
        FROM players p
        GROUP BY p.player_id
        """,
    )
    facts = {}
    for row in rows:
        (
            player_id,
            name,
            birth_date,
            country_of_birth,
            fjelstul_id,
            statsbomb_id,
            aliases,
            original_aliases,
            teams,
            tournaments,
            matches,
            mapped_external_ids,
            team_names,
            tournament_years,
            appearances,
            starts,
            minutes_played,
            goals,
            penalty_goals,
            assists,
        ) = row
        base_normalized = normalize_player_name(name, resolve_verified_aliases=False)
        normalized = normalize_player_name(name)
        external_ids = set(mapped_external_ids or [])
        if fjelstul_id:
            external_ids.add(f"fjelstul:{fjelstul_id}")
        if statsbomb_id:
            external_ids.add(f"statsbomb:{statsbomb_id}")
        source_names = set(original_aliases or []) | {name}
        raw_aliases = set(aliases or []) | {normalize_player_name(alias, resolve_verified_aliases=False) for alias in source_names}
        base_aliases = {normalize_player_name(alias, resolve_verified_aliases=False) for alias in raw_aliases} | {base_normalized}
        aliases = {normalize_player_name(alias) for alias in raw_aliases} | {normalized}
        facts[player_id] = {
            "player_id": player_id,
            "name": name,
            "source_names": source_names,
            "base_normalized": base_normalized,
            "normalized": normalized,
            "birth_date": birth_date,
            "country_of_birth": country_of_birth,
            "external_ids": external_ids,
            "base_aliases": base_aliases,
            "aliases": aliases,
            "teams": set(teams or []),
            "team_names": set(team_names or []),
            "tournaments": set(tournaments or []),
            "tournament_years": set(tournament_years or []),
            "matches": set(matches or []),
            "stats": {
                "appearances": appearances or 0,
                "starts": starts or 0,
                "minutes_played": minutes_played or 0,
                "goals": goals or 0,
                "penalty_goals": penalty_goals or 0,
                "assists": assists or 0,
            },
        }
    return facts


def has_verified_alias_relationship(left, right):
    return verified_alias_key(left, right) is not None


def verified_alias_key(left, right):
    for alias, target in VERIFIED_ALIAS_TARGETS.items():
        if alias in left["base_aliases"] and target in right["aliases"]:
            return target
        if alias in right["base_aliases"] and target in left["aliases"]:
            return target
    return None


def matching_evidence(left, right):
    evidence = []
    shared_external_ids = left["external_ids"] & right["external_ids"]
    if shared_external_ids:
        evidence.append(f"same external id {', '.join(sorted(shared_external_ids))}")
    if left["birth_date"] and right["birth_date"] and left["birth_date"] == right["birth_date"]:
        evidence.append(f"same birth date {left['birth_date']}")
    if left["country_of_birth"] and right["country_of_birth"] and normalize_player_name(left["country_of_birth"]) == normalize_player_name(right["country_of_birth"]):
        evidence.append(f"same country {left['country_of_birth']}")
    shared_teams = left["teams"] & right["teams"]
    if shared_teams:
        shared_team_names = sorted(left["team_names"] & right["team_names"])
        evidence.append(f"same team {', '.join(shared_team_names) if shared_team_names else ', '.join(str(team_id) for team_id in sorted(shared_teams))}")
    shared_tournaments = left["tournaments"] & right["tournaments"]
    if shared_tournaments:
        shared_years = sorted(left["tournament_years"] & right["tournament_years"])
        evidence.append(f"same tournament {', '.join(str(year) for year in shared_years) if shared_years else ', '.join(str(tid) for tid in sorted(shared_tournaments))}")
    shared_matches = left["matches"] & right["matches"]
    if shared_matches:
        evidence.append(f"same match count {len(shared_matches)}")
    if left["tournament_years"] and right["tournament_years"] and year_ranges_overlap(left["tournament_years"], right["tournament_years"]):
        evidence.append("overlapping tournament year range")
    return evidence


def year_ranges_overlap(left_years, right_years):
    left_min, left_max = min(left_years), max(left_years)
    right_min, right_max = min(right_years), max(right_years)
    return left_min <= right_max and right_min <= left_max


def has_supporting_evidence(left, right):
    return bool(matching_evidence(left, right))


def conflict_evidence(left, right):
    conflicts = []
    if left["birth_date"] and right["birth_date"] and left["birth_date"] != right["birth_date"]:
        conflicts.append(f"different birth dates {left['birth_date']} vs {right['birth_date']}")
    if left["country_of_birth"] and right["country_of_birth"] and normalize_player_name(left["country_of_birth"]) != normalize_player_name(right["country_of_birth"]):
        conflicts.append(f"different countries {left['country_of_birth']} vs {right['country_of_birth']}")
    return conflicts


def names_are_same_full_person(left, right):
    shared_names = (left["aliases"] & right["aliases"]) | (left["base_aliases"] & right["base_aliases"])
    return any(len(player_name_parts(name)) > 1 for name in shared_names) or left["base_normalized"] == right["base_normalized"]


def surname_alias_key(left, right):
    verified_key = verified_alias_key(left, right)
    if verified_key:
        return verified_key
    for left_name in left["base_aliases"]:
        if not is_surname_only_name(left_name):
            continue
        if any(len(player_name_parts(right_name)) > 1 and left_name in player_name_parts(right_name) for right_name in right["base_aliases"]):
            return left_name
    for right_name in right["base_aliases"]:
        if not is_surname_only_name(right_name):
            continue
        if any(len(player_name_parts(left_name)) > 1 and right_name in player_name_parts(left_name) for left_name in left["base_aliases"]):
            return right_name
    return None


def plan_reason(left, right):
    shared_external_ids = left["external_ids"] & right["external_ids"]
    if shared_external_ids:
        return "same_external_id", sorted(shared_external_ids)[0], matching_evidence(left, right)
    conflicts = conflict_evidence(left, right)
    alias_key = surname_alias_key(left, right)
    if alias_key:
        evidence = matching_evidence(left, right)
        if evidence:
            return "confirmed_surname_alias", VERIFIED_ALIAS_TARGETS.get(alias_key, alias_key), evidence
    if names_are_same_full_person(left, right) and not conflicts:
        return "same_normalized_full_name", sorted(left["aliases"] & right["aliases"] or left["base_aliases"] & right["base_aliases"])[0], matching_evidence(left, right)
    return None, None, []


def build_identity_plan(cursor):
    facts = player_facts(cursor)
    by_external_id = defaultdict(list)
    by_name = defaultdict(list)
    by_surname = defaultdict(list)
    for player_id, fact in facts.items():
        for external_id in fact["external_ids"]:
            by_external_id[external_id].append(player_id)
        for key in fact["base_aliases"]:
            by_name[key].append(player_id)
            parts = player_name_parts(key)
            for part in set(parts):
                by_surname[part].append(player_id)

    confirmed = []
    ambiguous = []
    seen = set()

    def add_plan(key, reason, player_ids, evidence_by_duplicate=None):
        unique_ids = tuple(sorted(set(player_ids)))
        if len(unique_ids) < 2 or unique_ids in seen:
            return
        target_id = choose_canonical(unique_ids, facts)
        duplicate_ids = [player_id for player_id in unique_ids if player_id != target_id]
        if duplicate_ids:
            confirmed.append(
                {
                    "key": key,
                    "reason": reason,
                    "target_id": target_id,
                    "duplicate_ids": duplicate_ids,
                    "player_ids": list(unique_ids),
                    "evidence": evidence_by_duplicate or {player_id: matching_evidence(facts[target_id], facts[player_id]) for player_id in duplicate_ids},
                }
            )
            seen.add(unique_ids)

    for external_id, player_ids in sorted(by_external_id.items()):
        add_plan(external_id, "same_external_id", player_ids)

    for key, player_ids in sorted(by_name.items()):
        if len(player_name_parts(key)) < 2:
            continue
        unique_ids = tuple(sorted(set(player_ids)))
        if len(unique_ids) < 2:
            continue
        conflicts = [conflict_evidence(facts[a], facts[b]) for index, a in enumerate(unique_ids) for b in unique_ids[index + 1 :]]
        if any(conflicts):
            ambiguous.append({"key": key, "reason": "same_name_conflict", "player_ids": list(unique_ids)})
        else:
            add_plan(key, "same_normalized_full_name", unique_ids)

    for surname, player_ids in sorted(by_surname.items()):
        unique_ids = sorted(set(player_ids))
        if len(unique_ids) < 2:
            continue
        surname_only_ids = [player_id for player_id in unique_ids if any(is_surname_only_name(alias) and alias == surname for alias in facts[player_id]["base_aliases"])]
        full_name_ids = [player_id for player_id in unique_ids if any(len(player_name_parts(alias)) > 1 and surname in player_name_parts(alias) for alias in facts[player_id]["base_aliases"])]
        if not surname_only_ids or not full_name_ids:
            continue
        for short_id in surname_only_ids:
            supported = []
            evidence_by_duplicate = {}
            for full_id in full_name_ids:
                if short_id == full_id:
                    continue
                reason, key, evidence = plan_reason(facts[short_id], facts[full_id])
                if reason == "confirmed_surname_alias":
                    supported.append(full_id)
                    evidence_by_duplicate[full_id] = evidence
            if len(supported) == 1:
                add_plan(VERIFIED_ALIAS_TARGETS.get(surname, surname), "confirmed_surname_alias", [short_id, supported[0]], evidence_by_duplicate)
            elif len(supported) > 1:
                ambiguous.append({"key": surname, "reason": "ambiguous_surname_alias", "player_ids": [short_id] + supported})

    return {"confirmed": confirmed, "ambiguous": ambiguous, "facts": facts}


def candidate_groups(cursor):
    plan = build_identity_plan(cursor)
    return [(item["key"], item["player_ids"]) for item in plan["confirmed"]], plan["facts"]


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
        "SELECT external_fjelstul_id, external_statsbomb_id, birth_date, preferred_position FROM players WHERE player_id = %s",
        (duplicate_id,),
    )
    duplicate = cursor.fetchone()
    cursor.execute(
        "SELECT external_fjelstul_id, external_statsbomb_id FROM players WHERE player_id = %s",
        (target_id,),
    )
    target = cursor.fetchone()
    if duplicate and target:
        duplicate_fjelstul_id, duplicate_statsbomb_id, duplicate_birth_date, duplicate_position = duplicate
        target_fjelstul_id, target_statsbomb_id = target
        if duplicate_fjelstul_id:
            cursor.execute(
                """
                INSERT INTO player_external_ids (source_id, external_player_id, player_id, original_name)
                SELECT 'fjelstul', %s, %s, canonical_name
                FROM players
                WHERE player_id = %s
                ON CONFLICT (source_id, external_player_id) DO UPDATE SET player_id = EXCLUDED.player_id
                """,
                (duplicate_fjelstul_id, target_id, duplicate_id),
            )
        if duplicate_statsbomb_id:
            cursor.execute(
                """
                INSERT INTO player_external_ids (source_id, external_player_id, player_id, original_name)
                SELECT 'statsbomb', %s, %s, canonical_name
                FROM players
                WHERE player_id = %s
                ON CONFLICT (source_id, external_player_id) DO UPDATE SET player_id = EXCLUDED.player_id
                """,
                (duplicate_statsbomb_id, target_id, duplicate_id),
            )
        if duplicate_fjelstul_id and not target_fjelstul_id:
            cursor.execute("UPDATE players SET external_fjelstul_id = NULL WHERE player_id = %s", (duplicate_id,))
            cursor.execute("UPDATE players SET external_fjelstul_id = %s WHERE player_id = %s", (duplicate_fjelstul_id, target_id))
        if duplicate_statsbomb_id and not target_statsbomb_id:
            cursor.execute("UPDATE players SET external_statsbomb_id = NULL WHERE player_id = %s", (duplicate_id,))
            cursor.execute("UPDATE players SET external_statsbomb_id = %s WHERE player_id = %s", (duplicate_statsbomb_id, target_id))
        cursor.execute(
            """
            UPDATE players
            SET birth_date = COALESCE(birth_date, %s),
                preferred_position = COALESCE(preferred_position, %s)
            WHERE player_id = %s
            """,
            (duplicate_birth_date, duplicate_position, target_id),
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
            (row[0], "verified", alias.title(), normalize_player_name(alias)),
        )


def normalize_existing_aliases(cursor):
    cursor.execute("SELECT alias_id, player_id, source_id, original_name, normalized_name FROM player_aliases ORDER BY alias_id")
    rows = cursor.fetchall()
    changed = 0
    deleted = 0
    for alias_id, player_id, source_id, original_name, normalized_name in rows:
        next_normalized = normalize_player_name(original_name)
        if next_normalized == normalized_name:
            continue
        cursor.execute(
            """
            SELECT alias_id
            FROM player_aliases
            WHERE player_id = %s
              AND source_id = %s
              AND normalized_name = %s
              AND alias_id <> %s
            LIMIT 1
            """,
            (player_id, source_id, next_normalized, alias_id),
        )
        if cursor.fetchone():
            cursor.execute("DELETE FROM player_aliases WHERE alias_id = %s", (alias_id,))
            deleted += 1
        else:
            cursor.execute("UPDATE player_aliases SET normalized_name = %s WHERE alias_id = %s", (next_normalized, alias_id))
            changed += 1
    return {"normalized_aliases": changed, "deleted_alias_conflicts": deleted}


def format_fact(fact):
    stats = fact["stats"]
    parts = [
        f"{fact['player_id']}:{fact['name']}",
        f"aliases={sorted(fact['base_aliases'])[:8]}",
        f"teams={sorted(fact['team_names']) or sorted(fact['teams'])}",
        f"tournaments={sorted(fact['tournament_years']) or sorted(fact['tournaments'])}",
        f"external_ids={sorted(fact['external_ids'])}",
        (
            "stats="
            f"apps:{stats['appearances']} starts:{stats['starts']} min:{stats['minutes_played']} "
            f"goals:{stats['goals']} pens:{stats['penalty_goals']} assists:{stats['assists']}"
        ),
    ]
    if fact["birth_date"]:
        parts.insert(2, f"birth_date={fact['birth_date']}")
    if fact["country_of_birth"]:
        parts.insert(3, f"country={fact['country_of_birth']}")
    return " | ".join(parts)


def print_identity_report(plan, mode):
    facts = plan["facts"]
    progress(f"{mode}: confirmed merge groups={len(plan['confirmed'])} ambiguous review groups={len(plan['ambiguous'])}")
    for item in plan["confirmed"]:
        target = facts[item["target_id"]]
        progress(f"{mode}: {item['reason']} key={item['key']} target={format_fact(target)}")
        for duplicate_id in item["duplicate_ids"]:
            evidence = item["evidence"].get(duplicate_id, [])
            progress(f"{mode}:   duplicate={format_fact(facts[duplicate_id])} evidence={evidence or ['same normalized full name']}")
    for item in plan["ambiguous"]:
        progress(f"{mode}: review required reason={item['reason']} key={item['key']}")
        for player_id in item["player_ids"]:
            progress(f"{mode}:   candidate={format_fact(facts[player_id])}")


def run(database_url, apply=False):
    connection = connect(database_url)
    try:
        with connection.cursor() as cursor:
            plan = build_identity_plan(cursor)
            print_identity_report(plan, "apply" if apply else "dry-run")
            for item in plan["confirmed"]:
                if apply:
                    for duplicate_id in item["duplicate_ids"]:
                        merge_players(cursor, item["target_id"], duplicate_id)
            if apply:
                add_verified_aliases(cursor)
                alias_result = normalize_existing_aliases(cursor)
                progress(
                    f"alias normalization: normalized={alias_result['normalized_aliases']} "
                    f"deleted_conflicts={alias_result['deleted_alias_conflicts']}"
                )
                connection.commit()
            else:
                connection.rollback()
            return plan
    except Exception:
        safe_rollback(connection)
        raise
    finally:
        safe_close(connection)


def main():
    parser = argparse.ArgumentParser(description="Safely merge duplicate World Cup player entities.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--inspect", action="store_true", help="Print confirmed and ambiguous duplicate candidates without changing data.")
    mode.add_argument("--dry-run", action="store_true", help="Print duplicate merge plan without changing data.")
    mode.add_argument("--apply", action="store_true", help="Apply duplicate merges.")
    args = parser.parse_args()
    load_dotenv(ROOT / "backend" / ".env")
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is required")
    plan = run(database_url, apply=args.apply)
    progress(f"candidate groups={len(plan['confirmed'])}")


if __name__ == "__main__":
    main()
