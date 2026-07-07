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
