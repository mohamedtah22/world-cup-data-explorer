import json
import argparse
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FJELSTUL_DIR = ROOT / "data" / "raw" / "fjelstul"
STATSBOMB_DIR = ROOT / "data" / "raw" / "statsbomb"
ESPN_2026_DIR = ROOT / "data" / "raw" / "espn_2026"
METADATA_FILE = ROOT / "data" / "raw" / "source_metadata.json"

FJELSTUL_DATASETS = [
    "players",
    "squads",
    "player_appearances",
    "goals",
    "penalty_kicks",
    "bookings",
    "substitutions",
    "awards",
    "award_winners",
    "matches",
]

FJELSTUL_BASE = "https://raw.githubusercontent.com/jfjelstul/worldcup/master/data-csv"
STATSBOMB_BASE = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"
ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard?limit=200&dates=20260611-20260719"
ESPN_SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/summary?event={event_id}"
USER_AGENT = "world-cup-data-explorer/1.0 (+https://site.api.espn.com public JSON cache)"


def request_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def download(url, target, refresh=True):
    if target.exists() and not refresh:
        return target.stat().st_size
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        target.write_bytes(response.read())
    return target.stat().st_size


def read_json_url(url):
    return request_json(url)


def detect_statsbomb_world_cups():
    competitions = read_json_url(f"{STATSBOMB_BASE}/competitions.json")
    detected = [
        row
        for row in competitions
        if row.get("competition_name") == "FIFA World Cup"
        and row.get("competition_gender") == "male"
        and not row.get("competition_youth")
    ]
    return sorted(detected, key=lambda row: int(row["season_name"]))


def download_with_retries(url, target, refresh, attempts=3):
    if target.exists() and not refresh:
        return json.loads(target.read_text(encoding="utf-8")), False
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            data = request_json(url)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            return data, True
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(2 * attempt)
    raise last_error


def download_statsbomb_coverage(metadata, refresh):
    competitions_path = STATSBOMB_DIR / "competitions.json"
    download(f"{STATSBOMB_BASE}/competitions.json", competitions_path, refresh=refresh)
    detected = detect_statsbomb_world_cups()
    coverage = []

    for row in detected:
        competition_id = row["competition_id"]
        season_id = row["season_id"]
        year = int(row["season_name"])
        season_dir = STATSBOMB_DIR / str(competition_id) / str(season_id)
        matches_path = season_dir / "matches.json"
        try:
            download(f"{STATSBOMB_BASE}/matches/{competition_id}/{season_id}.json", matches_path, refresh=refresh)
            matches = json.loads(matches_path.read_text(encoding="utf-8"))
        except urllib.error.HTTPError as exc:
            metadata["issues"].append(
                {
                    "source_id": "statsbomb",
                    "issue_type": "statsbomb_matches_unavailable",
                    "description": f"Matches unavailable for competition {competition_id}, season {season_id}: HTTP {exc.code}",
                }
            )
            continue

        downloaded_matches = 0
        for match in matches:
            match_id = match["match_id"]
            for folder in ("lineups", "events"):
                target = season_dir / folder / f"{match_id}.json"
                try:
                    download(f"{STATSBOMB_BASE}/{folder}/{match_id}.json", target, refresh=refresh)
                except urllib.error.HTTPError as exc:
                    metadata["issues"].append(
                        {
                            "source_id": "statsbomb",
                            "issue_type": f"statsbomb_{folder}_unavailable",
                            "external_id": str(match_id),
                            "description": f"{folder} unavailable for StatsBomb match {match_id}: HTTP {exc.code}",
                        }
                    )
            downloaded_matches += 1

        coverage.append(
            {
                "source_id": "statsbomb",
                "source_name": "StatsBomb Open Data",
                "dataset_name": "matches_lineups_events",
                "coverage_year": year,
                "competition_id": competition_id,
                "season_id": season_id,
                "match_count": downloaded_matches,
                "file_path": str(season_dir.relative_to(ROOT)),
                "notes": "Detected from competitions.json; only available FIFA World Cup seasons were downloaded.",
            }
        )

    metadata["statsbomb_coverage"] = coverage


