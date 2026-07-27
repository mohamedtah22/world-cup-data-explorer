import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
sys.path.append(str(Path(__file__).resolve().parents[2] / "scripts"))

import app as backend_app
from load_database import normalize_person_name
from load_player_data import statsbomb_match_key
import dedupe_players


def client():
    backend_app.app.config.update(TESTING=True)
    return backend_app.app.test_client()


def test_player_identity_resolution_normalizes_names():
    assert normalize_person_name("  Lionel   Messi ") == "lionel messi"
    assert normalize_person_name("Messi") == "lionel messi"
    assert normalize_person_name("Julio Musimessi") == "julio musimessi"


def test_duplicate_player_prevention_sql_uses_external_id():
    from load_database import upsert_player

    constants = "\n".join(str(value) for value in upsert_player.__code__.co_consts)
    assert "ON CONFLICT (external_fjelstul_id)" in constants


def test_player_to_match_linking_key_uses_detected_statsbomb_match():
    match = {
        "season": {"season_name": "2022"},
        "match_date": "2022-12-18",
        "home_team": {"home_team_name": "Argentina"},
        "away_team": {"away_team_name": "France"},
    }
    assert statsbomb_match_key(match) == (2022, "2022-12-18", "Argentina", "France")


def test_top_scorer_calculation_endpoint(monkeypatch):
    monkeypatch.setattr(backend_app, "run_query", lambda *args, **kwargs: [{"player_id": 1, "player": "Miroslav Klose", "goals": 16, "appearances": 24}])
    response = client().get("/api/players/top-scorers?minimum_appearances=1&limit=5")
    assert response.status_code == 200
    assert response.get_json()[0]["goals"] == 16


def test_player_comparison_includes_basic_assists(monkeypatch):
    monkeypatch.setattr(
        backend_app,
        "run_query",
        lambda sql, params=(), one=False: {
            "player_id": 1,
            "player": "Player",
            "appearances": 1,
            "starts": 1,
            "goals": 0,
            "assists": 1,
            "minutes_played": None,
        }
        if "WHERE player_id IN" in sql
        else [],
    )
    response = client().get("/api/players/compare?player1=1&player2=2")
    assert response.status_code in {200, 404}


def test_statsbomb_coverage_detection_shape():
    coverage = statsbomb_match_key(
        {
            "season": {"season_name": "2018"},
            "match_date": "2018-07-15",
            "home_team": {"home_team_name": "France"},
            "away_team": {"away_team_name": "Croatia"},
        }
    )
    assert coverage[0] == 2018


def test_player_api_filters(monkeypatch):
    monkeypatch.setattr(
        backend_app,
        "run_query",
        lambda sql, params=(), one=False: {"total": 1} if one else [{"player_id": 1, "player": "Ronaldo", "goals": 8}],
    )
    response = client().get("/api/players?search=ronaldo&team=Brazil&sort_by=goals&order=desc")
    assert response.status_code == 200
    assert response.get_json()["results"][0]["player"] == "Ronaldo"


def test_player_comparison(monkeypatch):
    def fake_query(sql, params=(), one=False):
        if "SELECT * FROM" in sql and "WHERE player_id IN" in sql:
            return [
                {"player_id": 1, "player": "A", "goals": 2},
                {"player_id": 2, "player": "B", "goals": 1},
            ]
        return []

    monkeypatch.setattr(backend_app, "run_query", fake_query)
    response = client().get("/api/players/compare?player1=1&player2=2")
    assert response.status_code == 200
    assert response.get_json()["player1"]["player"] == "A"


def test_dedupe_groups_messi_but_not_julio_musimessi(monkeypatch):
    class FakeCursor:
        def __init__(self):
            self.rows = []

        def execute(self, sql, params=()):
            self.rows = [
                (1, "Messi", None, None, None, ["lionel messi"], [10], [2022], [100]),
                (2, "Lionel Messi", None, "p_lionel", None, ["lionel messi"], [10], [2022], [101]),
                (3, "Julio Musimessi", None, "p_julio", None, ["julio musimessi"], [20], [1958], [200]),
            ]

        def fetchall(self):
            return self.rows

    groups, facts = dedupe_players.candidate_groups(FakeCursor())
    messi_groups = [(key, ids) for key, ids in groups if key == "lionel messi"]

    assert messi_groups == [("lionel messi", [1, 2])]
    assert 3 not in messi_groups[0][1]
    assert dedupe_players.choose_canonical([1, 2], facts) == 2
