# Pollen Visualization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `viz_pollen.py`, a cron-friendly script that renders `pollen.jsonl` as a small-multiples PNG chart (`pollen.png`), one panel per in-season pollen type with low/moderate/high threshold bands.

**Architecture:** A single new script with a pure data layer (load/dedupe/select/series) that needs only the stdlib, and a rendering layer that imports matplotlib lazily and writes the PNG atomically. Thresholds and pollen names are imported from the existing `pollen.py` — never duplicated.

**Tech Stack:** Python 3.14, stdlib, matplotlib (only dependency, installed in a repo-local `.venv`).

Spec: `docs/superpowers/specs/2026-07-07-pollen-visualization-design.md`

## Global Constraints

- Only external dependency: `matplotlib` (in `requirements.txt`), installed into `.venv/` at the repo root.
- `matplotlib` is imported **inside** `render_chart()` only, so the data-layer tests run on a bare system Python.
- Thresholds come from `pollen.POLLEN_LEVEL_INTERVALS` and names from `pollen.POLLEN_NAMES` — do not copy the tables.
- Tests use the repo's existing bare test-function style with the `__main__` runner from `test_pollen.py` — no pytest, no unittest classes.
- A level of `-1` or `null` means "no data": never plot it, never count it as a measurement.
- Output must be written atomically (temp file in the destination dir + `os.replace`).
- Chart colors are exactly the hex constants defined in Task 2 (validated light-mode palette); text never wears the series color.
- Exit codes: 0 = success, 1 = unreadable/empty/unplottable data, message on stderr.

---

### Task 1: Scaffolding + data layer

**Files:**
- Create: `.gitignore`
- Create: `requirements.txt`
- Create: `viz_pollen.py` (data layer only)
- Create: `test_viz_pollen.py`

**Interfaces:**
- Consumes: `pollen.POLLEN_NAMES: dict[str, str]` (id → key, insertion-ordered).
- Produces (used by Tasks 2–3):
  - `load_rows(path: str) -> list[dict]` — rows sorted by `measurement_date`, deduped last-wins; raises `OSError` if unreadable.
  - `level_of(row: dict, key: str) -> Optional[int]` — level ≥ 0 or `None`.
  - `active_types(rows: list[dict]) -> list[str]` — keys with ≥ 1 real measurement, in `POLLEN_NAMES` order.
  - `series_for(rows: list[dict], key: str) -> tuple[list[date], list[float]]` — continuous daily axis, `math.nan` for missing days.

- [ ] **Step 1: Create the venv and project files**

```bash
cd /Users/neoneye/git/denmark_pollen
python3 -m venv .venv
.venv/bin/pip install matplotlib
```

Create `.gitignore`:

```gitignore
.venv/
__pycache__/
```

Create `requirements.txt`:

```
matplotlib
```

- [ ] **Step 2: Write the failing data-layer tests**

Create `test_viz_pollen.py`:

