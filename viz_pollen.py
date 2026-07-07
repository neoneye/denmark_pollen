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


# Light-mode chart palette (validated reference palette).
SURFACE = "#fcfcfb"
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRIDLINE = "#e1e0d9"
BASELINE = "#c3c2b7"
SERIES = "#2a78d6"
BAND_COLORS = {"low": "#0ca30c", "moderate": "#fab219", "high": "#d03b3b"}
BAND_ALPHA = 0.10


def _draw_bands(ax, intervals: list[int], y_max: float) -> None:
    """Low/moderate/high background washes, labeled when tall enough to fit text."""
    bounds = [
        (0.0, float(intervals[1]), "low"),
        (float(intervals[1]), float(intervals[2]), "moderate"),
        (float(intervals[2]), y_max, "high"),
    ]
    for band_low, band_high, name in bounds:
        band_high = min(band_high, y_max)
        if band_high <= band_low:
            continue
        ax.axhspan(band_low, band_high, facecolor=BAND_COLORS[name], alpha=BAND_ALPHA, linewidth=0, zorder=0)
        if (band_high - band_low) / y_max >= 0.12:
            ax.text(
                0.995, (band_low + band_high) / 2, name,
                transform=ax.get_yaxis_transform(),
                ha="right", va="center", fontsize=7, color=INK_SECONDARY, zorder=1,
            )


def _atomic_savefig(fig, out_path: str) -> None:
    """Write the figure to a temp file next to out_path, then rename into place."""
    out_dir = os.path.dirname(os.path.abspath(out_path))
    fd, tmp_path = tempfile.mkstemp(prefix=".pollen-", suffix=".png", dir=out_dir)
    try:
        with os.fdopen(fd, "wb") as handle:
            fig.savefig(handle, format="png", facecolor=fig.get_facecolor())
        os.replace(tmp_path, out_path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def render_chart(rows: list[dict], out_path: str) -> None:
    """Render one panel per active pollen type and atomically write the PNG.

    rows must be non-empty with at least one active type (main() validates).
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    keys = active_types(rows)
    fig, axes = plt.subplots(
        len(keys), 1, sharex=True, squeeze=False,
        figsize=(8, 1.9 * len(keys) + 1.1), dpi=150,
    )
    fig.patch.set_facecolor(SURFACE)

    for ax, key in zip(axes[:, 0], keys):
        days, levels = series_for(rows, key)
        measured = [(day, level) for day, level in zip(days, levels) if not math.isnan(level)]
        y_max = max(1.0, max(level for _, level in measured) * 1.15)

        ax.set_facecolor(SURFACE)
        ax.set_axisbelow(True)
        ax.grid(axis="y", color=GRIDLINE, linewidth=1)
        _draw_bands(ax, POLLEN_LEVEL_INTERVALS[KEY_TO_ID[key]], y_max)
        ax.plot(
            days, levels,
            color=SERIES, linewidth=2, solid_capstyle="round", solid_joinstyle="round",
            marker="o", markersize=6, markerfacecolor=SERIES,
            markeredgecolor=SURFACE, markeredgewidth=1.5, zorder=3,
        )
        last_day, last_level = measured[-1]
        ax.annotate(
            f"{last_level:g}", xy=(last_day, last_level), xytext=(0, 8),
            textcoords="offset points", ha="center", fontsize=8, color=INK_PRIMARY, zorder=4,
        )

        ax.set_title(DISPLAY_NAMES.get(key, key), loc="left", fontsize=10, color=INK_PRIMARY, pad=4)
        ax.set_ylim(0, y_max)
        ax.margins(x=0.02)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(BASELINE)
        ax.tick_params(colors=INK_MUTED, labelsize=8)
        ax.tick_params(axis="y", length=0)

    locator = mdates.AutoDateLocator()
    axes[-1, 0].xaxis.set_major_locator(locator)
    axes[-1, 0].xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))

    station = rows[-1].get("station_name", "")
    first_date = rows[0]["measurement_date"]
    last_date = rows[-1]["measurement_date"]
    fig.suptitle(
        f"Pollen — {station}", x=0.02, y=0.995, ha="left", va="top",
        fontsize=12, fontweight="bold", color=INK_PRIMARY,
    )
    fig.text(
        0.98, 0.995, f"{first_date} → {last_date}", ha="right", va="top",
        fontsize=9, color=INK_SECONDARY,
    )
    fig.text(
        0.02, 0.004, f"Source: astma-allergi.dk · generated {date.today().isoformat()}",
        ha="left", va="bottom", fontsize=7, color=INK_MUTED,
    )
    fig.tight_layout(rect=(0, 0.025, 1, 0.95))

    try:
        _atomic_savefig(fig, out_path)
    finally:
        plt.close(fig)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Render pollen.jsonl as a small-multiples PNG chart.")
    parser.add_argument("--data", default="pollen.jsonl", help="input JSONL path (default: ./pollen.jsonl)")
    parser.add_argument("--out", default="pollen.png", help="output PNG path (default: ./pollen.png)")
    args = parser.parse_args(argv)

    try:
        rows = load_rows(args.data)
    except OSError as exc:
        print(f"error: cannot read {args.data}: {exc}", file=sys.stderr)
        return 1
    if not rows:
        print(f"error: no rows in {args.data}", file=sys.stderr)
        return 1
    keys = active_types(rows)
    if not keys:
        print(f"error: no plottable measurements in {args.data}", file=sys.stderr)
        return 1

    try:
        render_chart(rows, args.out)
    except ModuleNotFoundError as exc:
        print(
            f"error: {exc.name} is not installed for {sys.executable}\n"
            f"run with the project venv:  .venv/bin/python3 {os.path.basename(sys.argv[0])}\n"
            f"or install dependencies:   .venv/bin/pip install -r requirements.txt",
            file=sys.stderr,
        )
        return 1
    print(f"wrote {args.out}: {len(rows)} days, {len(keys)} pollen types")
    return 0


if __name__ == "__main__":
    sys.exit(main())
