import json
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw" / "openfootball"

ALIASES = {
    "West Germany": "Germany",
    "United States": "USA",
    "IR Iran": "Iran",
    "Korea Republic": "South Korea",
    "Czechia": "Czech Republic",
    "Republic of Ireland": "Ireland",
    "Ivory Coast": "Côte d'Ivoire",
    "Cote d'Ivoire": "Côte d'Ivoire",
    "Bosnia and Herzegovina": "Bosnia & Herzegovina",
    "Bosnia-Herzegovina": "Bosnia & Herzegovina",
    "Türkiye": "Turkey",
    "Curacao": "Curaçao",
    "Congo DR": "DR Congo",
}

PLAYER_CANONICAL_ALIASES = {
    "messi": "lionel messi",
    "lionel andrés messi cuccittini": "lionel messi",
}


@dataclass(frozen=True)
class CleanMatch:
    source_file: str
    tournament_name: str
    year: int
    date: date
    kickoff_time: str | None
    stage: str
    group_name: str | None
    home_original: str
    away_original: str
    home_team: str
    away_team: str
    home_score: int | None
    away_score: int | None
    stadium_name: str
    stadium_city: str
    goals: tuple
    source_match_key: str


def canonical_team_name(name):
    value = (name or "Unknown").strip()
    return ALIASES.get(value, value)


def parse_year(document, source_file):
    match = re.search(r"(19|20)\d{2}", document.get("name", "") or source_file)
    if not match:
        raise ValueError(f"Cannot determine tournament year for {source_file}")
    return int(match.group(0))


def parse_score(raw_match):
    score = (raw_match.get("score") or {}).get("ft")
    if not score or len(score) != 2 or score[0] is None or score[1] is None:
        return None, None
    return int(score[0]), int(score[1])


def split_stadium(raw_ground):
    ground = (raw_ground or "").strip()
    if not ground:
        return "Unknown stadium", "Unknown city", True
    if "," in ground:
        name, city = [part.strip() for part in ground.split(",", 1)]
        return name or "Unknown stadium", city or "Unknown city", False
    parenthetical = re.match(r"^(.*?)\s*\((.*?)\)\s*$", ground)
    if parenthetical:
        return parenthetical.group(1).strip(), parenthetical.group(2).strip(), False
    return ground, ground, False


def parse_goal_minute(goal):
    minute = goal.get("minute")
    offset = goal.get("offset")
    if minute is None:
        return None, None
    if isinstance(minute, int):
        return minute, int(offset) if offset is not None else None
    text = str(minute).strip()
    if "+" in text:
        base, extra = text.split("+", 1)
        return int(base), int(extra)
    return int(text), int(offset) if offset is not None else None


def duplicate_key(year, raw_match, home_team=None, away_team=None):
    home = home_team or canonical_team_name(raw_match.get("team1"))
    away = away_team or canonical_team_name(raw_match.get("team2"))
    parts = [
        str(year),
        raw_match.get("date") or "",
        raw_match.get("round") or "Unknown",
        raw_match.get("group") or "",
        home,
        away,
    ]
    return "|".join(part.strip().lower() for part in parts)


def iter_raw_files(raw_dir=RAW_DIR):
    return sorted(Path(raw_dir).glob("*.json"))


