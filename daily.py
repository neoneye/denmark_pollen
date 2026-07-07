#!/usr/bin/env python3
"""Daily cron entry point: fetch pollen data, and when a new measurement
arrived, re-render the chart, commit, and push to GitHub.

Cron: 30 13 * * * python3 /Users/neoneye/git/denmark_pollen/daily.py
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from typing import Optional

from fetch_pollen import fetch_feed, last_measurement_date, parse_feed

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = "pollen.jsonl"
CHART_FILE = "pollen.webp"
VENV_PYTHON = os.path.join(REPO_DIR, ".venv", "bin", "python3")


def say(message: str) -> None:
    print(f"daily: {message}", flush=True)


def run(argv: list[str]) -> int:
    """Run a child command from the repo dir, streaming its output."""
    say("run: " + " ".join(argv))
    try:
        return subprocess.run(argv, cwd=REPO_DIR).returncode
    except FileNotFoundError:
        say(
            f"error: {argv[0]} not found"
            " (missing venv? create it: python3 -m venv .venv"
            " && .venv/bin/pip install -r requirements.txt)"
        )
        return 127


def has_changes(porcelain: str) -> bool:
    """True if `git status --porcelain` output reports any change."""
    return bool(porcelain.strip())


def commit_message(measurement_date: Optional[str]) -> str:
    return f"data: {measurement_date or 'new'} measurement"


def _porcelain() -> str:
    return subprocess.run(
        ["git", "status", "--porcelain", "--", DATA_FILE],
        cwd=REPO_DIR, capture_output=True, text=True, check=True,
    ).stdout


MAX_AGE_HOURS = 30.0  # 24h cadence + a few hours of grace


def _venv_exists() -> bool:
    return os.path.exists(VENV_PYTHON)


def last_row(path: str) -> Optional[dict]:
    """The last JSON row of the data file, or None if unreadable/empty."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            last = None
            for line in f:
                if line.strip():
                    last = line.strip()
    except OSError:
        return None
    if last is None:
        return None
    try:
        row = json.loads(last)
    except json.JSONDecodeError:
        return None
    return row if isinstance(row, dict) else None


def staleness_hours(row: dict, now: datetime) -> Optional[float]:
    """Hours since the row's fetched_at, or None if it is missing/invalid."""
    try:
        fetched_at = datetime.fromisoformat(row["fetched_at"])
        return (now - fetched_at).total_seconds() / 3600.0
    except (KeyError, TypeError, ValueError):
        return None


def _feed_measurement_date() -> str:
    """The live feed's current measurement date (raises on fetch/parse trouble)."""
    measurement_date, _ = parse_feed(fetch_feed())
    return measurement_date


def health(now: datetime, max_age_hours: float) -> int:
    """Run all health checks, print one line per check, return 0/1."""
    healthy = True

    if _venv_exists():
        say("health: OK venv python present")
    else:
        healthy = False
        say(
            "health: FAIL venv python missing"
            " (create it: python3 -m venv .venv"
            " && .venv/bin/pip install -r requirements.txt)"
        )

    row = last_row(os.path.join(REPO_DIR, DATA_FILE))
    age = staleness_hours(row, now) if row is not None else None
    if row is None:
        healthy = False
        say(f"health: FAIL no readable rows in {DATA_FILE}")
    elif age is None:
        healthy = False
        say(f"health: FAIL last row of {DATA_FILE} has no valid fetched_at")
    elif age <= max_age_hours:
        say(f"health: OK data is fresh (fetched {age:.1f}h ago, threshold {max_age_hours:g}h)")
    else:
        say(f"health: data is stale (fetched {age:.1f}h ago, threshold {max_age_hours:g}h); probing the feed")

    if row is None or age is None or age > max_age_hours:
        try:
            feed_date = _feed_measurement_date()
        except Exception as exc:
            healthy = False
            say(f"health: FAIL astma-allergi.dk feed not responding or unparseable: {exc}")
        else:
            recorded = row.get("measurement_date") if row is not None else None
            if isinstance(recorded, str) and feed_date <= recorded:
                say(f"health: OK feed responds; source has not published beyond {recorded} — pipeline healthy")
            else:
                healthy = False
                say(f"health: FAIL feed has {feed_date} but last recorded is {recorded} — pipeline is not recording")

    say("health: all checks passed" if healthy else "health: PROBLEMS FOUND")
    return 0 if healthy else 1


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Daily pollen pipeline: fetch, chart, commit, push.")
    parser.add_argument("--health", action="store_true", help="run read-only health checks and exit 0/1")
    parser.add_argument("--max-age-hours", type=float, default=MAX_AGE_HOURS,
                        help=f"staleness threshold for --health (default: {MAX_AGE_HOURS:g})")
    args = parser.parse_args(argv)

    if args.health:
        return health(datetime.now().astimezone(), args.max_age_hours)

    if run([sys.executable, os.path.join(REPO_DIR, "fetch_pollen.py")]) != 0:
        say("fetch_pollen.py failed; aborting")
        return 1

    if not has_changes(_porcelain()):
        last = last_measurement_date(os.path.join(REPO_DIR, DATA_FILE))
        say(f"no new measurement (last recorded {last}); nothing to do")
        return 0

    if run([VENV_PYTHON, os.path.join(REPO_DIR, "viz_pollen.py")]) != 0:
        say("viz_pollen.py failed; aborting (data stays uncommitted, next run retries)")
        return 1

    message = commit_message(last_measurement_date(os.path.join(REPO_DIR, DATA_FILE)))
    publish_steps = [
        ["git", "add", "--", DATA_FILE, CHART_FILE],
        ["git", "commit", "-m", message, "--", DATA_FILE, CHART_FILE],
        ["git", "push", "origin", "main"],
    ]
    for argv in publish_steps:
        if run(argv) != 0:
            say(f"{argv[0]} {argv[1]} failed; aborting")
            return 1

    say(f"published: {message}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
