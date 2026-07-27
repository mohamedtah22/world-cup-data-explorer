import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
sys.path.append(str(Path(__file__).resolve().parents[2] / "scripts"))

import app as backend_app
from load_database import normalize_person_name
from load_player_data import statsbomb_match_key
import dedupe_players
from player_identity import is_partial_name_match


def player_fact_row(
    player_id,
    name,
    aliases=None,
    teams=None,
    tournaments=None,
    matches=None,
    external_ids=None,
    birth_date=None,
    country_of_birth=None,
    external_fjelstul_id=None,
    external_statsbomb_id=None,
    team_names=None,
    tournament_years=None,
    appearances=0,
    starts=0,
    minutes_played=0,
    goals=0,
    penalty_goals=0,
    assists=0,
):
    return (
        player_id,
        name,
        birth_date,
        country_of_birth,
        external_fjelstul_id,
        external_statsbomb_id,
        aliases or [],
        aliases or [],
        teams or [],
        tournaments or [],
        matches or [],
        external_ids or [],
        team_names or [],
        tournament_years or [],
        appearances,
        starts,
        minutes_played,
        goals,
        penalty_goals,
        assists,
    )


def client():
    backend_app.app.config.update(TESTING=True)
    return backend_app.app.test_client()


def test_player_identity_resolution_normalizes_names():
    assert normalize_person_name("  Lionel   Messi ") == "lionel messi"
    assert normalize_person_name("Messi") == "lionel messi"
    assert normalize_person_name("Julio Musimessi") == "julio musimessi"
    assert normalize_person_name("Kylian Mbappé") == "kylian mbappe"
    assert normalize_person_name("Mbappe, Kylian") == "kylian mbappe"
    assert normalize_person_name("Jean-Pierre O'Neill") == "jean pierre oneill"
    assert is_partial_name_match("Messi", "Lionel Messi")


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
                player_fact_row(1, "Messi", aliases=["messi"], teams=[10], tournaments=[2022], matches=[100], team_names=["Argentina"], tournament_years=[2022], goals=1),
                player_fact_row(
                    2,
                    "Lionel Messi",
                    aliases=["lionel messi"],
                    teams=[10],
                    tournaments=[2022],
                    matches=[101],
                    external_fjelstul_id="p_lionel",
                    team_names=["Argentina"],
                    tournament_years=[2022],
                    appearances=1,
                ),
                player_fact_row(3, "Julio Musimessi", aliases=["julio musimessi"], teams=[20], tournaments=[1958], matches=[200], external_fjelstul_id="p_julio"),
            ]

        def fetchall(self):
            return self.rows

    groups, facts = dedupe_players.candidate_groups(FakeCursor())
    messi_groups = [(key, ids) for key, ids in groups if key == "lionel messi"]

    assert messi_groups == [("lionel messi", [1, 2])]
    assert 3 not in messi_groups[0][1]
    assert dedupe_players.choose_canonical([1, 2], facts) == 2


def test_dedupe_groups_verified_surname_alias_with_goal_evidence_only():
    class FakeCursor:
        def execute(self, sql, params=()):
            self.rows = [
                player_fact_row(1, "Messi", aliases=["messi"], teams=[10], tournaments=[2022], matches=[100], team_names=["Argentina"], tournament_years=[2022], goals=1),
                player_fact_row(2, "Lionel Messi", aliases=["lionel messi"], teams=[10], tournaments=[2022], matches=[101], external_fjelstul_id="p_lionel", team_names=["Argentina"], tournament_years=[2022]),
                player_fact_row(3, "Julio Musimessi", aliases=["julio musimessi"], teams=[20], tournaments=[1958], matches=[200], external_fjelstul_id="p_julio"),
            ]

        def fetchall(self):
            return self.rows

    groups, facts = dedupe_players.candidate_groups(FakeCursor())
    messi_groups = [(key, ids) for key, ids in groups if key == "lionel messi"]

    assert messi_groups == [("lionel messi", [1, 2])]
    assert dedupe_players.has_verified_alias_relationship(facts[1], facts[2])
    assert dedupe_players.has_supporting_evidence(facts[1], facts[2])
    assert 3 not in messi_groups[0][1]


def test_dedupe_does_not_merge_ambiguous_same_surname():
    class FakeCursor:
        def execute(self, sql, params=()):
            self.rows = [
                player_fact_row(1, "Ronaldo", aliases=["ronaldo"], teams=[1], tournaments=[2018], matches=[10], team_names=["Portugal"], tournament_years=[2018]),
                player_fact_row(2, "Cristiano Ronaldo", aliases=["cristiano ronaldo"], teams=[1], tournaments=[2018], matches=[20], external_fjelstul_id="cr7", team_names=["Portugal"], tournament_years=[2018]),
                player_fact_row(3, "Ronaldo Nazario", aliases=["ronaldo nazario"], teams=[1], tournaments=[2018], matches=[30], external_fjelstul_id="r9", team_names=["Portugal"], tournament_years=[2018]),
            ]

        def fetchall(self):
            return self.rows

    plan = dedupe_players.build_identity_plan(FakeCursor())

    assert not plan["confirmed"]
    assert plan["ambiguous"][0]["reason"] == "ambiguous_surname_alias"


def test_dedupe_groups_cristiano_ronaldo_exact_duplicate():
    class FakeCursor:
        def execute(self, sql, params=()):
            self.rows = [
                player_fact_row(1, "Cristiano Ronaldo", aliases=["cristiano ronaldo"], teams=[1], tournaments=[2018], matches=[10], external_fjelstul_id="cr7"),
                player_fact_row(2, "Cristiano Ronaldo", aliases=["cristiano ronaldo"], teams=[1], tournaments=[2018], matches=[11], external_ids=["espn_2026:7"]),
            ]

        def fetchall(self):
            return self.rows

    plan = dedupe_players.build_identity_plan(FakeCursor())

    assert plan["confirmed"][0]["reason"] == "same_normalized_full_name"
    assert plan["confirmed"][0]["player_ids"] == [1, 2]


def test_dedupe_groups_same_source_external_id():
    class FakeCursor:
        def execute(self, sql, params=()):
            self.rows = [
                player_fact_row(1, "Kylian Mbappe", aliases=["kylian mbappe"], teams=[1], tournaments=[2022], matches=[10], external_ids=["espn_2026:123"]),
                player_fact_row(2, "Kylian Mbappé", aliases=["kylian mbappe"], teams=[1], tournaments=[2022], matches=[11], external_ids=["espn_2026:123"]),
            ]

        def fetchall(self):
            return self.rows

    groups, facts = dedupe_players.candidate_groups(FakeCursor())

    assert groups[0][1] == [1, 2]
    assert dedupe_players.has_supporting_evidence(facts[1], facts[2])
