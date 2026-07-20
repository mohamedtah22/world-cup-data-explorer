@echo off
cd /d "%~dp0"

docker compose up -d

cd backend

if not exist venv (
  python -m venv venv
)

call venv\Scripts\activate
python -c "import flask, psycopg2" >nul 2>nul
if errorlevel 1 (
  pip install -r requirements.txt
)

set DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/worldcup
set PORT=3001

python app.py
