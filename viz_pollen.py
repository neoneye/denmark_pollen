#!/usr/bin/env python3
"""Render pollen.jsonl as a small-multiples PNG chart.

Companion to pollen.py: cron runs pollen.py (fetch/append) first, then this
script to regenerate the chart from the accumulated history.

Run:           .venv/bin/python3 viz_pollen.py
Custom paths:  .venv/bin/python3 viz_pollen.py --data pollen.jsonl --out pollen.png
"""

import argparse
import json
import math
import os
import sys
import tempfile
from datetime import date, timedelta
from typing import Optional

from pollen import POLLEN_LEVEL_INTERVALS, POLLEN_NAMES

# key -> label shown on its panel
DISPLAY_NAMES: dict[str, str] = {
    "el": "El (alder)",
    "hassel": "Hassel (hazel)",
    "elm": "Elm",
    "birk": "Birk (birch)",
    "graes": "Græs (grass)",
    "bynke": "Bynke (mugwort)",
    "alternaria": "Alternaria (mould)",
    "cladosporium": "Cladosporium (mould)",
}

KEY_TO_ID: dict[str, str] = {key: pollen_id for pollen_id, key in POLLEN_NAMES.items()}


def load_rows(path: str) -> list[dict]:
    """Read JSONL rows sorted by measurement_date, deduped (last occurrence wins).

    Blank lines are ignored; malformed lines and rows without a
    measurement_date are skipped with a warning on stderr.
    """
    by_date: dict[str, dict] = {}
    with open(path, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                print(f"warning: {path}:{lineno}: skipping malformed line", file=sys.stderr)
                continue
            measurement_date = row.get("measurement_date") if isinstance(row, dict) else None
            if not isinstance(measurement_date, str):
                print(f"warning: {path}:{lineno}: skipping row without measurement_date", file=sys.stderr)
                continue
            by_date[measurement_date] = row
    return [by_date[key] for key in sorted(by_date)]


def level_of(row: dict, key: str) -> Optional[int]:
    """The measured level for one pollen type in one row, or None for no data."""
    entry = row.get("pollen", {}).get(key)
    if not isinstance(entry, dict):
        return None
    level = entry.get("level")
    if isinstance(level, int) and not isinstance(level, bool) and level >= 0:
        return level
    return None


def active_types(rows: list[dict]) -> list[str]:
    """Pollen keys with at least one real measurement, in POLLEN_NAMES order."""
    return [
        key
        for key in POLLEN_NAMES.values()
        if any(level_of(row, key) is not None for row in rows)
    ]


def series_for(rows: list[dict], key: str) -> tuple[list[date], list[float]]:
    """(days, levels) on a continuous daily axis from first to last measurement.

    Days without a measurement get NaN so the plotted line breaks instead of
    interpolating across the gap.
    """
    by_day: dict[date, float] = {}
    for row in rows:
        day = date.fromisoformat(row["measurement_date"])
        level = level_of(row, key)
        by_day[day] = float(level) if level is not None else math.nan
    first, last = min(by_day), max(by_day)
    days = [first + timedelta(days=offset) for offset in range((last - first).days + 1)]
    return days, [by_day.get(day, math.nan) for day in days]