def clean_records(raw_dir=RAW_DIR):
    raw_records = 0
    missing_scores = 0
    missing_stadiums = 0
    duplicates = 0
    seen = set()
    records = []
    source_counts = defaultdict(lambda: {"raw": 0, "cleaned": 0, "duplicates": 0, "year": None})
    alias_pairs = set()

    for path in iter_raw_files(raw_dir):
        document = json.loads(path.read_text(encoding="utf-8"))
        year = parse_year(document, path.name)
        source_counts[path.name]["year"] = year
        tournament_name = document.get("name") or f"World Cup {year}"
        for raw_match in document.get("matches", []):
            raw_records += 1
            source_counts[path.name]["raw"] += 1
            home_original = (raw_match.get("team1") or "Unknown").strip()
            away_original = (raw_match.get("team2") or "Unknown").strip()
            home_team = canonical_team_name(home_original)
            away_team = canonical_team_name(away_original)
            if home_original != home_team:
                alias_pairs.add((home_original, home_team))
            if away_original != away_team:
                alias_pairs.add((away_original, away_team))

            key = duplicate_key(year, raw_match, home_team, away_team)
            if key in seen:
                duplicates += 1
                source_counts[path.name]["duplicates"] += 1
                continue
            seen.add(key)

            home_score, away_score = parse_score(raw_match)
            if home_score is None or away_score is None:
                missing_scores += 1
            stadium_name, stadium_city, stadium_missing = split_stadium(raw_match.get("ground"))
            if stadium_missing:
                missing_stadiums += 1

            goal_rows = []
            for side, scoring_team, goals in (
                ("home", home_team, raw_match.get("goals1") or []),
                ("away", away_team, raw_match.get("goals2") or []),
            ):
                for index, goal in enumerate(goals):
                    minute, stoppage = parse_goal_minute(goal)
                    player_name = (goal.get("name") or "Unknown scorer").strip()
                    goal_rows.append(
                        {
                            "side": side,
                            "index": index,
                            "player_name": player_name,
                            "team": scoring_team,
                            "minute": minute,
                            "stoppage_minute": stoppage,
                            "is_penalty": bool(goal.get("penalty")),
                            "is_own_goal": bool(goal.get("owngoal")),
                        }
                    )

            records.append(
                CleanMatch(
                    source_file=path.name,
                    tournament_name=tournament_name,
                    year=year,
                    date=date.fromisoformat(raw_match["date"]),
                    kickoff_time=raw_match.get("time"),
                    stage=raw_match.get("round") or "Unknown",
                    group_name=raw_match.get("group"),
                    home_original=home_original,
                    away_original=away_original,
                    home_team=home_team,
                    away_team=away_team,
                    home_score=home_score,
                    away_score=away_score,
                    stadium_name=stadium_name,
                    stadium_city=stadium_city,
                    goals=tuple(goal_rows),
                    source_match_key=key,
                )
            )
            source_counts[path.name]["cleaned"] += 1

    summary = {
        "raw_records": raw_records,
        "cleaned_records": len(records),
        "duplicate_records": duplicates,
        "missing_scores": missing_scores,
        "missing_stadiums": missing_stadiums,
        "alias_mappings": len(alias_pairs),
        "alias_pairs": sorted(alias_pairs),
        "source_counts": dict(source_counts),
    }
    return records, summary


def fetch_id(cursor, sql, params):
    cursor.execute(sql, params)
    return cursor.fetchone()[0]


def upsert_team(cursor, canonical_name):
    return fetch_id(
        cursor,
        """
        INSERT INTO teams (canonical_name)
        VALUES (%s)
        ON CONFLICT (canonical_name) DO UPDATE SET canonical_name = EXCLUDED.canonical_name
        RETURNING team_id
        """,
        (canonical_name,),
    )


def normalize_person_name(name):
    normalized = re.sub(r"\s+", " ", (name or "Unknown player").strip()).casefold()
    return PLAYER_CANONICAL_ALIASES.get(normalized, normalized)


