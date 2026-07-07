#!/usr/bin/env python3
"""Offline tests for daily.py — no subprocesses, no git. Run: python3 test_daily.py"""

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
    assert len(recorder.calls) == 1  # only pollen.py ran
    assert "pollen.py" in recorder.calls[0][1]


def test_main_publishes_when_new_data():
    recorder = _stubbed(porcelain=" M pollen.jsonl\n")
    assert daily.main() == 0
    assert "pollen.py" in recorder.calls[0][1]
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
