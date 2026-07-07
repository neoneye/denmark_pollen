# daily.py --health — Design

Date: 2026-07-07
Status: approved

## Goal

`python3 daily.py --health`: a read-only self-diagnosis that answers "is the
daily pollen pipeline working?" with per-check output and an exit code
(0 healthy, 1 problems). Optional `--max-age-hours N` (default 30 = 24 h + 6 h
grace) sets the staleness threshold. Never fetches into the file, never touches
git.

## Checks (all reported, one `health:` line each)

1. **venv** — `.venv/bin/python3` exists; on FAIL print the setup command.
2. **data** — `pollen.jsonl` has a readable last JSON row with a parseable
   `fetched_at` timestamp.
3. **freshness** — hours between now and the last row's `fetched_at`
   ≤ threshold → OK and no probe.
4. **source probe** — only when freshness cannot be confirmed (stale, no rows,
   or bad `fetched_at`): fetch + parse the live feed via `fetch_pollen.fetch_feed`
   / `parse_feed`:
   - fetch/parse raises → FAIL "feed not responding or unparseable";
   - feed measurement date newer than our last recorded → FAIL "pipeline is not
     recording" (cron broken);
   - feed date ≤ ours → OK, informational "source has not published beyond
     <date>; pipeline healthy".

## Structure

- `health(now, max_age_hours) -> int` in `daily.py`, plus small seams for tests:
  `_venv_exists()`, `last_row(path)`, `staleness_hours(row, now)`,
  `_feed_measurement_date()`.
- `main()` grows argparse: `--health` flag and `--max-age-hours`; without
  `--health` the existing fetch→chart→publish flow is unchanged.

## Testing

Extend `test_daily.py` (bare-runner style): stub `_venv_exists`, `last_row`,
`_feed_measurement_date` by assignment; pass a fixed aware `now` so staleness is
deterministic. Cover: fresh OK; venv missing; stale + source quiet (exit 0);
stale + source ahead (exit 1); stale + site down (exit 1); unreadable data file
(exit 1); `staleness_hours` edge cases. No network, no real clock, no git.

## README

Add a Health check section with the command and what exit codes mean.
