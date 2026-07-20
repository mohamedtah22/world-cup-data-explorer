import json
from dataclasses import asdict, is_dataclass
from datetime import date
from pathlib import Path

from load_database import clean_records

ROOT = Path(__file__).resolve().parents[1]
CLEAN_DIR = ROOT / "data" / "clean"


def default(value):
    if isinstance(value, date):
        return value.isoformat()
    if is_dataclass(value):
        return asdict(value)
    raise TypeError(f"Cannot serialize {type(value)!r}")


def main():
    records, summary = clean_records()
    CLEAN_DIR.mkdir(parents=True, exist_ok=True)
    (CLEAN_DIR / "matches.json").write_text(json.dumps(records, ensure_ascii=False, indent=2, default=default), encoding="utf-8")
    (CLEAN_DIR / "data_quality_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=default), encoding="utf-8")
    print(f"Normalized {len(records)} matches")


if __name__ == "__main__":
    main()
