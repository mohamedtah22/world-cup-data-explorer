import os
import sys
from datetime import date
from decimal import Decimal

import psycopg2
from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS
from psycopg2.extras import RealDictCursor
from psycopg2.pool import SimpleConnectionPool

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "scripts"))
if SCRIPTS_DIR not in sys.path:
    sys.path.append(SCRIPTS_DIR)
from player_identity import normalize_player_name  # noqa: E402

load_dotenv(os.path.join(BASE_DIR, ".env"))

app = Flask(__name__)


def normalize_person_name(name):
    return normalize_player_name(name)


def allowed_origins():
    raw = os.getenv("FRONTEND_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    return [origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()]


CORS(app, resources={r"/api/*": {"origins": allowed_origins()}, r"/health": {"origins": allowed_origins()}})

_pool = None


def get_pool():
    global _pool
    if _pool is None:
        _pool = SimpleConnectionPool(
            1,
            10,
            dsn=os.getenv("DATABASE_URL") or "postgresql://postgres:postgres@127.0.0.1:5432/worldcup",
        )
    return _pool


def serialize(value):
    if isinstance(value, (date,)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def json_ready(row):
    return {key: serialize(value) for key, value in row.items()}


def run_query(sql, params=(), one=False):
    pool = get_pool()
    connection = pool.getconn()
    try:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(sql, params)
            if cursor.description is None:
                connection.commit()
                return None
            rows = [json_ready(row) for row in cursor.fetchall()]
            return rows[0] if one and rows else (None if one else rows)
    finally:
        pool.putconn(connection)


def int_arg(name, default=None, minimum=None, maximum=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be at most {maximum}")
    return value


def pagination_args(default_limit=25, max_limit=100):
    page = int_arg("page", 1, 1)
    limit = int_arg("limit", default_limit, 1, max_limit)
    return page, limit, (page - 1) * limit


def order_args(allowed_sort, default_sort):
    sort_by = request.args.get("sort_by", default_sort)
    if sort_by not in allowed_sort:
        raise ValueError(f"sort_by must be one of: {', '.join(sorted(allowed_sort))}")
    order = request.args.get("order", "desc").lower()
    if order not in {"asc", "desc"}:
        raise ValueError("order must be asc or desc")
    return allowed_sort[sort_by], order


def search_args():
    query = request.args.get("q", "").strip()
    if len(query) > 120:
        raise ValueError("q must be at most 120 characters")
    limit = int_arg("limit", 10, 1, 25)
    return query, limit


def response(payload, status=200):
    return jsonify(payload), status


@app.errorhandler(ValueError)
def bad_request(error):
    return response({"error": "bad_request", "message": str(error)}, 400)


@app.errorhandler(psycopg2.Error)
def database_error(error):
    status = 503 if isinstance(error, psycopg2.OperationalError) else 500
    return response({"error": "database_error", "message": "Database operation failed"}, status)


@app.errorhandler(404)
def not_found(error):
    return response({"error": "not_found", "message": "Resource not found"}, 404)


@app.errorhandler(Exception)
def unhandled(error):
    return response({"error": "internal_error", "message": "Unexpected server error"}, 500)


@app.get("/health")
def health():
    try:
        run_query("SELECT 1 AS ok", one=True)
    except psycopg2.Error:
        return response({"status": "error", "database": "unavailable"}, 503)
    return jsonify({"status": "ok", "database": "connected"})


@app.get("/api/dashboard")
def dashboard():
    counts = run_query(
        """
        SELECT
          (SELECT COUNT(*) FROM tournaments)::int AS tournament_count,
          (SELECT COUNT(*) FROM teams)::int AS team_count,
          (SELECT COUNT(*) FROM matches)::int AS match_count,
          (SELECT COUNT(*) FROM goals)::int AS goal_count,
          (SELECT COUNT(*) FROM players)::int AS player_count,
          (SELECT COUNT(*) FROM player_appearances)::int AS player_appearance_count
        """,
        one=True,
    )
    goals_by_tournament = run_query(
        """
        SELECT tr.year, COUNT(g.goal_id)::int AS goals, COUNT(DISTINCT m.match_id)::int AS matches
        FROM tournaments tr
        LEFT JOIN matches m ON m.tournament_id = tr.tournament_id
        LEFT JOIN goals g ON g.match_id = m.match_id
        GROUP BY tr.tournament_id
        ORDER BY tr.year
        """
    )
    teams_with_most_wins = run_query(team_stats_sql("ORDER BY wins DESC, goals_for DESC, team ASC LIMIT 10"))
    top_scorers = run_query(top_scorers_sql("LIMIT %s"), (None, None, 10))
    stadiums = run_query(
        """
        SELECT s.stadium_id, s.name, s.city, COUNT(m.match_id)::int AS matches
        FROM stadiums s
        JOIN matches m ON m.stadium_id = s.stadium_id
        GROUP BY s.stadium_id
        ORDER BY matches DESC, s.name
        LIMIT 10
        """
    )
    player_highlights = run_query(
        """
        WITH app_totals AS (
          SELECT player_id, COUNT(*)::int AS appearances
          FROM player_appearances
          GROUP BY player_id
        ),
        goal_totals AS (
          SELECT player_id, COUNT(*)::int AS goals
          FROM goals
          WHERE player_id IS NOT NULL AND NOT is_own_goal
          GROUP BY player_id
        ),
        player_totals AS (
          SELECT p.player_id, p.canonical_name AS player,
                 COALESCE(a.appearances, 0) AS appearances,
                 COALESCE(g.goals, 0) AS goals
          FROM players p
          LEFT JOIN app_totals a ON a.player_id = p.player_id
          LEFT JOIN goal_totals g ON g.player_id = p.player_id
        ),
        tournament_goals AS (
          SELECT p.player_id, p.canonical_name AS player, tr.year, COUNT(g.goal_id)::int AS goals
          FROM goals g
          JOIN players p ON p.player_id = g.player_id
          JOIN tournaments tr ON tr.tournament_id = g.tournament_id
          WHERE NOT g.is_own_goal
          GROUP BY p.player_id, tr.year
        )
        SELECT
          (SELECT row_to_json(x) FROM (SELECT player, goals FROM player_totals ORDER BY goals DESC, player LIMIT 1) x) AS top_scorer,
          (SELECT row_to_json(x) FROM (SELECT player, appearances FROM player_totals ORDER BY appearances DESC, player LIMIT 1) x) AS most_appearances,
          (SELECT row_to_json(x) FROM (SELECT player, year, goals FROM tournament_goals ORDER BY goals DESC, year LIMIT 1) x) AS most_goals_one_tournament
        """
    , one=True)
    return jsonify(
        {
            "counts": counts,
            "goals_by_tournament": goals_by_tournament,
            "teams_with_most_wins": teams_with_most_wins,
            "top_scorers": top_scorers,
            "stadiums_with_most_matches": stadiums,
            "player_highlights": player_highlights,
        }
    )


def team_stats_sql(tail=""):
    return f"""
    WITH appearances AS (
      SELECT home_team_id AS team_id, home_score AS gf, away_score AS ga
      FROM matches WHERE home_score IS NOT NULL
      UNION ALL
      SELECT away_team_id, away_score, home_score
      FROM matches WHERE away_score IS NOT NULL
    )
    SELECT
      t.team_id,
      t.canonical_name AS team,
      COUNT(a.team_id)::int AS played,
      COALESCE(SUM((a.gf > a.ga)::int), 0)::int AS wins,
      COALESCE(SUM((a.gf = a.ga)::int), 0)::int AS draws,
      COALESCE(SUM((a.gf < a.ga)::int), 0)::int AS losses,
      COALESCE(SUM(a.gf), 0)::int AS goals_for,
      COALESCE(SUM(a.ga), 0)::int AS goals_against,
      ROUND(COALESCE(100.0 * SUM((a.gf > a.ga)::int) / NULLIF(COUNT(a.team_id), 0), 0), 1) AS win_rate
    FROM teams t
    LEFT JOIN appearances a ON a.team_id = t.team_id
    GROUP BY t.team_id
    {tail}
    """


def top_scorers_sql(tail=""):
    return f"""
    SELECT p.player_id, p.canonical_name AS player, tm.canonical_name AS team,
           COUNT(g.goal_id)::int AS goals
    FROM goals g
    JOIN players p ON p.player_id = g.player_id
    JOIN teams tm ON tm.team_id = g.team_id
    JOIN tournaments tr ON tr.tournament_id = g.tournament_id
    WHERE NOT g.is_own_goal
      AND (%s IS NULL OR tr.year = %s)
    GROUP BY p.player_id, tm.team_id
    ORDER BY goals DESC, player ASC
    {tail}
    """


def player_totals_sql(where_tail=""):
    return f"""
    WITH appearances AS (
      SELECT player_id,
             COUNT(DISTINCT match_id)::int AS appearances,
             COUNT(DISTINCT match_id) FILTER (WHERE started IS TRUE)::int AS starts,
             COUNT(DISTINCT match_id) FILTER (WHERE started IS FALSE)::int AS substitute_appearances,
             SUM(minutes_played)::int AS minutes_played
      FROM player_appearances
      GROUP BY player_id
    ),
    tournaments AS (
      SELECT player_id, COUNT(DISTINCT tournament_id)::int AS tournament_appearances
      FROM player_tournaments
      GROUP BY player_id
    ),
    goal_totals AS (
      SELECT player_id,
             COUNT(*)::int AS goals,
             COALESCE(SUM((is_penalty IS TRUE)::int), 0)::int AS penalty_goals
      FROM goals
      WHERE player_id IS NOT NULL AND NOT is_own_goal
      GROUP BY player_id
    ),
    assists AS (
      SELECT player_id,
             COALESCE(SUM(assists), 0)::int AS assists
      FROM player_match_stats
      WHERE assists IS NOT NULL
      GROUP BY player_id
    )
      SELECT
        p.player_id,
        p.canonical_name AS player,
        p.birth_date,
        p.country_of_birth,
        p.preferred_position,
        COALESCE(a.appearances, 0) AS appearances,
        COALESCE(a.starts, 0) AS starts,
        COALESCE(a.substitute_appearances, 0) AS substitute_appearances,
        a.minutes_played,
        COALESCE(t.tournament_appearances, 0) AS tournament_appearances,
        COALESCE(g.goals, 0) AS goals,
        COALESCE(g.penalty_goals, 0) AS penalty_goals,
        COALESCE(ast.assists, 0) AS assists,
        ROUND(COALESCE(g.goals, 0)::numeric / NULLIF(a.appearances, 0), 3) AS goals_per_match
      FROM players p
      LEFT JOIN appearances a ON a.player_id = p.player_id
      LEFT JOIN tournaments t ON t.player_id = p.player_id
      LEFT JOIN goal_totals g ON g.player_id = p.player_id
      LEFT JOIN assists ast ON ast.player_id = p.player_id
    {where_tail}
    """


@app.get("/api/search/teams")
def search_teams():
    query, limit = search_args()
    if not query:
        return jsonify([])
    return jsonify(
        run_query(
            """
            SELECT team_id AS id, canonical_name AS label
            FROM teams
            WHERE canonical_name ILIKE '%%' || %s || '%%'
            ORDER BY
              CASE
                WHEN LOWER(canonical_name) = LOWER(%s) THEN 0
                WHEN canonical_name ILIKE %s || '%%' THEN 1
                WHEN canonical_name ILIKE '%% ' || %s || '%%' THEN 2
                ELSE 3
              END,
              canonical_name
            LIMIT %s
            """,
            (query, query, query, query, limit),
        )
    )


@app.get("/api/search/players")
def search_players():
    query, limit = search_args()
    if not query:
        return jsonify([])
    return jsonify(
        run_query(
            """
            WITH candidates AS (
              SELECT p.player_id,
                     p.canonical_name,
                     p.birth_date,
                     STRING_AGG(DISTINCT tm.canonical_name, ', ' ORDER BY tm.canonical_name) AS teams,
                     MIN(
                       CASE
                         WHEN LOWER(p.canonical_name) = LOWER(%s) THEN 0
                         WHEN EXISTS (
                           SELECT 1 FROM player_aliases pa
                           WHERE pa.player_id = p.player_id AND LOWER(pa.original_name) = LOWER(%s)
                         ) THEN 0
                         WHEN p.canonical_name ILIKE %s || '%%' THEN 1
                         WHEN EXISTS (
                           SELECT 1 FROM player_aliases pa
                           WHERE pa.player_id = p.player_id AND pa.original_name ILIKE %s || '%%'
                         ) THEN 1
                         ELSE 2
                       END
                     ) AS rank
              FROM players p
              LEFT JOIN player_aliases pa ON pa.player_id = p.player_id
              LEFT JOIN player_tournaments pt ON pt.player_id = p.player_id
              LEFT JOIN teams tm ON tm.team_id = pt.team_id
              WHERE p.canonical_name ILIKE '%%' || %s || '%%'
                 OR pa.original_name ILIKE '%%' || %s || '%%'
                 OR pa.normalized_name ILIKE '%%' || %s || '%%'
              GROUP BY p.player_id
            )
            SELECT player_id AS id,
                   canonical_name AS label,
                   TRIM(BOTH ' · ' FROM CONCAT_WS(' · ', NULLIF(teams, ''), CASE WHEN birth_date IS NOT NULL THEN 'b. ' || EXTRACT(YEAR FROM birth_date)::int::text END)) AS description
            FROM candidates
            ORDER BY
              rank,
              canonical_name
            LIMIT %s
            """,
            (query, query, query, query, query, query, normalize_person_name(query), limit),
        )
    )


@app.get("/api/tournaments")
def tournaments():
    rows = run_query(
        """
        WITH match_counts AS (
          SELECT tournament_id, COUNT(*)::int AS matches
          FROM matches GROUP BY tournament_id
        ),
        goal_counts AS (
          SELECT tournament_id, COUNT(*)::int AS goals
          FROM goals GROUP BY tournament_id
        ),
        team_counts AS (
          SELECT tournament_id, COUNT(DISTINCT team_id)::int AS teams
          FROM (
            SELECT tournament_id, home_team_id AS team_id FROM matches
            UNION ALL
            SELECT tournament_id, away_team_id AS team_id FROM matches
          ) sides
          GROUP BY tournament_id
        )
        SELECT tr.tournament_id, tr.year, tr.name,
               COALESCE(mc.matches, 0) AS matches,
               COALESCE(tc.teams, 0) AS teams,
               COALESCE(gc.goals, 0) AS goals,
               ROUND(COALESCE(gc.goals, 0)::numeric / NULLIF(mc.matches, 0), 2) AS goals_per_match
        FROM tournaments tr
        LEFT JOIN match_counts mc ON mc.tournament_id = tr.tournament_id
        LEFT JOIN goal_counts gc ON gc.tournament_id = tr.tournament_id
        LEFT JOIN team_counts tc ON tc.tournament_id = tr.tournament_id
        ORDER BY tr.year
        """
    )
    return jsonify(rows)


@app.get("/api/tournaments/<int:year>")
def tournament_detail(year):
    tournament = run_query(
        """
        SELECT tr.tournament_id, tr.year, tr.name,
               COUNT(DISTINCT m.match_id)::int AS matches,
               COUNT(g.goal_id)::int AS goals
        FROM tournaments tr
        LEFT JOIN matches m ON m.tournament_id = tr.tournament_id
        LEFT JOIN goals g ON g.match_id = m.match_id
        WHERE tr.year = %s
        GROUP BY tr.tournament_id
        """,
        (year,),
        one=True,
    )
    if not tournament:
        return response({"error": "not_found", "message": f"Tournament {year} not found"}, 404)
    matches = match_rows("WHERE tr.year = %s ORDER BY m.match_date, m.match_id", (year,))
    teams = run_query(
        """
        SELECT DISTINCT tm.team_id, tm.canonical_name AS team
        FROM matches m
        JOIN tournaments tr ON tr.tournament_id = m.tournament_id
        JOIN teams tm ON tm.team_id IN (m.home_team_id, m.away_team_id)
        WHERE tr.year = %s
        ORDER BY tm.canonical_name
        """,
        (year,),
    )
    top_scorers = run_query(top_scorers_sql("LIMIT %s"), (year, year, 10))
    return jsonify({"tournament": tournament, "matches": matches, "teams": teams, "top_scorers": top_scorers})


@app.get("/api/teams")
def teams():
    search = request.args.get("search", "").strip()
    page, limit, offset = pagination_args(max_limit=500)
    sort_sql, order = order_args(
        {
            "team": "team",
            "played": "played",
            "wins": "wins",
            "draws": "draws",
            "losses": "losses",
            "goals_for": "goals_for",
            "goals_against": "goals_against",
            "win_rate": "win_rate",
        },
        "wins",
    )
    params = (search, search, limit, offset)
    rows = run_query(
        f"""
        WITH stats AS ({team_stats_sql()})
        SELECT * FROM stats
        WHERE (%s = '' OR team ILIKE '%%' || %s || '%%')
        ORDER BY {sort_sql} {order.upper()}, team ASC
        LIMIT %s OFFSET %s
        """,
        params,
    )
    total = run_query(
        """
        SELECT COUNT(*)::int AS total
        FROM teams
        WHERE (%s = '' OR canonical_name ILIKE '%%' || %s || '%%')
        """,
        (search, search),
        one=True,
    )["total"]
    return jsonify({"results": rows, "pagination": {"page": page, "limit": limit, "total": total}})


@app.get("/api/teams/<int:team_id>")
def team_detail(team_id):
    team = run_query(f"WITH stats AS ({team_stats_sql()}) SELECT * FROM stats WHERE team_id = %s", (team_id,), one=True)
    if not team:
        return response({"error": "not_found", "message": f"Team {team_id} not found"}, 404)
    appearances = run_query(
        """
        SELECT tr.year,
               COUNT(m.match_id)::int AS matches,
               SUM(CASE WHEN m.home_team_id = %s THEN m.home_score ELSE m.away_score END)::int AS goals_for
        FROM matches m
        JOIN tournaments tr ON tr.tournament_id = m.tournament_id
        WHERE m.home_team_id = %s OR m.away_team_id = %s
        GROUP BY tr.year
        ORDER BY tr.year
        """,
        (team_id, team_id, team_id),
    )
    history = match_rows(
        "WHERE m.home_team_id = %s OR m.away_team_id = %s ORDER BY m.match_date DESC, m.match_id DESC LIMIT 100",
        (team_id, team_id),
    )
    return jsonify({"team": team, "tournament_appearances": appearances, "match_history": history})


def match_rows(where_clause="", params=()):
    return run_query(
        f"""
        SELECT m.match_id, tr.year, m.match_date, m.kickoff_time, m.stage, m.group_name,
               h.team_id AS home_team_id, h.canonical_name AS home_team,
               a.team_id AS away_team_id, a.canonical_name AS away_team,
               m.home_score, m.away_score, s.stadium_id, s.name AS stadium, s.city
        FROM matches m
        JOIN tournaments tr ON tr.tournament_id = m.tournament_id
        JOIN teams h ON h.team_id = m.home_team_id
        JOIN teams a ON a.team_id = m.away_team_id
        LEFT JOIN stadiums s ON s.stadium_id = m.stadium_id
        {where_clause}
        """,
        params,
    )


@app.get("/api/matches")
def matches():
    page, limit, offset = pagination_args()
    year = int_arg("year", None, 1930, 2100)
    team = request.args.get("team", "").strip()
    stage = request.args.get("stage", "").strip()
    stadium = request.args.get("stadium", "").strip()
    search = request.args.get("search", "").strip()
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    for name, value in (("date_from", date_from), ("date_to", date_to)):
        if value:
            try:
                date.fromisoformat(value)
            except ValueError as exc:
                raise ValueError(f"{name} must use YYYY-MM-DD") from exc

    filters = [
        "(%s IS NULL OR tr.year = %s)",
        "(%s = '' OR h.canonical_name ILIKE '%%' || %s || '%%' OR a.canonical_name ILIKE '%%' || %s || '%%')",
        "(%s = '' OR m.stage ILIKE '%%' || %s || '%%')",
        "(%s = '' OR s.name ILIKE '%%' || %s || '%%' OR s.city ILIKE '%%' || %s || '%%')",
        "(%s IS NULL OR m.match_date >= %s::date)",
        "(%s IS NULL OR m.match_date <= %s::date)",
        "(%s = '' OR h.canonical_name ILIKE '%%' || %s || '%%' OR a.canonical_name ILIKE '%%' || %s || '%%' OR m.stage ILIKE '%%' || %s || '%%')",
    ]
    params = (
        year, year,
        team, team, team,
        stage, stage,
        stadium, stadium, stadium,
        date_from, date_from,
        date_to, date_to,
        search, search, search, search,
    )
    where = "WHERE " + " AND ".join(filters)
    rows = match_rows(f"{where} ORDER BY m.match_date DESC, m.match_id DESC LIMIT %s OFFSET %s", params + (limit, offset))
    total = run_query(
        f"""
        SELECT COUNT(*)::int AS total
        FROM matches m
        JOIN tournaments tr ON tr.tournament_id = m.tournament_id
        JOIN teams h ON h.team_id = m.home_team_id
        JOIN teams a ON a.team_id = m.away_team_id
        LEFT JOIN stadiums s ON s.stadium_id = m.stadium_id
        {where}
        """,
        params,
        one=True,
    )["total"]
    return jsonify({"results": rows, "pagination": {"page": page, "limit": limit, "total": total}})


@app.get("/api/players")
def players():
    search = request.args.get("search", "").strip()
    team = request.args.get("team", "").strip()
    tournament = int_arg("tournament", None, 1930, 2100)
    position = request.args.get("position", "").strip()
    page, limit, offset = pagination_args(default_limit=25, max_limit=100)
    sort_sql, order = order_args(
        {
            "name": "player",
            "goals": "goals",
            "appearances": "appearances",
            "starts": "starts",
        },
        "goals",
    )
    filters = [
        "(%s = '' OR p.player ILIKE '%%' || %s || '%%')",
        "(%s = '' OR EXISTS (SELECT 1 FROM player_tournaments pt JOIN teams tm ON tm.team_id = pt.team_id WHERE pt.player_id = p.player_id AND tm.canonical_name ILIKE '%%' || %s || '%%'))",
        "(%s IS NULL OR EXISTS (SELECT 1 FROM player_tournaments pt JOIN tournaments tr ON tr.tournament_id = pt.tournament_id WHERE pt.player_id = p.player_id AND tr.year = %s))",
        "(%s = '' OR p.preferred_position ILIKE '%%' || %s || '%%' OR EXISTS (SELECT 1 FROM player_tournaments pt WHERE pt.player_id = p.player_id AND pt.position ILIKE '%%' || %s || '%%'))",
    ]
    params = (search, search, team, team, tournament, tournament, position, position, position)
    where = "WHERE " + " AND ".join(filters)
    rows = run_query(
        f"""
        SELECT *
        FROM ({player_totals_sql()}) p
        {where}
        ORDER BY {sort_sql} {order.upper()} NULLS LAST, player ASC
        LIMIT %s OFFSET %s
        """,
        params + (limit, offset),
    )
    total = run_query(
        f"""
        SELECT COUNT(*)::int AS total
        FROM ({player_totals_sql()}) p
        {where}
        """,
        params,
        one=True,
    )["total"]
    return jsonify({"results": rows, "pagination": {"page": page, "limit": limit, "total": total}})


@app.get("/api/players/top-scorers")
def top_scorers():
    year = int_arg("year", None, 1930, 2100)
    team = request.args.get("team", "").strip()
    minimum_appearances = int_arg("minimum_appearances", 0, 0, 100)
    limit = int_arg("limit", 20, 1, 100)
    rows = run_query(
        """
        WITH appearances AS (
          SELECT pa.player_id, COUNT(*)::int AS appearances
          FROM player_appearances pa
          JOIN matches m ON m.match_id = pa.match_id
          JOIN tournaments tr ON tr.tournament_id = m.tournament_id
          JOIN teams tm ON tm.team_id = pa.team_id
          WHERE (%s IS NULL OR tr.year = %s)
            AND (%s = '' OR tm.canonical_name ILIKE '%%' || %s || '%%')
          GROUP BY pa.player_id
        ),
        goal_totals AS (
          SELECT g.player_id, COUNT(*)::int AS goals
          FROM goals g
          JOIN tournaments tr ON tr.tournament_id = g.tournament_id
          JOIN teams tm ON tm.team_id = g.team_id
          WHERE g.player_id IS NOT NULL
            AND NOT g.is_own_goal
            AND (%s IS NULL OR tr.year = %s)
            AND (%s = '' OR tm.canonical_name ILIKE '%%' || %s || '%%')
          GROUP BY g.player_id
        )
        SELECT p.player_id, p.canonical_name AS player,
               COALESCE(a.appearances, 0) AS appearances,
               COALESCE(gt.goals, 0) AS goals,
               ROUND(COALESCE(gt.goals, 0)::numeric / NULLIF(a.appearances, 0), 3) AS goals_per_match
        FROM players p
        LEFT JOIN appearances a ON a.player_id = p.player_id
        LEFT JOIN goal_totals gt ON gt.player_id = p.player_id
        WHERE COALESCE(a.appearances, 0) >= %s
        ORDER BY goals DESC, goals_per_match DESC NULLS LAST, player ASC
        LIMIT %s
        """,
        (year, year, team, team, year, year, team, team, minimum_appearances, limit),
    )
    return jsonify(rows)


@app.get("/api/players/leaderboards")
def player_leaderboards():
    min_apps = int_arg("minimum_appearances", 5, 1, 100)
    top = lambda order: run_query(f"SELECT * FROM ({player_totals_sql()}) p ORDER BY {order} LIMIT 10")
    goals_per_match = run_query(
        f"""
        SELECT * FROM ({player_totals_sql()}) p
        WHERE appearances >= %s
        ORDER BY goals_per_match DESC NULLS LAST, goals DESC, player
        LIMIT 10
        """,
        (min_apps,),
    )
    return jsonify(
        {
            "goals": top("goals DESC, player ASC"),
            "appearances": top("appearances DESC, player ASC"),
            "starts": top("starts DESC, player ASC"),
            "substitute_appearances": top("substitute_appearances DESC, player ASC"),
            "minutes_played": top("minutes_played DESC NULLS LAST, player ASC"),
            "goals_per_match": goals_per_match,
            "assists": top("assists DESC, player ASC"),
        }
    )


@app.get("/api/players/<int:player_id>")
def player_detail(player_id):
    profile = run_query(f"SELECT * FROM ({player_totals_sql()}) p WHERE player_id = %s", (player_id,), one=True)
    if not profile:
        return response({"error": "not_found", "message": f"Player {player_id} not found"}, 404)
    teams = run_query(
        """
        SELECT DISTINCT tm.team_id, tm.canonical_name AS team
        FROM player_tournaments pt
        JOIN teams tm ON tm.team_id = pt.team_id
        WHERE pt.player_id = %s
        ORDER BY team
        """,
        (player_id,),
    )
    tournaments_rows = run_query(
        """
        SELECT tr.year, tm.canonical_name AS team, pt.shirt_number, pt.position,
               COUNT(DISTINCT pa.match_id)::int AS appearances,
               COUNT(DISTINCT pa.match_id) FILTER (WHERE pa.started IS TRUE)::int AS starts,
               COUNT(DISTINCT g.goal_id)::int AS goals
        FROM player_tournaments pt
        JOIN tournaments tr ON tr.tournament_id = pt.tournament_id
        JOIN teams tm ON tm.team_id = pt.team_id
        LEFT JOIN matches m ON m.tournament_id = tr.tournament_id AND (m.home_team_id = tm.team_id OR m.away_team_id = tm.team_id)
        LEFT JOIN player_appearances pa ON pa.player_id = pt.player_id AND pa.match_id = m.match_id
        LEFT JOIN goals g ON g.player_id = pt.player_id AND g.tournament_id = tr.tournament_id AND NOT g.is_own_goal
        WHERE pt.player_id = %s
        GROUP BY tr.year, tm.canonical_name, pt.shirt_number, pt.position
        ORDER BY tr.year
        """,
        (player_id,),
    )
    history = player_match_history(player_id, 1, 25)["results"]
    coverage = run_query(
        """
        SELECT source_id, source_name, dataset_name, coverage_year, match_count, notes
        FROM source_metadata
        WHERE source_id IN ('fjelstul', 'statsbomb', 'espn_2026')
        ORDER BY source_id, coverage_year NULLS FIRST, dataset_name
        """
    )
    return jsonify({"profile": profile, "teams": teams, "tournaments": tournaments_rows, "match_history": history, "coverage": coverage})


def player_match_history(player_id, page, limit):
    offset = (page - 1) * limit
    rows = run_query(
        """
        SELECT m.match_id, tr.year, m.match_date, h.canonical_name AS home_team,
               a.canonical_name AS away_team, m.home_score, m.away_score,
               tm.canonical_name AS team, pa.started, pa.minutes_played,
               fs.goals, fs.penalties_scored,
               COALESCE(SUM(pms.assists), 0)::int AS assists
        FROM player_appearances pa
        JOIN matches m ON m.match_id = pa.match_id
        JOIN tournaments tr ON tr.tournament_id = m.tournament_id
        JOIN teams h ON h.team_id = m.home_team_id
        JOIN teams a ON a.team_id = m.away_team_id
        JOIN teams tm ON tm.team_id = pa.team_id
        LEFT JOIN player_match_stats fs ON fs.player_id = pa.player_id AND fs.match_id = pa.match_id AND fs.source_id = 'fjelstul'
        LEFT JOIN player_match_stats pms ON pms.player_id = pa.player_id AND pms.match_id = pa.match_id AND pms.assists IS NOT NULL
        WHERE pa.player_id = %s
        GROUP BY m.match_id, tr.year, m.match_date, h.canonical_name, a.canonical_name,
                 m.home_score, m.away_score, tm.canonical_name, pa.started, pa.minutes_played,
                 fs.goals, fs.penalties_scored
        ORDER BY m.match_date DESC, m.match_id DESC
        LIMIT %s OFFSET %s
        """,
        (player_id, limit, offset),
    )
    total = run_query("SELECT COUNT(*)::int AS total FROM player_appearances WHERE player_id = %s", (player_id,), one=True)["total"]
    return {"results": rows, "pagination": {"page": page, "limit": limit, "total": total}}


@app.get("/api/players/<int:player_id>/matches")
def player_matches(player_id):
    page, limit, _ = pagination_args(default_limit=25, max_limit=100)
    exists = run_query("SELECT player_id FROM players WHERE player_id = %s", (player_id,), one=True)
    if not exists:
        return response({"error": "not_found", "message": f"Player {player_id} not found"}, 404)
    return jsonify(player_match_history(player_id, page, limit))


@app.get("/api/players/compare")
def compare_players():
    player1 = int_arg("player1", None, 1)
    player2 = int_arg("player2", None, 1)
    if not player1 or not player2:
        raise ValueError("player1 and player2 are required")
    if player1 == player2:
        raise ValueError("player1 and player2 must be different")
    rows = run_query(f"SELECT * FROM ({player_totals_sql()}) p WHERE player_id IN (%s, %s)", (player1, player2))
    if len(rows) != 2:
        return response({"error": "not_found", "message": "One or both players were not found"}, 404)
    by_id = {row["player_id"]: row for row in rows}
    return jsonify({"player1": by_id[player1], "player2": by_id[player2]})


def team_comparison(team_id):
    stats = run_query(f"WITH stats AS ({team_stats_sql()}) SELECT * FROM stats WHERE team_id = %s", (team_id,), one=True)
    if not stats:
        return None
    appearances = run_query(
        """
        SELECT COUNT(DISTINCT tournament_id)::int AS tournament_appearances
        FROM matches
        WHERE home_team_id = %s OR away_team_id = %s
        """,
        (team_id, team_id),
        one=True,
    )
    best = run_query(
        """
        SELECT tr.year, COUNT(g.goal_id)::int AS goals
        FROM tournaments tr
        JOIN matches m ON m.tournament_id = tr.tournament_id
        LEFT JOIN goals g ON g.match_id = m.match_id AND g.team_id = %s
        WHERE m.home_team_id = %s OR m.away_team_id = %s
        GROUP BY tr.year
        ORDER BY goals DESC, tr.year ASC
        LIMIT 1
        """,
        (team_id, team_id, team_id),
        one=True,
    )
    stats["tournament_appearances"] = appearances["tournament_appearances"]
    stats["best_tournament_by_goals"] = best
    return stats


@app.get("/api/compare")
def compare():
    team1 = int_arg("team1", None, 1)
    team2 = int_arg("team2", None, 1)
    if not team1 or not team2:
        raise ValueError("team1 and team2 are required")
    if team1 == team2:
        raise ValueError("team1 and team2 must be different")
    left = team_comparison(team1)
    right = team_comparison(team2)
    if not left or not right:
        return response({"error": "not_found", "message": "One or both teams were not found"}, 404)
    return jsonify({"team1": left, "team2": right})


@app.get("/api/data-quality")
def data_quality():
    metrics = run_query("SELECT * FROM data_quality_metrics WHERE metric_id = 1", one=True)
    sources = run_query("SELECT * FROM data_quality_sources ORDER BY tournament_year, source_file")
    source_metadata = run_query(
        """
        SELECT source_id, source_name, dataset_name, coverage_year, competition_id, season_id, match_count, file_path, notes
        FROM source_metadata
        ORDER BY source_id, coverage_year NULLS FIRST, dataset_name
        """
    )
    issues = run_query(
        """
        SELECT issue_type, COUNT(*)::int AS count
        FROM data_quality_issues
        GROUP BY issue_type
        ORDER BY count DESC, issue_type
        """
    )
    aliases = run_query(
        """
        SELECT ta.alias AS original_name, tm.canonical_name AS canonical_name
        FROM team_aliases ta
        JOIN teams tm ON tm.team_id = ta.team_id
        WHERE ta.alias <> tm.canonical_name
        ORDER BY ta.alias
        """
    )
    player_aliases = run_query(
        """
        SELECT pa.original_name, p.canonical_name, pa.source_id
        FROM player_aliases pa
        JOIN players p ON p.player_id = pa.player_id
        WHERE pa.original_name <> p.canonical_name OR pa.source_id <> 'fjelstul'
        ORDER BY pa.source_id, pa.original_name
        LIMIT 500
        """
    )
    return jsonify({"metrics": metrics or {}, "sources": sources, "source_metadata": source_metadata, "issues": issues, "alias_mappings": aliases, "player_aliases": player_aliases})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "3001")), debug=os.getenv("FLASK_DEBUG") == "1")
