import json
import os
import subprocess
import sys
import shutil
from collections import Counter
from pathlib import Path

import psycopg2
import pytest
import importlib

sys.path.append(str(Path(__file__).resolve().parents[2] / "scripts"))

from load_database import canonical_team_name, clean_records, duplicate_key, load_database
from load_player_data import load_fjelstul
load_player_data_module = importlib.import_module("load_player_data")


def test_alias_normalization():
    assert canonical_team_name("West Germany") == "Germany"
    assert canonical_team_name("United States") == "USA"
    assert canonical_team_name("IR Iran") == "Iran"
    assert canonical_team_name("Korea Republic") == "South Korea"
    assert canonical_team_name("Brazil") == "Brazil"
    assert canonical_team_name("Ivory Coast") == "Côte d'Ivoire"
    assert canonical_team_name("Bosnia-Herzegovina") == "Bosnia & Herzegovina"


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
    if shutil.which("psql"):
        subprocess.run(["psql", database_url, "-f", str(schema)], check=True)
    else:
        with psycopg2.connect(database_url) as connection:
            connection.set_session(autocommit=True)
            with connection.cursor() as cursor:
                cursor.execute(schema.read_text(encoding="utf-8"))
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


def test_fjelstul_goal_delete_is_scoped_to_linked_matches():
    constants = "\n".join(str(value) for value in load_fjelstul.__code__.co_consts)
    assert "source_goal_key NOT LIKE 'fjelstul:%%' AND match_id = ANY(%s)" in constants
    assert "DELETE FROM goals WHERE source_goal_key NOT LIKE 'fjelstul:%'" not in constants


def test_player_loader_resume_skips_quality_issue_clear(monkeypatch):
    phases = []

    def fake_execute_phase(database_url, phase_name, phase_func, stats, resume=False):
        phases.append((phase_name, resume))
        return {}

    monkeypatch.setattr(load_player_data_module, "execute_phase", fake_execute_phase)
    monkeypatch.setattr(load_player_data_module, "statsbomb_coverages", lambda: [])

    load_player_data_module.load_player_data(database_url="postgresql://example/db", resume=True)

    assert "clear source quality issues" not in [phase for phase, _ in phases]
    assert "clear StatsBomb player_events" in [phase for phase, _ in phases]
    assert [phase for phase, _ in phases][:3] == [
        "Fjelstul players and aliases",
        "Fjelstul squads and match-player links",
        "Fjelstul appearances, goals, bookings, and substitutions",
    ]
    assert all(resume for _, resume in phases)


def test_player_loader_only_espn_skips_fjelstul_and_statsbomb(monkeypatch):
    phases = []

    def fake_execute_phase(database_url, phase_name, phase_func, stats, resume=False):
        phases.append((phase_name, resume))
        return {}

    monkeypatch.setattr(load_player_data_module, "execute_phase", fake_execute_phase)
    monkeypatch.setattr(load_player_data_module, "statsbomb_coverages", lambda: [{"coverage_year": 2022}])

    load_player_data_module.load_player_data(database_url="postgresql://example/db", resume=True, only_espn=True)

    assert [phase for phase, _ in phases] == ["ESPN 2026 data", "final quality metrics"]
    assert all(resume for _, resume in phases)


def test_phase_retry_reconnects_after_operational_error(monkeypatch):
    attempts = {"count": 0}
    sleeps = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=()):
            pass

    class FakeConnection:
        closed = 0

        def cursor(self):
            return FakeCursor()

        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            self.closed = 1

    def flaky_phase(cursor, stats):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise psycopg2.OperationalError("server closed the connection unexpectedly")
        return {"rows": 2}

    monkeypatch.setattr(load_player_data_module, "connect", lambda database_url: FakeConnection())
    monkeypatch.setattr(load_player_data_module.time, "sleep", lambda seconds: sleeps.append(seconds))

    result = load_player_data_module.execute_phase("postgresql://example/db", "test phase", flaky_phase, Counter())

    assert result == {"rows": 2}
    assert attempts["count"] == 2
    assert sleeps == [1]


def test_fjelstul_players_and_aliases_use_bulk_batches(monkeypatch):
    calls = []

    class FakeCursor:
        def __init__(self):
            self._results = []

        def execute(self, sql, params=()):
            assert "WHERE external_fjelstul_id = ANY" in sql
            self._results = [(external_id, index + 1) for index, external_id in enumerate(params[0])]

        def fetchall(self):
            return self._results

    def fake_execute_values(cursor, sql, rows, page_size=None, template=None):
        calls.append((sql, list(rows), page_size))

    rows = [
        {"player_id": "p1", "given_name": "Alpha", "family_name": "One", "birth_date": "1990-01-01", "forward": "1"},
        {"player_id": "p2", "given_name": "Beta", "family_name": "Two", "birth_date": "", "defender": "1"},
    ]

    monkeypatch.setattr(load_player_data_module, "execute_values", fake_execute_values)

    player_ids, counts = load_player_data_module.load_fjelstul_players_and_aliases(FakeCursor(), rows)

    assert player_ids == {"p1": 1, "p2": 2}
    assert counts == {"players": 2, "aliases": 2}
    assert len(calls) == 3
    assert "UPDATE players AS p" in calls[0][0]
    assert all(call[2] == load_player_data_module.BATCH_SIZE for call in calls)


def test_statsbomb_raw_event_json_is_off_by_default():
    assert load_player_data_module.STORE_RAW_EVENT_JSON is False


def test_statsbomb_player_events_are_off_by_default():
    assert load_player_data_module.STORE_PLAYER_EVENTS is False


def test_statsbomb_loader_is_assists_only():
    constants = "\n".join(str(value) for value in load_player_data_module.load_statsbomb.__code__.co_consts)
    assert "goal_assist" in constants
    assert "INSERT INTO player_events" not in constants
    assert "player_id, match_id, assists, source_id" in constants
    assert "shots, shots_on_target" not in constants


def test_espn_loader_skips_detailed_bookings_and_substitutions():
    constants = "\n".join(str(value) for value in load_player_data_module.load_espn_2026.__code__.co_consts)
    assert "espn 2026: match " in constants
    assert "INSERT INTO bookings" not in constants
    assert "INSERT INTO substitutions" not in constants
    assert "skipped_detail_plays" in constants


def test_statsbomb_event_cleanup_when_storage_disabled(monkeypatch):
    monkeypatch.setattr(load_player_data_module, "STORE_PLAYER_EVENTS", False)

    class FakeCursor:
        rowcount = 7

        def __init__(self):
            self.calls = []

        def execute(self, sql, params=()):
            self.calls.append((sql, params))

    cursor = FakeCursor()
    result = load_player_data_module.clear_statsbomb_player_events_when_disabled(cursor, Counter())

    assert result == {"deleted_player_events": 7}
    assert "DELETE FROM player_events WHERE source_id = %s" in cursor.calls[0][0]
    assert cursor.calls[0][1] == ("statsbomb",)


def test_execute_phase_sets_statement_timeout(monkeypatch):
    executed = []

    class FakeCursor:
        def __init__(self, connection):
            self.connection = connection

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=()):
            executed.append((sql, params))

    class FakeConnection:
        closed = 0

        def cursor(self):
            return FakeCursor(self)

        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            self.closed = 1

    monkeypatch.setattr(load_player_data_module, "connect", lambda database_url: FakeConnection())

    load_player_data_module.execute_phase("postgresql://example/db", "phase", lambda cursor, stats: {"ok": 1}, Counter())

    assert executed[0] == ("SET statement_timeout = %s", (load_player_data_module.STATEMENT_TIMEOUT_MS,))
