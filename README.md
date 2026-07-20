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

## Environment Files

`backend/.env.example`:

```text
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/worldcup
PORT=3001
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

`download_player_sources.py` downloads Fjelstul CSV datasets and StatsBomb `competitions.json`. It detects available men’s FIFA World Cup seasons, then downloads matches, lineups, and events only for those detected seasons. Coverage is written to `data/raw/source_metadata.json` and loaded into PostgreSQL by `load_player_data.py`.

Fjelstul is the authoritative source for historical player identities, squads, appearances, goals, bookings, substitutions, awards, and award winners. StatsBomb is used only as event-data enrichment for covered matches.

Latest verified load:

- Raw records: 1,069
- Cleaned records: 1,069
- Tournaments: 23
- Teams: 91
- Matches: 1,069
- Goals: 1,138
- Players after player load: 11,916
- Player appearances after player load: 19,362
- Player-match statistic rows after player load: 23,390
- StatsBomb player event rows after player load: 497,198
- Duplicates: 0
- Missing scores: 3
- Missing stadiums: 0
- Alias mappings: 2

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
