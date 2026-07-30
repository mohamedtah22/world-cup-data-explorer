import argparse
import os
import subprocess
import sys
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "database" / "schema.sql"

sys.path.insert(0, str(ROOT / "scripts"))
from load_database import load_database  # noqa: E402
from load_player_data import load_player_data  # noqa: E402


TABLES_TO_CHECK = (
    "tournaments",
    "teams",
    "matches",
    "players",
    "goals",
    "player_appearances",
)


def require_database_url():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is required. Refusing to initialize an unknown database.")
    return database_url


def table_exists(cursor, table_name):
    cursor.execute("SELECT to_regclass(%s)", (f"public.{table_name}",))
    return cursor.fetchone()[0] is not None


def database_has_data(database_url):
    with psycopg2.connect(database_url) as connection:
        with connection.cursor() as cursor:
            for table_name in TABLES_TO_CHECK:
                if not table_exists(cursor, table_name):
                    continue
                cursor.execute(f"SELECT EXISTS (SELECT 1 FROM {table_name} LIMIT 1)")
                if cursor.fetchone()[0]:
                    return True
    return False


def apply_schema(database_url):
    with psycopg2.connect(database_url) as connection:
        connection.set_session(autocommit=True)
        with connection.cursor() as cursor:
            cursor.execute(SCHEMA.read_text(encoding="utf-8"))


def download_sources(refresh=False, espn_only=False):
    command = [sys.executable, str(ROOT / "scripts" / "download_player_sources.py")]
    if refresh:
        command.append("--refresh")
    if espn_only:
        command.append("--espn-only")
    subprocess.run(command, check=True)


def main():
    parser = argparse.ArgumentParser(description="Initialize or reset the World Cup PostgreSQL database for deployment.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--initial-load", action="store_true", help="Load data into an empty database.")
    mode.add_argument("--force-reset", action="store_true", help="Drop/recreate schema and reload data even if data exists.")
    mode.add_argument(
        "--update-2026",
        action="store_true",
        help="Refresh ESPN 2026 data and update the existing database without resetting historical data.",
    )
    args = parser.parse_args()

    database_url = require_database_url()
    has_data = database_has_data(database_url)
    if args.update_2026:
        if not has_data:
            raise SystemExit("Database is empty. Use --initial-load first.")
        download_sources(refresh=True, espn_only=True)
        load_player_data(database_url=database_url, resume=True, only_espn=True)
        print("2026 ESPN data refresh complete.")
        return

    if args.initial_load and has_data:
        raise SystemExit("Database is not empty. Use --force-reset only if you intentionally want to delete existing data.")

    if args.force_reset or not has_data:
        apply_schema(database_url)

    download_sources()
    load_database(database_url=database_url)
    load_player_data(database_url=database_url)
    print("Deployment database load complete.")


if __name__ == "__main__":
    main()