```python
#!/usr/bin/env python3
"""Offline tests for viz_pollen.py — no network. Run: python3 test_viz_pollen.py"""

import json
import math
import os
import tempfile
from datetime import date

import viz_pollen


def _row(measurement_date, levels):
    """Minimal pollen.jsonl row: levels is {key: level}."""
    pollen_map = {
        key: {"id": 0, "level": level, "in_season": level is not None and level >= 0, "category": None}
        for key, level in levels.items()
    }
    return {"measurement_date": measurement_date, "station_name": "København", "pollen": pollen_map}


def _write_jsonl(directory, rows_or_lines):
    path = os.path.join(directory, "pollen.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for item in rows_or_lines:
            f.write((item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)) + "\n")
    return path


def test_load_rows_skips_blank_and_malformed_lines():
    with tempfile.TemporaryDirectory() as d:
        path = _write_jsonl(d, [
            _row("2026-06-22", {"graes": 82}),
            "",
            "{not json",
            json.dumps({"no_measurement_date": True}),
            _row("2026-06-24", {"graes": 86}),
        ])
        rows = viz_pollen.load_rows(path)
        assert [r["measurement_date"] for r in rows] == ["2026-06-22", "2026-06-24"]


def test_load_rows_dedupes_and_sorts():
    with tempfile.TemporaryDirectory() as d:
        path = _write_jsonl(d, [
            _row("2026-06-24", {"graes": 1}),
            _row("2026-06-22", {"graes": 82}),
            _row("2026-06-24", {"graes": 86}),  # same date again: last wins
        ])
        rows = viz_pollen.load_rows(path)
        assert [r["measurement_date"] for r in rows] == ["2026-06-22", "2026-06-24"]
        assert viz_pollen.level_of(rows[1], "graes") == 86


def test_level_of_treats_negative_null_and_missing_as_no_data():
    row = _row("2026-06-22", {"graes": 82, "birk": -1, "el": None})
    assert viz_pollen.level_of(row, "graes") == 82
    assert viz_pollen.level_of(row, "birk") is None
    assert viz_pollen.level_of(row, "el") is None
    assert viz_pollen.level_of(row, "bynke") is None  # absent key
    assert viz_pollen.level_of({}, "graes") is None   # no pollen map at all


def test_active_types_orders_by_pollen_names():
    rows = [
        _row("2026-06-22", {"graes": 82, "birk": -1, "cladosporium": 1967}),
        _row("2026-06-24", {"graes": 86, "alternaria": 8}),
    ]
    assert viz_pollen.active_types(rows) == ["graes", "alternaria", "cladosporium"]
    assert viz_pollen.active_types([]) == []


def test_series_for_breaks_line_across_missing_days():
    rows = [
        _row("2026-06-22", {"graes": 82}),
        _row("2026-06-25", {"graes": 60}),  # 23rd and 24th missing
    ]
    days, levels = viz_pollen.series_for(rows, "graes")
    assert days == [date(2026, 6, 22), date(2026, 6, 23), date(2026, 6, 24), date(2026, 6, 25)]
    assert levels[0] == 82.0
    assert math.isnan(levels[1]) and math.isnan(levels[2])
    assert levels[3] == 60.0


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except Exception as exc:
                failures += 1
                print(f"FAIL {name}: {exc!r}")
    raise SystemExit(1 if failures else 0)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python3 test_viz_pollen.py`
Expected: crashes with `ModuleNotFoundError: No module named 'viz_pollen'`

- [ ] **Step 4: Implement the data layer**

Create `viz_pollen.py`:

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 test_viz_pollen.py`
Expected: `PASS` × 5, exit 0. Also run `python3 test_pollen.py` — still all `PASS`.

- [ ] **Step 6: Commit**

```bash
git add .gitignore requirements.txt viz_pollen.py test_viz_pollen.py
git commit -m "feat: add viz_pollen.py data layer (load/dedupe/select/series)"
```

---

### Task 2: Chart rendering with atomic PNG output

**Files:**
- Modify: `viz_pollen.py` (append rendering layer)
- Modify: `test_viz_pollen.py` (append smoke test)

**Interfaces:**
- Consumes: `load_rows`, `active_types`, `series_for`, `level_of`, `KEY_TO_ID`, `DISPLAY_NAMES` from Task 1; `pollen.POLLEN_LEVEL_INTERVALS` (`{id: [_, low_max, moderate_max, _]}`).
- Produces (used by Task 3): `render_chart(rows: list[dict], out_path: str) -> None` — renders and atomically writes the PNG; requires `rows` non-empty with ≥ 1 active type (caller validates).

- [ ] **Step 1: Write the failing smoke test**

Append to `test_viz_pollen.py` (above the `__main__` block):

```python
def test_render_chart_writes_png():
    try:
        import matplotlib  # noqa: F401
    except ModuleNotFoundError:
        print("SKIP test_render_chart_writes_png (matplotlib not installed)")
        return
    rows = viz_pollen.load_rows("pollen.jsonl")  # the repo's real data
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "pollen.png")
        viz_pollen.render_chart(rows, out)
        assert os.path.exists(out)
        with open(out, "rb") as f:
            header = f.read(8)
        assert header == b"\x89PNG\r\n\x1a\n", "not a PNG file"
        assert os.path.getsize(out) > 10_000  # a real multi-panel chart, not a stub
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python3 test_viz_pollen.py`
Expected: `FAIL test_render_chart_writes_png: AttributeError(...)` (no `render_chart` yet); the 5 data-layer tests still `PASS`.

- [ ] **Step 3: Implement the rendering layer**

Append to `viz_pollen.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python3 test_viz_pollen.py`
Expected: `PASS` × 6, exit 0.

- [ ] **Step 5: Render the real data and inspect the image**

```bash
.venv/bin/python3 -c "import viz_pollen; viz_pollen.render_chart(viz_pollen.load_rows('pollen.jsonl'), 'pollen.png')"
```

Open/read `pollen.png` and check: three panels (græs, alternaria, cladosporium); line breaks at the missing days (2026-06-23, 06-25, 07-04/05); band labels don't collide with data or each other; no clipped text; endpoint value label visible. Fix layout issues before committing.

- [ ] **Step 6: Commit**

```bash
git add viz_pollen.py test_viz_pollen.py pollen.png
git commit -m "feat: render small-multiples pollen chart with threshold bands"
```

---

### Task 3: CLI entry point, cron docs, README

**Files:**
- Modify: `viz_pollen.py` (append `main()`)
- Modify: `test_viz_pollen.py` (append exit-code tests)
- Modify: `README.md`

**Interfaces:**
- Consumes: `load_rows`, `active_types`, `render_chart` from Tasks 1–2.
- Produces: `main(argv: Optional[list[str]] = None) -> int` with `--data` / `--out` flags; script exits via `sys.exit(main())`.

- [ ] **Step 1: Write the failing exit-code tests**

Append to `test_viz_pollen.py` (above the `__main__` block):

```python
def test_main_errors_on_missing_file():
    with tempfile.TemporaryDirectory() as d:
        missing = os.path.join(d, "nope.jsonl")
        assert viz_pollen.main(["--data", missing, "--out", os.path.join(d, "out.png")]) == 1


