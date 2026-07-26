# World Cup Data Explorer

World Cup Data Explorer is a data-management project that loads OpenFootball World Cup JSON files into PostgreSQL, exposes SQL-backed Flask endpoints, and displays the results in a React JavaScript dashboard.

## Stack

- Frontend: React with JavaScript and Vite
- Backend: Python Flask
- Database: PostgreSQL
- ETL: Python

## Project Structure

```text
backend/      Flask REST API and pytest suite
database/     PostgreSQL schema and representative SQL queries
data/         raw OpenFootball files and reproducible clean files
docs/         evaluation meeting notes
frontend/     React JavaScript dashboard
report/       final implementation report
scripts/      data cleaning and PostgreSQL loader
```

## Setup and Run

From the project root:

```bash
docker compose up -d
python scripts/load_database.py
python scripts/download_player_sources.py
python scripts/load_player_data.py
```

Use `python scripts/download_player_sources.py --refresh` when you intentionally want to redownload cached public source files, including ESPN 2026 summaries.

Start the Flask backend on Windows:

```bat
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Start the React frontend in another terminal:

```bat
cd frontend
npm install
npm run dev
```

The frontend runs at `http://localhost:5173`. The API runs at `http://localhost:3001`.

## Render Deployment

This repository includes a root-level `render.yaml` Blueprint for Render PostgreSQL, the Flask API, and the React static site. The API build command is `pip install -r backend/requirements.txt`, and the start command is:

```bash
gunicorn --chdir backend --bind 0.0.0.0:$PORT app:app
```

Set `FRONTEND_ORIGINS` on the API service and `VITE_API_URL` on the static site for the final Render URLs. Initialize the Render PostgreSQL database explicitly after deploy:

```bash
python scripts/deploy_database.py --initial-load
```

See `docs/DEPLOYMENT.md` for the full deployment steps.

## Environment Files

`backend/.env.example`:

```text
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/worldcup
PORT=3001
FRONTEND_ORIGINS=http://localhost:5173
```

`frontend/.env.example`:

```text
VITE_API_URL=http://localhost:3001/api
```

## ETL

Run:

```bash
python scripts/load_database.py
```

The match loader reads every JSON file in `data/raw/openfootball`, preserves the raw files, normalizes known aliases, splits stadium and city values, parses scores and goal minutes, upserts relational entities in dependency order, and writes data-quality metrics.

Player statistics are loaded in two steps:

```bash
python scripts/download_player_sources.py
python scripts/load_player_data.py
```

`download_player_sources.py` downloads Fjelstul CSV datasets, StatsBomb `competitions.json`, and ESPN public 2026 match JSON. It detects available men’s FIFA World Cup seasons in StatsBomb, downloads only those seasons, and caches ESPN scoreboard/summary responses under `data/raw/espn_2026/`. Coverage is written to `data/raw/source_metadata.json` and loaded into PostgreSQL by `load_player_data.py`.

Fjelstul is the authoritative source for historical men’s player identities, squads, appearances, goals, bookings, substitutions, awards, and award winners through 2022. OpenFootball remains the broad match source and supplies most 2026 goals. ESPN public JSON is an unofficial supplemental 2026 source for completed scores missing from OpenFootball, fallback goal events for those matches, rosters, appearances, starter/substitute flags, and supported player stats. StatsBomb is used only as advanced event-data enrichment for its covered seasons.

Latest verified load:

- Raw records: 1,069
- Cleaned records: 1,069
- Tournaments: 23
- Teams: 89
- Matches: 1,069
- Goals after player load: 3,026
- Players after player load: 9,868
- Player appearances after player load: 23,906
- Player-match statistic rows after player load: 27,934
- StatsBomb player event rows after player load: 497,198
- ESPN 2026 appearances: 3,288
- 2026 goals after full ETL: 306
- Duplicates: 0
- Missing scores: 3
- Missing stadiums: 0
- Alias mappings: 4

## Main API Endpoints

- `GET /health`
- `GET /api/dashboard`
- `GET /api/tournaments`
- `GET /api/tournaments/<year>`
- `GET /api/teams?search=&sort_by=&order=&page=&limit=`
- `GET /api/teams/<team_id>`
- `GET /api/matches?year=&team=&stage=&stadium=&date_from=&date_to=&page=&limit=`
- `GET /api/players/top-scorers?year=&limit=`
- `GET /api/players?search=&team=&tournament=&position=&sort_by=&order=&page=&limit=`
- `GET /api/players/<player_id>`
- `GET /api/players/leaderboards`
- `GET /api/players/<player_id>/matches?page=&limit=`
- `GET /api/players/compare?player1=<id>&player2=<id>`
- `GET /api/compare?team1=<id>&team2=<id>`
- `GET /api/search/teams?q=<text>&limit=10`
- `GET /api/search/players?q=<text>&limit=10`
- `GET /api/data-quality`

## Verification

Backend tests:

```bash
cd frontend
../backend/venv/bin/python -m pytest ../backend/tests -p no:cacheprovider
```

Frontend build:

```bash
cd frontend
npm run build
```

Optional real ETL idempotency test:

```bash
set TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/worldcup_test
cd frontend
../backend/venv/bin/python -m pytest ../backend/tests/test_etl.py -p no:cacheprovider
```

## Search Indexes

The schema enables `pg_trgm` and creates GIN trigram indexes on `teams.canonical_name` and `players.canonical_name` for substring autocomplete. In the verified database, `EXPLAIN ANALYZE` for player search `messi` used `idx_players_name_trgm` with a bitmap heap scan and completed in about 0.23 ms. Team search `arg` used a sequential scan over 89 rows in about 0.07 ms because PostgreSQL correctly judged that cheaper than using the index for such a small table.