def upsert_player(cursor, canonical_name, external_fjelstul_id=None, external_statsbomb_id=None):
    if external_fjelstul_id:
        normalized = normalize_person_name(canonical_name)
        cursor.execute(
            """
            SELECT p.player_id
            FROM players p
            JOIN player_aliases pa ON pa.player_id = p.player_id
            WHERE pa.normalized_name = %s
              AND (p.external_fjelstul_id IS NULL OR p.external_fjelstul_id = %s)
            ORDER BY CASE WHEN p.external_fjelstul_id = %s THEN 0 ELSE 1 END
            LIMIT 1
            """,
            (normalized, external_fjelstul_id, external_fjelstul_id),
        )
        row = cursor.fetchone()
        if row:
            cursor.execute(
                """
                UPDATE players
                SET canonical_name = %s,
                    external_fjelstul_id = COALESCE(external_fjelstul_id, %s)
                WHERE player_id = %s
                """,
                (canonical_name, external_fjelstul_id, row[0]),
            )
            return row[0]
        return fetch_id(
            cursor,
            """
            INSERT INTO players (canonical_name, external_fjelstul_id)
            VALUES (%s, %s)
            ON CONFLICT (external_fjelstul_id) DO UPDATE
            SET canonical_name = EXCLUDED.canonical_name
            RETURNING player_id
            """,
            (canonical_name, external_fjelstul_id),
        )
    if external_statsbomb_id:
        normalized = normalize_person_name(canonical_name)
        cursor.execute(
            """
            SELECT p.player_id
            FROM players p
            JOIN player_aliases pa ON pa.player_id = p.player_id
            WHERE pa.normalized_name = %s
              AND (p.external_statsbomb_id IS NULL OR p.external_statsbomb_id = %s)
            ORDER BY CASE WHEN p.external_statsbomb_id = %s THEN 0 ELSE 1 END
            LIMIT 1
            """,
            (normalized, external_statsbomb_id, external_statsbomb_id),
        )
        row = cursor.fetchone()
        if row:
            cursor.execute(
                """
                UPDATE players
                SET canonical_name = %s,
                    external_statsbomb_id = COALESCE(external_statsbomb_id, %s)
                WHERE player_id = %s
                """,
                (canonical_name, external_statsbomb_id, row[0]),
            )
            return row[0]
        return fetch_id(
            cursor,
            """
            INSERT INTO players (canonical_name, external_statsbomb_id)
            VALUES (%s, %s)
            ON CONFLICT (external_statsbomb_id) DO UPDATE
            SET canonical_name = EXCLUDED.canonical_name
            RETURNING player_id
            """,
            (canonical_name, external_statsbomb_id),
        )
    cursor.execute(
        """
        SELECT p.player_id
        FROM players p
        JOIN player_aliases pa ON pa.player_id = p.player_id
        WHERE pa.source_id = %s AND pa.normalized_name = %s
        LIMIT 1
        """,
        ("openfootball", normalize_person_name(canonical_name)),
    )
    row = cursor.fetchone()
    if row:
        return row[0]
    player_id = fetch_id(
        cursor,
        """
        INSERT INTO players (canonical_name)
        VALUES (%s)
        RETURNING player_id
        """,
        (canonical_name,),
    )
    cursor.execute(
        """
        INSERT INTO player_aliases (player_id, source_id, original_name, normalized_name)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (source_id, normalized_name, player_id) DO NOTHING
        """,
        (player_id, "openfootball", canonical_name, normalize_person_name(canonical_name)),
    )
    return player_id


