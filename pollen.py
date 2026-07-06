#!/usr/bin/env python3
"""Append the latest Copenhagen pollen counts to a JSONL file, once per day.

Data source: astma-allergi.dk's backend API (no scraping / JS needed).
The feed is a double-JSON-encoded Firestore-style document keyed by station id;
station "48" is Copenhagen / East Denmark.

Run once per day:  python3 pollen.py
Custom output:     python3 pollen.py --out /path/to/pollen.jsonl
"""

import argparse
import json
import sys
import urllib.request
from datetime import datetime
from typing import Any, Optional, TypedDict

FEED_URL = "https://www.astma-allergi.dk/umbraco/api/pollenapi/getpollenfeed"
STATION = "48"
STATION_NAME = "København"
USER_AGENT = "Mozilla/5.0 (pollen-logger; +https://github.com/neoneye)"


class PollenEntry(TypedDict):
    id: int
    level: Optional[int]
    in_season: Optional[bool]
    category: Optional[str]


class Row(TypedDict):
    fetched_at: str
    measurement_date: str
    station: str
    station_name: str
    pollen: dict[str, PollenEntry]


# id -> latin/danish key, mirrored from the site's pollen.js POLLEN_NAMES.
POLLEN_NAMES: dict[str, str] = {
    "1": "el",            # alder
    "2": "hassel",        # hazel
    "4": "elm",           # elm
    "7": "birk",          # birch
    "28": "graes",        # grass  <- primary allergy
    "31": "bynke",        # mugwort
    "44": "alternaria",   # mould
    "45": "cladosporium", # mould
}

# id -> [_, low_max, moderate_max, _] thresholds, from pollen.js POLLEN_LEVEL_INTERVALS.
POLLEN_LEVEL_INTERVALS: dict[str, list[int]] = {
    "1": [0, 10, 50, 200],
    "2": [0, 5, 15, 40],
    "4": [0, 10, 50, 80],
    "7": [0, 30, 100, 550],
    "28": [0, 5, 15, 40],
    "31": [0, 10, 50, 60],
    "44": [0, 20, 100, 500],
    "45": [0, 2000, 6000, 7000],
}


def category_for(pollen_id: str | int, level: Optional[int]) -> Optional[str]:
    """Map a grain count to low/moderate/high using the site's own thresholds.

    Returns None when there is no data (level < 0) or the id is unknown.
    """
    if level is None or level < 0:
        return None
    intervals = POLLEN_LEVEL_INTERVALS.get(str(pollen_id))
    if intervals is None:
        return None
    if level < intervals[1]:
        return "low"
    if level < intervals[2]:
        return "moderate"
    return "high"


def _firestore_value(field: dict[str, Any]) -> int | bool | str | None:
    """Unwrap a single Firestore-typed value (integerValue / booleanValue / ...)."""
    if "integerValue" in field:
        return int(field["integerValue"])
    if "booleanValue" in field:
        return field["booleanValue"]
    if "stringValue" in field:
        return field["stringValue"]
    return None


def parse_feed(raw_text: str, station: str = STATION) -> tuple[str, dict[str, PollenEntry]]:
    """Decode the raw API body into (measurement_date_iso, {pollen_key: {...}}).

    raw_text is the double-JSON-encoded response body. measurement_date_iso is
    in YYYY-MM-DD form. Raises ValueError if the station is missing.
    """
    doc = json.loads(json.loads(raw_text))  # body is a JSON string of a JSON doc
    stations = doc["fields"]
    if station not in stations:
        raise ValueError(f"station {station!r} not present in feed (have {list(stations)})")

    station_fields = stations[station]["mapValue"]["fields"]
    raw_date = str(_firestore_value(station_fields["date"]))  # "DD-MM-YYYY"
    measurement_date = datetime.strptime(raw_date, "%d-%m-%Y").date().isoformat()

    data = station_fields["data"]["mapValue"]["fields"]
    pollen: dict[str, PollenEntry] = {}
    for pollen_id, key in POLLEN_NAMES.items():
        entry = data.get(pollen_id)
        if entry is None:
            pollen[key] = {"id": int(pollen_id), "level": None, "in_season": None, "category": None}
            continue
        fields = entry["mapValue"]["fields"]
        raw_level = _firestore_value(fields.get("level", {}))
        level: Optional[int] = int(raw_level) if isinstance(raw_level, (int, bool)) else None
        raw_in_season = _firestore_value(fields.get("inSeason", {}))
        in_season: Optional[bool] = raw_in_season if isinstance(raw_in_season, bool) else None
        pollen[key] = {
            "id": int(pollen_id),
            "level": level,
            "in_season": in_season,
            "category": category_for(pollen_id, level),
        }
    return measurement_date, pollen


def build_row(
    measurement_date: str, pollen: dict[str, PollenEntry], fetched_at: str
) -> Row:
    return {
        "fetched_at": fetched_at,
        "measurement_date": measurement_date,
        "station": STATION,
        "station_name": STATION_NAME,
        "pollen": pollen,
    }


def last_measurement_date(path: str) -> Optional[str]:
    """Return the measurement_date of the last row in the JSONL file, or None."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            last = None
            for line in f:
                line = line.strip()
                if line:
                    last = line
    except FileNotFoundError:
        return None
    if last is None:
        return None
    try:
        return json.loads(last).get("measurement_date")
    except json.JSONDecodeError:
        return None


def fetch_feed(url: str = FEED_URL) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Append daily Copenhagen pollen counts to a JSONL file.")
    parser.add_argument("--out", default="pollen.jsonl", help="output JSONL path (default: ./pollen.jsonl)")
    parser.add_argument("--force", action="store_true", help="append even if the measurement date hasn't advanced")
    args = parser.parse_args(argv)

    try:
        raw = fetch_feed()
        measurement_date, pollen = parse_feed(raw)
    except Exception as exc:  # network, decode, or missing-station errors
        print(f"error: failed to fetch/parse pollen feed: {exc}", file=sys.stderr)
        return 1

    previous = last_measurement_date(args.out)
    if not args.force and previous is not None and measurement_date <= previous:
        print(f"already up to date (measurement_date {measurement_date}, last recorded {previous}); nothing appended")
        return 0

    fetched_at = datetime.now().astimezone().isoformat(timespec="seconds")
    row = build_row(measurement_date, pollen, fetched_at)
    with open(args.out, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")

    grass = pollen.get("graes", {})
    print(
        f"appended {measurement_date} to {args.out}: "
        f"grass={grass.get('level')} ({grass.get('category')})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
