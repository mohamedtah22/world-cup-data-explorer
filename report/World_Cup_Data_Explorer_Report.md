# World Cup Data Explorer Report

## Application Overview

World Cup Data Explorer is a full-stack data-management application for FIFA Men’s World Cup data through 2026. A Python ETL pipeline reads OpenFootball JSON, Fjelstul CSVs, StatsBomb open-data JSON, and cached ESPN 2026 public JSON, then loads PostgreSQL. A Flask API exposes SQL-backed dashboard, tournament, team, match, player, comparison, autocomplete, and data-quality endpoints. The React/Vite frontend requests final statistics from the Flask API; it does not use static dashboard JSON as a data source.

The verified final database load contains 1,069 canonical matches, 23 tournaments, 89 teams, 3,026 goals, 9,868 players, 23,906 linked player appearances, 27,934 player-match statistic rows, and 497,198 StatsBomb event rows. The completed 2026 tournament has 104 matches, 306 goals, no missing scores, and 3,288 ESPN-sourced player appearances.

## Data Sources and Descriptions

OpenFootball is the broad match source, including the 104-match 2026 tournament. It supplies most 2026 goals; ESPN fills only completed 2026 scores and goal events missing from OpenFootball.

Historical player data comes from Fjelstul World Cup Database CSV exports. Fjelstul is authoritative for men’s player identities, squads, appearances, goals, penalty kicks, bookings, substitutions, awards, and award winners through 2022 when its matches link to canonical OpenFootball matches. Women’s tournament rows in the upstream CSVs are filtered out.

ESPN public soccer JSON is an unofficial 2026 supplemental source. The downloader caches the scoreboard and 104 summary responses under `data/raw/espn_2026/`, with retries, timeout handling, a descriptive User-Agent, and `--refresh`. ESPN rosters provide 2026 appearances, starters, substitutions, cards, and supported player stats.

StatsBomb Open Data is advanced-event enrichment only. The loader detects available men’s World Cup seasons from `competitions.json` and downloads matches, lineups, and events only for those seasons. Verified coverage is 1958, 1962, 1970, 1974, 1986, 1990, 2018, and 2022; the app does not claim full historical advanced coverage.

## Data-Management Challenges

The source files combine semi-structured JSON, CSV tables, and nested event data, so the main work is cleaning, matching, and relational modeling rather than display design. Team names are not always stable across history, so the ETL maps known aliases into canonical teams while preserving the original labels in `team_aliases`.

Venue data is also inconsistent. Some rows use `Stadium, City`, while some newer rows contain a single location string or a parenthesized city. The ETL separates venue name and city when possible and uses explicit unknown values only for missing raw venues. Goal minutes can be integers, strings such as `90+4`, or an integer with an `offset`; these are converted into `minute` and `stoppage_minute` integer columns.

Player identity is resolved conservatively. Fjelstul external IDs are authoritative through 2022. ESPN player IDs are stored in `player_external_ids`. StatsBomb and ESPN names are matched by external ID first, otherwise by normalized full name plus team and known aliases. Controlled aliases handle source drift such as `Lionel Andrés Messi Cuccittini` to `Lionel Messi`; weak partial matches are not used. Unmatched or ambiguous rows are recorded in `data_quality_issues`.

OpenFootball goal-only players are later reconciled to canonical ESPN/Fjelstul players when a unique same-team alias exists, so rows such as `Messi`, `L. Messi`, and `Lionel Messi` do not split the same scorer’s facts. Non-Fjelstul goals are deleted only for matches successfully linked to Fjelstul, preserving 2026 OpenFootball goals and unmatched historical goals.

Unavailable advanced statistics are stored as `NULL`, not zero. A zero value means the event data covers that match and the event count is truly zero. `NULL` means the source does not provide that statistic for that player or match.

## Database Design

The PostgreSQL schema contains core match and player tables:

- `tournaments`: one row per World Cup edition.
- `teams`: canonical team entities.
- `team_aliases`: original source names mapped to canonical teams.
- `stadiums`: stadium and city entities.
- `matches`: match facts with tournament, team, venue, date, stage, and score references.
- `players`: canonical player identities with Fjelstul and StatsBomb external IDs.
- `player_aliases`: source-specific player names mapped to canonical players.
- `player_tournaments`: squads by player, tournament, and team.
- `player_appearances`: match appearances, starts, substitutions, captain, goalkeeper, and minutes when known.
- `player_match_stats`: per-match basic and advanced statistics with source provenance.
- `bookings` and `substitutions`: disciplinary and substitution facts.
- `player_external_ids`: ESPN and other non-core external player identifiers.
- `player_events`: StatsBomb raw event provenance and event metadata.
- `goals`: goal events linked to matches, players, teams, and tournaments.

Primary keys are defined for every table. Foreign keys enforce relationships from matches to tournaments, teams, stadiums, players, and source-specific facts. Unique constraints protect tournament years, canonical team names, aliases, source match keys, source goal keys, player appearances, source events, and external IDs. Check constraints validate year ranges, non-empty names, scores, minutes, and different home/away teams.

Readable ERD:

```text
tournaments 1--* matches *--1 teams (home/away)
matches *--0..1 stadiums
matches 1--* goals *--0..1 players
matches 1--* player_appearances *--1 players
players 1--* player_tournaments *--1 teams
players 1--* player_aliases
players 1--* player_external_ids
players 1--* player_match_stats *--1 matches
players 1--* bookings *--1 matches
matches 1--* substitutions
matches 1--* player_events
source_metadata and data_quality_* audit coverage and ETL issues
```

B-tree indexes support joins and filters by tournament, date, team, player, and event source. `pg_trgm` GIN indexes support substring autocomplete on team/player names. `EXPLAIN ANALYZE` for player search `messi` used `idx_players_name_trgm` with a Bitmap Index Scan and Bitmap Heap Scan in about 0.23 ms. Team search `arg` used a sequential scan in about 0.07 ms because the table has only 89 rows, making a scan cheaper.

## Representative SQL Queries

Dashboard KPI counts:

```sql
SELECT
  (SELECT COUNT(*) FROM tournaments)::int AS tournament_count,
  (SELECT COUNT(*) FROM teams)::int AS team_count,
  (SELECT COUNT(*) FROM matches)::int AS match_count,
  (SELECT COUNT(*) FROM goals)::int AS goal_count;
```

All-time team table:

```sql
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
```

All-time player top scorers:

```sql
SELECT p.canonical_name AS player, COUNT(g.goal_id)::int AS goals
FROM goals g
JOIN players p ON p.player_id = g.player_id
WHERE NOT g.is_own_goal
GROUP BY p.player_id
ORDER BY goals DESC, player ASC
LIMIT 20;
```

Autocomplete search:

```sql
SELECT player_id AS id, canonical_name AS label
FROM players
WHERE canonical_name ILIKE '%' || 'messi' || '%'
ORDER BY
  CASE
    WHEN LOWER(canonical_name) = LOWER('messi') THEN 0
    WHEN canonical_name ILIKE 'messi' || '%' THEN 1
    WHEN canonical_name ILIKE '% ' || 'messi' || '%' THEN 2
    ELSE 3
  END,
  canonical_name
LIMIT 10;
```

The full query file also includes INNER JOIN and LEFT JOIN examples, top scorer per tournament with a window function, player tournament history, goals per appearance with `NULLIF`, player comparison, and advanced-statistics coverage.
