-- 1. Dashboard KPI counts
SELECT
  (SELECT COUNT(*) FROM tournaments)::int AS tournament_count,
  (SELECT COUNT(*) FROM teams)::int AS team_count,
  (SELECT COUNT(*) FROM matches)::int AS match_count,
  (SELECT COUNT(*) FROM goals)::int AS goal_count;

-- 2. Goals by tournament
SELECT tr.year, COUNT(g.goal_id)::int AS goals, COUNT(DISTINCT m.match_id)::int AS matches
FROM tournaments tr
LEFT JOIN matches m ON m.tournament_id = tr.tournament_id
LEFT JOIN goals g ON g.match_id = m.match_id
GROUP BY tr.tournament_id
ORDER BY tr.year;

-- 3. All-time team table with wins, draws, losses, goals, and win rate
WITH appearances AS (
  SELECT home_team_id AS team_id, home_score AS gf, away_score AS ga
  FROM matches WHERE home_score IS NOT NULL
  UNION ALL
  SELECT away_team_id, away_score, home_score
  FROM matches WHERE away_score IS NOT NULL
)
SELECT t.canonical_name AS team,
       COUNT(a.team_id)::int AS played,
       SUM((a.gf > a.ga)::int)::int AS wins,
       SUM((a.gf = a.ga)::int)::int AS draws,
       SUM((a.gf < a.ga)::int)::int AS losses,
       SUM(a.gf)::int AS goals_for,
       SUM(a.ga)::int AS goals_against,
       ROUND(100.0 * SUM((a.gf > a.ga)::int) / NULLIF(COUNT(a.team_id), 0), 1) AS win_rate
FROM teams t
LEFT JOIN appearances a ON a.team_id = t.team_id
GROUP BY t.team_id
ORDER BY wins DESC, goals_for DESC, team ASC;

-- 4. Match filtering by year, team, stage, stadium, and date range
SELECT m.match_id, tr.year, m.match_date, m.stage,
       h.canonical_name AS home_team, a.canonical_name AS away_team,
       m.home_score, m.away_score, s.name AS stadium, s.city
FROM matches m
JOIN tournaments tr ON tr.tournament_id = m.tournament_id
JOIN teams h ON h.team_id = m.home_team_id
JOIN teams a ON a.team_id = m.away_team_id
LEFT JOIN stadiums s ON s.stadium_id = m.stadium_id
WHERE tr.year = 2022
  AND (h.canonical_name ILIKE '%Argentina%' OR a.canonical_name ILIKE '%Argentina%')
  AND m.stage ILIKE '%Final%'
ORDER BY m.match_date DESC;

-- 5. Top scorers, excluding own goals
SELECT p.normalized_name AS player, tm.canonical_name AS team, COUNT(g.goal_id)::int AS goals
FROM goals g
JOIN players p ON p.player_id = g.player_id
JOIN teams tm ON tm.team_id = g.team_id
JOIN tournaments tr ON tr.tournament_id = g.tournament_id
WHERE NOT g.is_own_goal
GROUP BY p.player_id, tm.team_id
ORDER BY goals DESC, player ASC
LIMIT 20;

-- 6. Team comparison helper: best tournament by goals
SELECT tr.year, COUNT(g.goal_id)::int AS goals
FROM tournaments tr
JOIN matches m ON m.tournament_id = tr.tournament_id
LEFT JOIN goals g ON g.match_id = m.match_id AND g.team_id = 1
WHERE m.home_team_id = 1 OR m.away_team_id = 1
GROUP BY tr.year
ORDER BY goals DESC, tr.year ASC
LIMIT 1;

-- 7. Data-quality alias mappings
SELECT ta.alias AS original_name, tm.canonical_name AS canonical_name
FROM team_aliases ta
JOIN teams tm ON tm.team_id = ta.team_id
WHERE ta.alias <> tm.canonical_name
ORDER BY ta.alias;

-- 8. All-time player top scorers
SELECT p.player_id, p.canonical_name AS player, COUNT(g.goal_id)::int AS goals
FROM goals g
JOIN players p ON p.player_id = g.player_id
WHERE NOT g.is_own_goal
GROUP BY p.player_id
ORDER BY goals DESC, player ASC
LIMIT 20;

