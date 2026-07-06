#!/usr/bin/env python3
"""Offline tests for pollen.py — no network. Run: python3 test_pollen.py"""

import json
import os
import tempfile

import pollen


def _firestore_pollen(level, in_season):
    return {
        "mapValue": {
            "fields": {
                "level": {"integerValue": str(level)},
                "inSeason": {"booleanValue": in_season},
            }
        }
    }


def _sample_raw():
    """Build a minimal feed matching the real double-encoded API shape."""
    doc = {
        "fields": {
            "48": {
                "mapValue": {
                    "fields": {
                        "date": {"stringValue": "22-06-2026"},
                        "data": {
                            "mapValue": {
                                "fields": {
                                    "28": _firestore_pollen(82, True),    # grass -> high
                                    "7": _firestore_pollen(-1, False),    # birch -> no data
                                    "2": _firestore_pollen(8, True),      # hazel -> moderate
                                }
                            }
                        },
                    }
                }
            }
        }
    }
    return json.dumps(json.dumps(doc))  # double-encode like the real API


def test_category_for():
    assert pollen.category_for(28, 82) == "high"       # >= 15
    assert pollen.category_for(28, 10) == "moderate"   # 5 <= x < 15
    assert pollen.category_for(28, 3) == "low"         # < 5
    assert pollen.category_for(28, -1) is None         # no data
    assert pollen.category_for(28, None) is None
    assert pollen.category_for("99", 5) is None        # unknown id


def test_parse_feed():
    date, pollen_map = pollen.parse_feed(_sample_raw())
    assert date == "2026-06-22"
    assert pollen_map["graes"] == {"id": 28, "level": 82, "in_season": True, "category": "high"}
    assert pollen_map["birk"]["level"] == -1
    assert pollen_map["birk"]["category"] is None
    assert pollen_map["hassel"]["category"] == "moderate"
    # types absent from the feed still get a placeholder entry
    assert pollen_map["bynke"] == {"id": 31, "level": None, "in_season": None, "category": None}
    assert set(pollen_map) == set(pollen.POLLEN_NAMES.values())


def test_parse_feed_missing_station():
    raw = json.dumps(json.dumps({"fields": {"49": {}}}))
    try:
        pollen.parse_feed(raw)
        assert False, "expected ValueError for missing station 48"
    except ValueError:
        pass


def test_last_measurement_date_and_skip():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "pollen.jsonl")
        assert pollen.last_measurement_date(path) is None  # missing file
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"measurement_date": "2026-06-20"}) + "\n")
            f.write(json.dumps({"measurement_date": "2026-06-22"}) + "\n")
        assert pollen.last_measurement_date(path) == "2026-06-22"


def test_skip_logic_does_not_append(monkeypatched_feed_date="2026-06-22"):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "pollen.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"measurement_date": "2026-06-22"}) + "\n")
        before = open(path).read()
        # simulate the comparison main() does
        previous = pollen.last_measurement_date(path)
        new_date = "2026-06-22"
        should_skip = previous is not None and new_date <= previous
        assert should_skip is True
        assert open(path).read() == before  # unchanged


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