def test_main_errors_on_empty_and_unplottable_data():
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "out.png")
        empty = _write_jsonl(d, [])
        assert viz_pollen.main(["--data", empty, "--out", out]) == 1
        no_data = _write_jsonl(d, [_row("2026-06-22", {"graes": -1})])  # rows, but nothing plottable
        assert viz_pollen.main(["--data", no_data, "--out", out]) == 1
        assert not os.path.exists(out)


def test_main_renders_png_on_success():
    try:
        import matplotlib  # noqa: F401
    except ModuleNotFoundError:
        print("SKIP test_main_renders_png_on_success (matplotlib not installed)")
        return
    with tempfile.TemporaryDirectory() as d:
        path = _write_jsonl(d, [_row("2026-06-22", {"graes": 82}), _row("2026-06-24", {"graes": 86})])
        out = os.path.join(d, "out.png")
        assert viz_pollen.main(["--data", path, "--out", out]) == 0
        assert os.path.getsize(out) > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python3 test_viz_pollen.py`
Expected: the three new tests `FAIL` with `AttributeError` (no `main` yet); earlier tests still `PASS`.

- [ ] **Step 3: Implement main()**

Append to `viz_pollen.py`:

```python
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

    render_chart(rows, args.out)
    print(f"wrote {args.out}: {len(rows)} days, {len(keys)} pollen types")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python3 test_viz_pollen.py`
Expected: `PASS` × 9, exit 0. Also `.venv/bin/python3 test_pollen.py` — all `PASS`.

- [ ] **Step 5: End-to-end check of the cron pair**

```bash
cd /Users/neoneye/git/denmark_pollen
python3 pollen.py           # likely "already up to date" — that's fine
.venv/bin/python3 viz_pollen.py
```

Expected: `wrote pollen.png: N days, 3 pollen types`, exit 0, `pollen.png` regenerated.

- [ ] **Step 6: Update README**

Replace `README.md` content with:

````markdown
# denmark_pollen

Daily Copenhagen pollen counts from [astma-allergi.dk](https://www.astma-allergi.dk),
logged to `pollen.jsonl` and charted to `pollen.png`.

![Pollen chart](pollen.png)

## Scripts

- `pollen.py` — fetches today's counts and appends one JSONL row per measurement
  day (stdlib only).
- `viz_pollen.py` — renders `pollen.jsonl` as a small-multiples PNG, one panel per
  in-season pollen type, with the site's low/moderate/high thresholds as background
  bands. Needs matplotlib.

## Setup

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Daily cron

```cron
30 13 * * * cd /Users/neoneye/git/denmark_pollen && python3 pollen.py && .venv/bin/python3 viz_pollen.py
```

## Tests

```sh
python3 test_pollen.py
.venv/bin/python3 test_viz_pollen.py
```
````

- [ ] **Step 7: Commit**

```bash
git add viz_pollen.py test_viz_pollen.py README.md pollen.png
git commit -m "feat: add viz_pollen.py CLI and document the daily cron pair"
```