-- 9. Top scorer per tournament using a window function
WITH tournament_scorers AS (
  SELECT tr.year, p.player_id, p.canonical_name AS player, COUNT(g.goal_id)::int AS goals
  FROM goals g
  JOIN tournaments tr ON tr.tournament_id = g.tournament_id
  JOIN players p ON p.player_id = g.player_id
  WHERE NOT g.is_own_goal
  GROUP BY tr.year, p.player_id
),
ranked AS (
  SELECT *, DENSE_RANK() OVER (PARTITION BY year ORDER BY goals DESC, player ASC) AS scorer_rank
  FROM tournament_scorers
)
SELECT year, player, goals
FROM ranked
WHERE scorer_rank = 1
ORDER BY year;

-- 10. Player tournament history
SELECT p.canonical_name AS player, tr.year, tm.canonical_name AS team,
       pt.shirt_number, pt.position, COUNT(pa.appearance_id)::int AS appearances
FROM player_tournaments pt
JOIN players p ON p.player_id = pt.player_id
JOIN tournaments tr ON tr.tournament_id = pt.tournament_id
JOIN teams tm ON tm.team_id = pt.team_id
LEFT JOIN matches m ON m.tournament_id = tr.tournament_id
LEFT JOIN player_appearances pa ON pa.player_id = p.player_id AND pa.match_id = m.match_id
GROUP BY p.player_id, tr.year, tm.canonical_name, pt.shirt_number, pt.position
ORDER BY player, tr.year;

-- 11. Goals per appearance
WITH appearances AS (
  SELECT player_id, COUNT(*)::numeric AS appearances
  FROM player_appearances
  GROUP BY player_id
),
goal_totals AS (
  SELECT player_id, COUNT(*)::numeric AS goals
  FROM goals
  WHERE player_id IS NOT NULL AND NOT is_own_goal
  GROUP BY player_id
)
SELECT p.canonical_name AS player, COALESCE(g.goals, 0) AS goals,
       a.appearances, ROUND(COALESCE(g.goals, 0) / NULLIF(a.appearances, 0), 3) AS goals_per_appearance
FROM players p
JOIN appearances a ON a.player_id = p.player_id
LEFT JOIN goal_totals g ON g.player_id = p.player_id
ORDER BY goals_per_appearance DESC NULLS LAST, goals DESC;

-- 12. Players who represented multiple teams
SELECT p.canonical_name AS player, COUNT(DISTINCT tm.team_id)::int AS teams_represented,
       STRING_AGG(DISTINCT tm.canonical_name, ', ' ORDER BY tm.canonical_name) AS teams
FROM player_tournaments pt
JOIN players p ON p.player_id = pt.player_id
JOIN teams tm ON tm.team_id = pt.team_id
GROUP BY p.player_id
HAVING COUNT(DISTINCT tm.team_id) > 1
ORDER BY teams_represented DESC, player;

-- 13. Player comparison core query
SELECT p.player_id, p.canonical_name AS player,
       COUNT(DISTINCT pa.appearance_id)::int AS appearances,
       COALESCE(SUM((pa.started IS TRUE)::int), 0)::int AS starts,
       COUNT(DISTINCT g.goal_id)::int AS goals,
       COUNT(DISTINCT b.booking_id) FILTER (WHERE b.card_type IN ('yellow', 'second_yellow'))::int AS yellow_cards,
       COUNT(DISTINCT b.booking_id) FILTER (WHERE b.card_type IN ('red', 'second_yellow'))::int AS red_cards
FROM players p
LEFT JOIN player_appearances pa ON pa.player_id = p.player_id
LEFT JOIN goals g ON g.player_id = p.player_id AND NOT g.is_own_goal
LEFT JOIN bookings b ON b.player_id = p.player_id
WHERE p.player_id IN (1, 2)
GROUP BY p.player_id;

-- 14. Advanced statistics coverage
SELECT tr.year, COUNT(DISTINCT s.match_id)::int AS covered_matches,
       COUNT(DISTINCT s.player_id)::int AS covered_players,
       SUM(s.shots)::int AS shots,
       ROUND(100.0 * SUM(s.passes_completed) / NULLIF(SUM(s.passes_attempted), 0), 1) AS pass_completion
FROM player_match_stats s
JOIN matches m ON m.match_id = s.match_id
JOIN tournaments tr ON tr.tournament_id = m.tournament_id
WHERE s.source_id = 'statsbomb'
GROUP BY tr.year
ORDER BY tr.year;
