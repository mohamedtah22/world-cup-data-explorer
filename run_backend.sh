#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required. Install Python 3 in WSL first."
  exit 1
fi

docker compose up -d

cd backend

if [ ! -d venv ]; then
  python3 -m venv venv
fi

source venv/bin/activate

if ! python3 -c "import flask, psycopg2" >/dev/null 2>&1; then
  pip install -r requirements.txt
fi

export DATABASE_URL="${DATABASE_URL:-postgresql://postgres:postgres@127.0.0.1:5432/worldcup}"
export PORT="${PORT:-3001}"

if python3 - "$PORT" <<'PY'
import socket
import sys

port = int(sys.argv[1])
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.settimeout(1)
    sys.exit(0 if sock.connect_ex(("127.0.0.1", port)) == 0 else 1)
PY
then
  echo "Port ${PORT} is already in use."
  echo "If the backend is already running, open: http://localhost:${PORT}/health"
  echo "Otherwise stop the old process with Ctrl+C, or run on another port:"
  echo "  PORT=3002 ./run_backend.sh"
  exit 0
fi

python3 app.py
