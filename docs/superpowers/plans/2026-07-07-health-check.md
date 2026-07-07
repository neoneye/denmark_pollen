# daily.py --health Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only `--health` mode to `daily.py` that checks venv presence, data freshness (default 30 h), and — only when stale — probes the live feed to distinguish "site down" and "cron broken" from "source hasn't published".

**Architecture:** `health(now, max_age_hours)` orchestrates four checks through small stubbable seams (`_venv_exists`, `last_row`, `staleness_hours`, `_feed_measurement_date`); `main()` gains argparse with `--health` / `--max-age-hours` and otherwise runs the existing publish flow unchanged.

**Tech Stack:** Python 3.14 stdlib; reuses `fetch_pollen.fetch_feed` / `parse_feed` for the probe.

Spec: `docs/superpowers/specs/2026-07-07-health-check-design.md`

## Global Constraints

- `--health` is read-only: no writes to `pollen.jsonl`/`pollen.webp`, no git commands.
- Exit codes: 0 = healthy (including "stale but source quiet"), 1 = any failed check.
- All health output lines go through `say()` with a `health:` prefix; every check prints a line (OK or FAIL), not just the first failure.
- Tests stub module attributes by assignment and pass a fixed timezone-aware `now` — no network, no real clock, no subprocesses.

---

### Task 1: --health mode in daily.py

**Files:**
- Modify: `daily.py`
- Modify: `test_daily.py`
- Modify: `README.md` (add Health check section)

**Interfaces:**
- Consumes: `fetch_pollen.fetch_feed() -> str`, `fetch_pollen.parse_feed(raw) -> tuple[str, dict]`.
- Produces: `health(now: datetime, max_age_hours: float) -> int`; `last_row(path: str) -> Optional[dict]`; `staleness_hours(row: dict, now: datetime) -> Optional[float]`; `_venv_exists() -> bool`; `_feed_measurement_date() -> str`; `main(argv)` accepts `--health` and `--max-age-hours`.

- [ ] **Step 1: Write the failing tests** — append to `test_daily.py` above the `__main__` block (and add `from datetime import datetime, timedelta, timezone` to its imports):

```python
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
```

- [ ] **Step 2: Run to verify failure** — `python3 test_daily.py` → the new tests FAIL with `AttributeError` (no `health`/`staleness_hours`); the 7 existing tests still PASS.

- [ ] **Step 3: Implement** — in `daily.py`: add `import argparse`, `import json`, `from datetime import datetime`, extend the `fetch_pollen` import to include `fetch_feed, parse_feed`, and add:

```python
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
```

and replace `main()`'s first lines with:

```python
def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Daily pollen pipeline: fetch, chart, commit, push.")
    parser.add_argument("--health", action="store_true", help="run read-only health checks and exit 0/1")
    parser.add_argument("--max-age-hours", type=float, default=MAX_AGE_HOURS,
                        help=f"staleness threshold for --health (default: {MAX_AGE_HOURS:g})")
    args = parser.parse_args(argv)

    if args.health:
        return health(datetime.now().astimezone(), args.max_age_hours)
```

(the existing fetch→chart→publish body follows unchanged).

- [ ] **Step 4: Run to verify pass** — `python3 test_daily.py` → PASS × 15; `python3 test_fetch_pollen.py` and `.venv/bin/python3 test_viz_pollen.py` unchanged.

- [ ] **Step 5: Real runs** — `python3 daily.py --health` (expect stale-probe path or fresh path depending on feed; exit 0 if pipeline healthy) and `python3 daily.py --health --max-age-hours 0.01` (forces the probe; observe site-probe messages). Confirm no git changes: `git status --short` clean.

- [ ] **Step 6: README** — add under Tests:

````markdown
## Health check

```sh
python3 daily.py --health            # exit 0 = pipeline healthy, 1 = problems
python3 daily.py --health --max-age-hours 48
```

Checks: venv present, `pollen.jsonl` readable, data fresher than the threshold
(default 30 h). When stale it probes the live feed to distinguish "source
hasn't published" (OK) from "site down" or "cron not recording" (FAIL).
````

- [ ] **Step 7: Commit**

```bash
git add daily.py test_daily.py README.md
git commit -m "feat: add read-only --health mode to daily.py"
```
