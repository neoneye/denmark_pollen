#!/usr/bin/env python3
"""Offline tests for daily.py — no subprocesses, no git. Run: python3 test_daily.py"""

from datetime import datetime, timedelta, timezone

import daily


class _Recorder:
    """Stub for daily.run that records argvs and returns scripted exit codes."""

    def __init__(self, exit_codes=None):
        self.calls = []
        self.exit_codes = list(exit_codes or [])

    def __call__(self, argv):
        self.calls.append(argv)
        return self.exit_codes.pop(0) if self.exit_codes else 0


def _stubbed(porcelain, exit_codes=None, last_date="2026-07-06"):
    """Point daily's collaborators at stubs; return the run recorder."""
    recorder = _Recorder(exit_codes)
    daily.run = recorder
    daily._porcelain = lambda: porcelain
    daily.last_measurement_date = lambda path: last_date
    return recorder


def test_has_changes():
    assert daily.has_changes("") is False
    assert daily.has_changes("\n") is False
    assert daily.has_changes(" M pollen.jsonl\n") is True


def test_commit_message():
    assert daily.commit_message("2026-07-06") == "data: 2026-07-06 measurement"
    assert daily.commit_message(None) == "data: new measurement"


def test_main_skips_when_no_new_data():
    recorder = _stubbed(porcelain="")
    assert daily.main() == 0
    assert len(recorder.calls) == 1  # only fetch_pollen.py ran
    assert "fetch_pollen.py" in recorder.calls[0][1]


def test_main_publishes_when_new_data():
    recorder = _stubbed(porcelain=" M pollen.jsonl\n")
    assert daily.main() == 0
    assert "fetch_pollen.py" in recorder.calls[0][1]
    assert "viz_pollen.py" in recorder.calls[1][1]
    assert [call[:2] for call in recorder.calls[2:]] == [
        ["git", "add"], ["git", "commit"], ["git", "push"],
    ]
    commit_argv = recorder.calls[3]
    assert "data: 2026-07-06 measurement" in commit_argv
    # only the two data files are ever committed
    assert commit_argv[commit_argv.index("--") + 1:] == ["pollen.jsonl", "pollen.webp"]


def test_main_aborts_when_fetch_fails():
    recorder = _stubbed(porcelain=" M pollen.jsonl\n", exit_codes=[1])
    assert daily.main() == 1
    assert len(recorder.calls) == 1


def test_main_aborts_when_viz_fails():
    recorder = _stubbed(porcelain=" M pollen.jsonl\n", exit_codes=[0, 1])
    assert daily.main() == 1
    assert len(recorder.calls) == 2


def test_main_aborts_when_push_fails():
    recorder = _stubbed(porcelain=" M pollen.jsonl\n", exit_codes=[0, 0, 0, 0, 1])
    assert daily.main() == 1
    assert len(recorder.calls) == 5  # pollen, viz, add, commit, push


_NOW = datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc)


def _health_row(hours_old, measurement_date="2026-07-06"):
    return {
        "fetched_at": (_NOW - timedelta(hours=hours_old)).isoformat(),
        "measurement_date": measurement_date,
    }


def _stub_health(row, venv=True, feed_date=None, feed_error=None):
    """Stub daily's health seams. feed_error wins over feed_date."""
    daily._venv_exists = lambda: venv
    daily.last_row = lambda path: row

    def probe():
        if feed_error is not None:
            raise feed_error
        assert feed_date is not None, "probe called though freshness was OK"
        return feed_date

    daily._feed_measurement_date = probe


def test_staleness_hours():
    assert abs(daily.staleness_hours(_health_row(2), _NOW) - 2.0) < 1e-6
    assert daily.staleness_hours({}, _NOW) is None
    assert daily.staleness_hours({"fetched_at": "not-a-date"}, _NOW) is None


def test_health_ok_when_fresh():
    _stub_health(_health_row(5))  # probe would assert if called
    assert daily.health(_NOW, 30.0) == 0


def test_health_fails_when_venv_missing():
    _stub_health(_health_row(5), venv=False)
    assert daily.health(_NOW, 30.0) == 1


def test_health_stale_but_source_quiet_is_ok():
    _stub_health(_health_row(40), feed_date="2026-07-06")
    assert daily.health(_NOW, 30.0) == 0


def test_health_stale_and_source_ahead_fails():
    _stub_health(_health_row(40), feed_date="2026-07-07")
    assert daily.health(_NOW, 30.0) == 1


def test_health_stale_and_site_down_fails():
    _stub_health(_health_row(40), feed_error=OSError("connection refused"))
    assert daily.health(_NOW, 30.0) == 1


def test_health_fails_without_readable_rows():
    _stub_health(None, feed_date="2026-07-07")
    assert daily.health(_NOW, 30.0) == 1


def test_health_respects_max_age_hours():
    _stub_health(_health_row(40), feed_date=None)  # probe asserts if called
    assert daily.health(_NOW, 48.0) == 0


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
