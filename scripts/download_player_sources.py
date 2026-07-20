import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FJELSTUL_DIR = ROOT / "data" / "raw" / "fjelstul"
STATSBOMB_DIR = ROOT / "data" / "raw" / "statsbomb"
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


def download(url, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=60) as response:
        target.write_bytes(response.read())
    return target.stat().st_size


def read_json_url(url):
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.load(response)


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


def download_statsbomb_coverage(metadata):
    competitions_path = STATSBOMB_DIR / "competitions.json"
    download(f"{STATSBOMB_BASE}/competitions.json", competitions_path)
    detected = detect_statsbomb_world_cups()
    coverage = []

    for row in detected:
        competition_id = row["competition_id"]
        season_id = row["season_id"]
        year = int(row["season_name"])
        season_dir = STATSBOMB_DIR / str(competition_id) / str(season_id)
        matches_path = season_dir / "matches.json"
        try:
            download(f"{STATSBOMB_BASE}/matches/{competition_id}/{season_id}.json", matches_path)
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
                    download(f"{STATSBOMB_BASE}/{folder}/{match_id}.json", target)
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


def main():
    metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fjelstul_datasets": [],
        "statsbomb_coverage": [],
        "issues": [],
    }

    for dataset in FJELSTUL_DATASETS:
        target = FJELSTUL_DIR / f"{dataset}.csv"
        size = download(f"{FJELSTUL_BASE}/{dataset}.csv", target)
        metadata["fjelstul_datasets"].append(
            {
                "source_id": "fjelstul",
                "source_name": "Fjelstul World Cup Database",
                "dataset_name": dataset,
                "file_path": str(target.relative_to(ROOT)),
                "bytes": size,
            }
        )

    download_statsbomb_coverage(metadata)
    METADATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    METADATA_FILE.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Downloaded {len(metadata['fjelstul_datasets'])} Fjelstul datasets")
    print(f"Detected {len(metadata['statsbomb_coverage'])} StatsBomb World Cup seasons")


if __name__ == "__main__":
    main()
