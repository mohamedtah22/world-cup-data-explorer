# World Cup Data Explorer Report

## Application Overview

World Cup Data Explorer is a full-stack data-management application for FIFA World Cup match data. A Python ETL pipeline reads OpenFootball JSON files, cleans and normalizes the records, and loads them into PostgreSQL. A Python Flask API exposes SQL-backed endpoints for dashboard metrics, tournaments, teams, matches, player scoring, team comparison, and data quality. The frontend is a React JavaScript dashboard with a dark navy and gold sports style. The production frontend requests all final statistics from the Flask API at `http://localhost:3001/api`; it does not use static dashboard JSON as a data source.

The verified final database load contains 1,069 OpenFootball raw match records, 23 tournaments, 91 teams, 1,069 canonical matches, 11,916 players, 19,362 linked player appearances, 23,390 player-match statistic rows, and 497,198 StatsBomb event rows. The ETL detected 3 missing scores and preserves data-quality issues for player rows that cannot be safely linked without weak matching.

## Data Sources and Descriptions

The match source data is stored in `data/raw/openfootball`. Each JSON file represents one World Cup edition and contains match-level fields such as date, time, stage, group, teams, full-time score, venue, and nested goal arrays.

Historical player data comes from the Fjelstul World Cup Database CSV exports. Fjelstul is treated as the authoritative source for player identity, squads, appearances, goals, penalty kicks, bookings, substitutions, awards, and award winners. The loader uses the real CSV files under `data/raw/fjelstul`.

StatsBomb Open Data is treated only as an additional event-data source. The project first downloads `competitions.json`, detects available men’s FIFA World Cup seasons, and downloads matches, lineups, and events only for those seasons. The detected coverage is recorded in `data/raw/source_metadata.json` and `source_metadata`. The verified detected seasons are 1958, 1962, 1970, 1974, 1986, 1990, 2018, and 2022.

Important source fields:

- `name`: tournament name and year.
- `matches`: match records for the tournament.
- `team1` and `team2`: original team labels from the source.
- `score.ft`: full-time score.
- `goals1` and `goals2`: nested goal events.
- `ground`: stadium and city in one string for many records.

## Data-Management Challenges

The source files combine semi-structured JSON, CSV tables, and nested event data, so the main work is cleaning, matching, and relational modeling rather than display design. Team names are not always stable across history, so the ETL maps known aliases into canonical teams while preserving the original labels in `team_aliases`.

Venue data is also inconsistent. Some rows use `Stadium, City`, while some newer rows contain a single location string or a parenthesized city. The ETL separates venue name and city when possible and uses explicit unknown values only for missing raw venues. Goal minutes can be integers, strings such as `90+4`, or an integer with an `offset`; these are converted into `minute` and `stoppage_minute` integer columns.

Player identity is resolved conservatively. Fjelstul external player IDs are used as authoritative identifiers. StatsBomb players are matched through team, normalized lineup name, and existing aliases where possible. The loader never merges two players based only on weak partial-name matches; uncertain and unmatched rows are recorded in `data_quality_issues`.

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
- `player_events`: StatsBomb raw event provenance and event metadata.
- `goals`: goal events linked to matches, players, teams, and tournaments.

Primary keys are defined for every table. Foreign keys enforce relationships from matches to tournaments, teams, and stadiums, and from goals to matches, players, teams, and tournaments. Unique constraints protect tournament years, canonical team names, aliases, source match keys, source goal keys, and player/team pairs. Check constraints validate year ranges, non-empty names, scores, goal minutes, stoppage minutes, and different home and away teams. Indexes support common queries by date, tournament, stage, teams, stadiums, players, and goal aggregates.

Supporting tables, `source_metadata`, `data_quality_metrics`, `data_quality_sources`, and `data_quality_issues`, store source coverage and ETL audit results for the Data Quality page.

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

The full query file also includes top scorer per tournament with a window function, player tournament history, goals per appearance, players who represented multiple teams, player comparison, and advanced-statistics coverage.
