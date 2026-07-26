import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import app as backend_app


def client():
    backend_app.app.config.update(TESTING=True)
    return backend_app.app.test_client()


def test_health_endpoint(monkeypatch):
    monkeypatch.setattr(backend_app, "run_query", lambda *args, **kwargs: {"ok": 1})
    response = client().get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "database": "connected"}


def test_health_database_unavailable(monkeypatch):
    def unavailable(*args, **kwargs):
        raise backend_app.psycopg2.OperationalError("connection failed")

    monkeypatch.setattr(backend_app, "run_query", unavailable)
    response = client().get("/health")
    assert response.status_code == 503
    assert response.get_json() == {"status": "error", "database": "unavailable"}


def test_dashboard_endpoint(monkeypatch):
    responses = iter(
        [
            {"tournament_count": 2, "team_count": 4, "match_count": 5, "goal_count": 12},
            [{"year": 2022, "goals": 10, "matches": 4}],
            [{"team_id": 1, "team": "Brazil", "played": 3, "wins": 2, "draws": 1, "losses": 0, "goals_for": 6, "goals_against": 2, "win_rate": 66.7}],
            [{"player_id": 1, "player": "Ronaldo", "team": "Brazil", "goals": 3}],
            [{"stadium_id": 1, "name": "Lusail Stadium", "city": "Lusail", "matches": 3}],
            {"top_scorer": {"player": "Ronaldo", "goals": 3}, "most_appearances": {"player": "Ronaldo", "appearances": 7}, "most_goals_one_tournament": {"player": "Ronaldo", "year": 2002, "goals": 8}},
        ]
    )
    monkeypatch.setattr(backend_app, "run_query", lambda *args, **kwargs: next(responses))
    response = client().get("/api/dashboard")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["counts"]["match_count"] == 5
    assert payload["top_scorers"][0]["player"] == "Ronaldo"


def test_match_filtering(monkeypatch):
    calls = []

    def fake_query(sql, params=(), one=False):
        calls.append((sql, params, one))
        if one:
            return {"total": 1}
        return [{"match_id": 10, "home_team": "Argentina", "away_team": "France"}]

    monkeypatch.setattr(backend_app, "run_query", fake_query)
    response = client().get("/api/matches?year=2022&team=Argentina&stage=Final&page=1&limit=5")
    assert response.status_code == 200
    assert response.get_json()["pagination"]["total"] == 1
    assert "Argentina" in calls[0][1]


def test_team_search(monkeypatch):
    monkeypatch.setattr(
        backend_app,
        "run_query",
        lambda sql, params=(), one=False: {"total": 1} if one else [{"team_id": 1, "team": "Brazil", "wins": 5}],
    )
    response = client().get("/api/teams?search=bra&sort_by=team&order=asc")
    assert response.status_code == 200
    assert response.get_json()["results"][0]["team"] == "Brazil"


def test_ranked_team_autocomplete(monkeypatch):
    calls = []

    def fake_query(sql, params=(), one=False):
        calls.append((sql, params))
        return [{"id": 1, "label": "Argentina"}, {"id": 2, "label": "Saudi Arabia"}]

    monkeypatch.setattr(backend_app, "run_query", fake_query)
    response = client().get("/api/search/teams?q=arg&limit=10")
    assert response.status_code == 200
    assert response.get_json()[0]["label"] == "Argentina"
    assert "CASE" in calls[0][0]
    assert calls[0][1] == ("arg", "arg", "arg", "arg", 10)


def test_ranked_player_autocomplete_and_invalid_limit(monkeypatch):
    monkeypatch.setattr(backend_app, "run_query", lambda *args, **kwargs: [{"id": 410, "label": "Harry Kane"}])
    response = client().get("/api/search/players?q=kane&limit=1")
    assert response.status_code == 200
    assert response.get_json()[0]["label"] == "Harry Kane"

    invalid = client().get("/api/search/players?q=kane&limit=1000")
    assert invalid.status_code == 400


def test_team_comparison(monkeypatch):
    monkeypatch.setattr(
        backend_app,
        "team_comparison",
        lambda team_id: {"team_id": team_id, "team": f"Team {team_id}", "played": 3, "wins": 1, "draws": 1, "losses": 1, "goals_for": 4, "goals_against": 4, "win_rate": 33.3, "tournament_appearances": 1, "best_tournament_by_goals": {"year": 2022, "goals": 4}},
    )
    response = client().get("/api/compare?team1=1&team2=2")
    assert response.status_code == 200
    assert response.get_json()["team1"]["team"] == "Team 1"


def test_invalid_query_parameters():
    response = client().get("/api/matches?page=0")
    assert response.status_code == 400
    assert response.get_json()["error"] == "bad_request"


def test_compare_rejects_same_team():
    response = client().get("/api/compare?team1=1&team2=1")
    assert response.status_code == 400
