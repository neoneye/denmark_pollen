# Daily Orchestrator — Design

Date: 2026-07-07
Status: approved

## Goal

One cron entry point, `daily.py`, that fetches the day's pollen data, and — only
when a new measurement arrived — regenerates the chart, commits, and pushes to
github.com/neoneye/denmark_pollen (remote `origin`, already configured over SSH).

## Non-goals

- No changes to `pollen.py` or `viz_pollen.py`.
- No retry/backoff logic; cron tries again tomorrow.
- Never commits anything beyond `pollen.jsonl` and `pollen.webp`.

## Flow

1. Run `pollen.py` with the invoking interpreter (`sys.executable`), cwd = repo dir.
   Non-zero exit → abort with exit 1.
2. Ask git whether `pollen.jsonl` has uncommitted changes
   (`git status --porcelain -- pollen.jsonl`). Unchanged → print
   `daily: no new measurement (last recorded <date>); nothing to do` and exit 0.
   The date comes from `pollen.last_measurement_date`.
   (Side effect: if a previous run appended data but died before pushing, the file
   is still dirty, so the next run finishes the job.)
3. Run `viz_pollen.py` with `.venv/bin/python3`. Non-zero exit → abort with exit 1.
4. `git add -- pollen.jsonl pollen.webp`, then
   `git commit -m "data: <date> measurement" -- pollen.jsonl pollen.webp`
   (pathspec-limited so unrelated dirty files are never swept in), then
   `git push origin main`. Any failure → abort with exit 1; a failed push leaves
   the commit local and tomorrow's push carries it.

## Behavior details

- All paths resolve relative to the script's own directory; cron needs no `cd`.
- The script's own status lines are prefixed `daily:`; child output streams through.
- A missing `.venv` interpreter is reported with the setup command, exit 127
  (via the shared runner's FileNotFoundError handling).

## Deliverables

- `daily.py` — stdlib only.
- `test_daily.py` — bare-runner style, like the other test files. Pure helpers
  (`has_changes`, `commit_message`) tested directly; `main()` flow tested by
  monkeypatching the module's `run`/`_porcelain`/`last_measurement_date` — tests
  never touch real git state and never push.
- README cron section becomes: `30 13 * * * python3 /Users/neoneye/git/denmark_pollen/daily.py`