def load_database(database_url=None, raw_dir=RAW_DIR):
    import psycopg2

    records, summary = clean_records(raw_dir)
    database_url = database_url or os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/worldcup")
    connection = psycopg2.connect(database_url)
    try:
        with connection:
            with connection.cursor() as cursor:
                team_ids = {}
                tournament_ids = {}
                stadium_ids = {}
                match_ids = {}

                for record in records:
                    tournament_ids[record.year] = fetch_id(
                        cursor,
                        """
                        INSERT INTO tournaments (year, name, source_file)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (year) DO UPDATE
                        SET name = EXCLUDED.name, source_file = EXCLUDED.source_file
                        RETURNING tournament_id
                        """,
                        (record.year, record.tournament_name, record.source_file),
                    )

                for name in sorted({r.home_team for r in records} | {r.away_team for r in records}):
                    team_ids[name] = upsert_team(cursor, name)

                for record in records:
                    for original, canonical in ((record.home_original, record.home_team), (record.away_original, record.away_team)):
                        cursor.execute(
                            """
                            INSERT INTO team_aliases (alias, team_id, source_name)
                            VALUES (%s, %s, %s)
                            ON CONFLICT (alias) DO UPDATE
                            SET team_id = EXCLUDED.team_id, source_name = EXCLUDED.source_name
                            """,
                            (original, team_ids[canonical], "OpenFootball"),
                        )

                for record in records:
                    stadium_key = (record.stadium_name, record.stadium_city)
                    if stadium_key not in stadium_ids:
                        stadium_ids[stadium_key] = fetch_id(
                            cursor,
                            """
                            INSERT INTO stadiums (name, city)
                            VALUES (%s, %s)
                            ON CONFLICT (name, city, (COALESCE(country, ''))) DO UPDATE
                            SET name = EXCLUDED.name
                            RETURNING stadium_id
                            """,
                            stadium_key,
                        )

                for record in records:
                    match_ids[record.source_match_key] = fetch_id(
                        cursor,
                        """
                        INSERT INTO matches (
                          source_match_key, tournament_id, match_date, kickoff_time, stage, group_name,
                          stadium_id, home_team_id, away_team_id, home_score, away_score, data_source, source_file
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (source_match_key) DO UPDATE SET
                          tournament_id = EXCLUDED.tournament_id,
                          match_date = EXCLUDED.match_date,
                          kickoff_time = EXCLUDED.kickoff_time,
                          stage = EXCLUDED.stage,
                          group_name = EXCLUDED.group_name,
                          stadium_id = EXCLUDED.stadium_id,
                          home_team_id = EXCLUDED.home_team_id,
                          away_team_id = EXCLUDED.away_team_id,
                          home_score = EXCLUDED.home_score,
                          away_score = EXCLUDED.away_score,
                          data_source = EXCLUDED.data_source,
                          source_file = EXCLUDED.source_file
                        RETURNING match_id
                        """,
                        (
                            record.source_match_key,
                            tournament_ids[record.year],
                            record.date,
                            record.kickoff_time,
                            record.stage,
                            record.group_name,
                            stadium_ids[(record.stadium_name, record.stadium_city)],
                            team_ids[record.home_team],
                            team_ids[record.away_team],
                            record.home_score,
                            record.away_score,
                            "OpenFootball",
                            record.source_file,
                        ),
                    )

                    for goal in record.goals:
                        player_id = upsert_player(cursor, goal["player_name"])
                        source_goal_key = f"{record.source_match_key}|{goal['side']}|{goal['index']}|{goal['player_name']}|{goal['minute']}|{goal['stoppage_minute']}"
                        cursor.execute(
                            """
                            INSERT INTO goals (
                              source_goal_key, match_id, player_id, team_id, tournament_id,
                              minute, stoppage_minute, is_penalty, is_own_goal
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                                source_goal_key,
                                match_ids[record.source_match_key],
                                player_id,
                                team_ids[goal["team"]],
                                tournament_ids[record.year],
                                goal["minute"],
                                goal["stoppage_minute"],
                                goal["is_penalty"],
                                goal["is_own_goal"],
                            ),
                        )

                cursor.execute(
                    """
                    INSERT INTO data_quality_metrics (
                      metric_id, raw_records, cleaned_records, duplicate_records,
                      missing_scores, missing_stadiums, alias_mappings, loaded_at
                    )
                    VALUES (1, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (metric_id) DO UPDATE SET
                      raw_records = EXCLUDED.raw_records,
                      cleaned_records = EXCLUDED.cleaned_records,
                      duplicate_records = EXCLUDED.duplicate_records,
                      missing_scores = EXCLUDED.missing_scores,
                      missing_stadiums = EXCLUDED.missing_stadiums,
                      alias_mappings = EXCLUDED.alias_mappings,
                      loaded_at = NOW()
                    """,
                    (
                        summary["raw_records"],
                        summary["cleaned_records"],
                        summary["duplicate_records"],
                        summary["missing_scores"],
                        summary["missing_stadiums"],
                        summary["alias_mappings"],
                    ),
                )
                cursor.execute("DELETE FROM data_quality_sources")
                for source_file, counts in sorted(summary["source_counts"].items()):
                    cursor.execute(
                        """
                        INSERT INTO data_quality_sources (
                          source_file, tournament_year, raw_records, cleaned_records, duplicate_records
                        )
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (source_file, counts["year"], counts["raw"], counts["cleaned"], counts["duplicates"]),
                    )
                for key, table in (
                    ("tournaments", "tournaments"),
                    ("teams", "teams"),
                    ("matches", "matches"),
                    ("goals", "goals"),
                ):
                    cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    summary[key] = cursor.fetchone()[0]
        return summary
    finally:
        connection.close()


def print_summary(summary):
    labels = [
        ("Raw records", summary["raw_records"]),
        ("Cleaned records", summary["cleaned_records"]),
        ("Tournaments", summary.get("tournaments", len({counts["year"] for counts in summary["source_counts"].values()}))),
        ("Teams", summary.get("teams", "not loaded")),
        ("Matches", summary.get("matches", summary["cleaned_records"])),
        ("Goals", summary.get("goals", "not loaded")),
        ("Duplicates", summary["duplicate_records"]),
        ("Missing scores", summary["missing_scores"]),
        ("Missing stadiums", summary["missing_stadiums"]),
        ("Alias mappings", summary["alias_mappings"]),
    ]
    print("Data-quality summary")
    for label, value in labels:
        print(f"- {label}: {value}")
    for original, canonical in summary["alias_pairs"]:
        print(f"  alias: {original} -> {canonical}")


def main():
    from dotenv import load_dotenv

    load_dotenv(ROOT / "backend" / ".env")
    try:
        summary = load_database()
    except Exception as exc:
        print(f"ETL failed; transaction rolled back: {exc}", file=sys.stderr)
        raise
    print_summary(summary)


if __name__ == "__main__":
    main()
