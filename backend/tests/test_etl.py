import json
import os
import subprocess
import sys
from pathlib import Path

import psycopg2
import pytest

sys.path.append(str(Path(__file__).resolve().parents[2] / "scripts"))

from load_database import canonical_team_name, clean_records, duplicate_key, load_database


def test_alias_normalization():
    assert canonical_team_name("West Germany") == "Germany"
    assert canonical_team_name("United States") == "USA"
    assert canonical_team_name("IR Iran") == "Iran"
    assert canonical_team_name("Korea Republic") == "South Korea"
    assert canonical_team_name("Brazil") == "Brazil"


def test_duplicate_detection(tmp_path):
    raw = {
        "name": "World Cup 2022",
        "matches": [
            {
                "round": "Final",
                "date": "2022-12-18",
                "team1": "Argentina",
                "team2": "France",
                "score": {"ft": [3, 3]},
                "goals1": [{"name": "Messi", "minute": "23", "penalty": True}],
                "goals2": [],
                "ground": "Lusail Stadium, Lusail",
            },
            {
                "round": "Final",
                "date": "2022-12-18",
                "team1": "Argentina",
                "team2": "France",
                "score": {"ft": [3, 3]},
                "goals1": [],
                "goals2": [],
                "ground": "Lusail Stadium, Lusail",
            },
        ],
    }
    (tmp_path / "worldcup.json").write_text(json.dumps(raw), encoding="utf-8")
    records, summary = clean_records(tmp_path)
    assert summary["raw_records"] == 2
    assert summary["cleaned_records"] == 1
    assert summary["duplicate_records"] == 1
    assert duplicate_key(2022, raw["matches"][0]) == duplicate_key(2022, raw["matches"][1])


def test_etl_second_run_is_idempotent_when_test_database_is_available():
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL ETL idempotency integration test")

    schema = Path(__file__).resolve().parents[2] / "database" / "schema.sql"
    subprocess.run(["psql", database_url, "-f", str(schema)], check=True)
    first = load_database(database_url=database_url)
    second = load_database(database_url=database_url)

    with psycopg2.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM matches")
            match_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM goals")
            goal_count = cursor.fetchone()[0]

    assert first["matches"] == second["matches"] == match_count
    assert first["goals"] == second["goals"] == goal_count
