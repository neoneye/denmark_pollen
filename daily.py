#!/usr/bin/env python3
"""Daily cron entry point: fetch pollen data, and when a new measurement
arrived, re-render the chart, commit, and push to GitHub.

Cron: 30 13 * * * python3 /Users/neoneye/git/denmark_pollen/daily.py
"""

import os
import subprocess
import sys
from typing import Optional

from pollen import last_measurement_date

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


def main() -> int:
    if run([sys.executable, os.path.join(REPO_DIR, "pollen.py")]) != 0:
        say("pollen.py failed; aborting")
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
