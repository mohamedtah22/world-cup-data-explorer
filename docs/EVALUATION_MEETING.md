# Evaluation Meeting Guide

## 90-Second Introduction

World Cup Data Explorer is a full-stack data-management application for FIFA Men’s World Cup data through the completed 2026 tournament. The project starts from OpenFootball JSON files, keeps raw files unchanged, and uses Python ETL to normalize teams, split venues, parse scores and goal minutes, and prevent duplicate matches with deterministic keys. Fjelstul supplies authoritative historical player facts through 2022, ESPN public JSON supplies 2026 appearances and missing completed 2026 results, and StatsBomb supplies advanced events only for covered seasons. The verified full load contains 1,069 matches, 23 tournaments, 89 teams, 3,026 goals, 9,868 players, and 23,906 player appearances.

## Recommended Demonstration Order

1. Start on Overview and point out the four KPIs, goals-by-tournament chart, wins ranking, top scorers, and stadium usage.
2. Open Matches and filter by `2022`, `Argentina`, and `Final` to show server-side SQL filtering and pagination.
3. Open Teams, search for a team, sort columns, and select a team to show match history and appearances.
4. Open Tournaments, choose 2022, and show tournament teams, matches, and scorers.
5. Open Compare, search `Argentina` and `England` in the autocomplete fields, and explain that Flask computes both sides from SQL.
6. Open Player Compare, search `Messi` and `Kane`, and show that players outside the first 100 alphabetical rows are searchable.
7. Open Data Quality and explain aliases, missing values, source counts, ESPN 2026 coverage, partial StatsBomb coverage, and duplicate prevention.
7. Show `database/schema.sql` and `database/queries.sql`.

## Data-Management Challenge

The raw source files are JSON documents, not relational tables. They contain nested goals, composite venue strings, inconsistent historical team names, nullable future-match scores, and mixed minute formats such as integers, `90+4`, and integer plus offset fields. The ETL resolves these issues before loading PostgreSQL:

- Entity resolution maps `West Germany` to `Germany` and `United States` to `USA`.
- Additional controlled aliases map `Ivory Coast` to `Côte d'Ivoire`, `Bosnia-Herzegovina` to `Bosnia & Herzegovina`, `Czechia` to `Czech Republic`, and `Türkiye` to `Turkey`.
- `team_aliases` preserves the original source labels while pointing to canonical teams.
- ESPN dates are UTC; adjacent-date matches are linked only when the normalized teams also match, and those resolutions are recorded in data-quality issues.
- OpenFootball 2026 goals are preserved; non-Fjelstul goals are deleted only for canonical matches successfully replaced by Fjelstul.
- Stadium strings are split into `stadiums.name` and `stadiums.city`.
- Scores remain nullable when missing, but check constraints prevent negative scores.
- Goal minutes and stoppage time are stored as integers.
- A deterministic `source_match_key` prevents duplicate match inserts.

## Relational Schema

The schema centers on `matches`. Each match belongs to one `tournaments` row, references two `teams` rows, optionally references one `stadiums` row, and has many `goals`. Each goal references its match, scoring team, tournament, and player. Player identity uses Fjelstul/StatsBomb IDs plus `player_external_ids` for ESPN IDs and `player_aliases` for source names.

Important constraints:

- Primary keys on every entity table.
- Foreign keys from matches to tournaments, teams, and stadiums.
- Foreign keys from goals to matches, players, teams, and tournaments.
- Unique constraints on tournament year, team canonical name, team alias, source match key, source goal key, and player/team.
- Check constraints on years, non-empty names, score values, goal minutes, and different home/away teams.
- B-tree indexes on match dates, tournaments, stages, teams, stadiums, players, and goal aggregation keys.
- GIN trigram indexes on team/player names support substring autocomplete; the player search plan uses a bitmap heap scan, while team search uses a sequential scan because 89 rows are cheaper to scan.

## Important SQL Queries

- Dashboard counts use scalar subqueries over `tournaments`, `teams`, `matches`, and `goals`.
- Goals by tournament joins `tournaments`, `matches`, and `goals`, grouped by tournament.
- Team statistics use a CTE and `UNION ALL` to convert home and away rows into one appearance stream.
- Match search joins tournaments, home team, away team, and stadiums while applying parameterized filters.
- Top scorers join goals to players and teams and exclude own goals.
- Compare uses the same team-stat CTE plus a best-tournament-by-goals aggregate.
- Data Quality reads ETL metrics, source-level counts, and alias mappings.

## Likely Questions and Strong Answers

**Why PostgreSQL instead of JSON in React?**  
The dataset has relationships: tournaments contain matches, matches reference teams and stadiums, and goals reference players. PostgreSQL enforces those relationships and supports the required aggregation and filtering with SQL.

**How do you prevent duplicate matches?**  
The ETL builds `source_match_key` from tournament year, date, stage, group, and canonical home/away teams. PostgreSQL also enforces `UNIQUE (source_match_key)`.

**Why keep `team_aliases`?**  
It proves entity resolution. The canonical team table powers analysis, while aliases preserve source labels and make the cleaning decision auditable.

**How are missing values handled?**  
Scores are nullable because the data can include future or incomplete matches. Stadiums fall back to explicit unknown labels only when the raw venue is blank. The API reports missing-score and missing-stadium counts.

**What SQL functionality is demonstrated?**  
CTEs, joins, grouping, aggregate metrics, pagination, date and text filters, scalar subqueries, unique constraints, foreign keys, and indexed lookup paths.

**Why does Fjelstul end at 2022?**  
The current Fjelstul men’s CSV dataset covers completed men’s tournaments through 2022, so 2026 player appearances are loaded from cached ESPN public match summaries.

## Exact Demo Steps

1. Run `docker compose up -d`.
2. Run `python scripts/load_database.py`.
3. Run backend:
   ```bat
   cd backend
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   python app.py
   ```
4. Run frontend:
   ```bat
   cd frontend
   npm install
   npm run dev
   ```
5. Open `http://localhost:5173`.
6. Verify the API directly at `http://localhost:3001/api/dashboard`.
7. Show `database/schema.sql`, `scripts/load_database.py`, and `database/queries.sql`.