def download_espn_2026(metadata, refresh):
    scoreboard_path = ESPN_2026_DIR / "scoreboard_20260611_20260719.json"
    scoreboard, refreshed = download_with_retries(ESPN_SCOREBOARD_URL, scoreboard_path, refresh)
    completed_events = []
    for event in scoreboard.get("events", []):
        competitions = event.get("competitions") or []
        if not competitions:
            continue
        status = (competitions[0].get("status") or {}).get("type") or {}
        if status.get("completed"):
            completed_events.append(event)

    summaries = []
    for event in completed_events:
        event_id = str(event["id"])
        target = ESPN_2026_DIR / "summaries" / f"{event_id}.json"
        try:
            summary, _ = download_with_retries(ESPN_SUMMARY_URL.format(event_id=event_id), target, refresh)
            summaries.append((event_id, summary))
        except (urllib.error.URLError, TimeoutError) as exc:
            metadata["issues"].append(
                {
                    "source_id": "espn_2026",
                    "issue_type": "espn_summary_unavailable",
                    "external_id": event_id,
                    "description": f"ESPN summary unavailable for event {event_id}: {exc}",
                }
            )

    roster_matches = sum(1 for _, summary in summaries if summary.get("rosters"))
    metadata["espn_2026_coverage"] = [
        {
            "source_id": "espn_2026",
            "source_name": "ESPN public soccer JSON",
            "dataset_name": "scoreboard_summaries",
            "coverage_year": 2026,
            "match_count": len(summaries),
            "file_path": str(ESPN_2026_DIR.relative_to(ROOT)),
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "endpoint": ESPN_SCOREBOARD_URL,
            "notes": (
                "Unofficial public JSON cached locally; schemas may change. "
                f"Completed events: {len(completed_events)}; summaries with rosters: {roster_matches}; "
                f"scoreboard {'refreshed' if refreshed else 'read from cache'}."
            ),
        }
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="Redownload cached public source files")
    parser.add_argument(
        "--espn-only",
        action="store_true",
        help="Refresh only the lightweight ESPN 2026 scoreboard and summaries",
    )
    args = parser.parse_args()

    if args.espn_only and METADATA_FILE.exists():
        metadata = json.loads(METADATA_FILE.read_text(encoding="utf-8"))
        metadata["generated_at"] = datetime.now(timezone.utc).isoformat()
        metadata["issues"] = [
            issue for issue in metadata.get("issues", []) if issue.get("source_id") != "espn_2026"
        ]
    else:
        metadata = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "fjelstul_datasets": [],
            "statsbomb_coverage": [],
            "espn_2026_coverage": [],
            "issues": [],
        }

    if not args.espn_only:
        for dataset in FJELSTUL_DATASETS:
            target = FJELSTUL_DIR / f"{dataset}.csv"
            size = download(f"{FJELSTUL_BASE}/{dataset}.csv", target, refresh=args.refresh)
            metadata["fjelstul_datasets"].append(
                {
                    "source_id": "fjelstul",
                    "source_name": "Fjelstul World Cup Database",
                    "dataset_name": dataset,
                    "file_path": str(target.relative_to(ROOT)),
                    "bytes": size,
                }
            )

        download_statsbomb_coverage(metadata, refresh=args.refresh)
    download_espn_2026(metadata, refresh=args.refresh)
    METADATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    METADATA_FILE.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    if not args.espn_only:
        print(f"Downloaded {len(metadata['fjelstul_datasets'])} Fjelstul datasets")
        print(f"Detected {len(metadata['statsbomb_coverage'])} StatsBomb World Cup seasons")
    print(f"Cached {len(metadata['espn_2026_coverage'])} ESPN 2026 source groups")


if __name__ == "__main__":
    main()
