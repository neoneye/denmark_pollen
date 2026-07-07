# Daily Orchestrator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `daily.py`, the single cron entry point that fetches data and, only when a new measurement arrived, re-renders the chart, commits `pollen.jsonl` + `pollen.webp`, and pushes to origin/main.

**Architecture:** One stdlib-only script: tiny pure helpers (`has_changes`, `commit_message`) plus a `main()` that shells out through one `run()` chokepoint, so tests stub `run`/`_porcelain` and never touch real git.

**Tech Stack:** Python 3.14 stdlib (`subprocess`, `os`, `sys`); imports `last_measurement_date` from `pollen.py`.

Spec: `docs/superpowers/specs/2026-07-07-daily-orchestrator-design.md`

## Global Constraints

- `daily.py` runs on the system Python — stdlib only, no matplotlib import.
- Only `pollen.jsonl` and `pollen.webp` may ever be committed (pathspec-limited add + commit).
- All paths relative to the script's directory (`os.path.dirname(os.path.abspath(__file__))`); no `cd` needed in cron.
- Tests must not run real git commands or subprocesses — stub `daily.run` and `daily._porcelain` by attribute assignment.
- Exit codes: 0 = success or nothing-to-do, 1 = child/git failure, 127 = missing interpreter.

---

### Task 1: daily.py + tests + README cron update

**Files:**
- Create: `daily.py`
- Create: `test_daily.py`
- Modify: `README.md` (cron section)

**Interfaces:**
- Consumes: `pollen.last_measurement_date(path) -> Optional[str]`.
- Produces: `daily.main() -> int`; helpers `has_changes(porcelain: str) -> bool`, `commit_message(measurement_date) -> str`, `run(argv: list[str]) -> int`, `_porcelain() -> str`.

- [ ] **Step 1: Write the failing tests**

Create `test_daily.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 test_daily.py`
Expected: `ModuleNotFoundError: No module named 'daily'`

- [ ] **Step 3: Implement daily.py**

Create `daily.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 test_daily.py`
Expected: `PASS` × 7, exit 0. Also `python3 test_pollen.py` and `.venv/bin/python3 test_viz_pollen.py` still all pass.

- [ ] **Step 5: End-to-end run**

Run: `python3 daily.py`
Expected either path:
- no new data today → `daily: no new measurement (last recorded <date>); nothing to do`, exit 0, git state untouched;
- new data → fetch, render, one commit `data: <date> measurement` containing only pollen.jsonl + pollen.webp, pushed to origin/main.

- [ ] **Step 6: Update README cron section**

Replace the `## Daily cron` block's cron line with:

```cron
30 13 * * * python3 /Users/neoneye/git/denmark_pollen/daily.py
```

and mention that `daily.py` runs fetch → chart → commit → push, and skips
commit/push when there is no new measurement.

- [ ] **Step 7: Commit**

```bash
git add daily.py test_daily.py README.md
git commit -m "feat: add daily.py cron orchestrator (fetch, chart, commit, push)"
```
