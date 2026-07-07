# Pollen Visualization — Design

Date: 2026-07-07
Status: approved

## Goal

Render the accumulated `pollen.jsonl` history as a PNG chart, regenerated daily by
cron right after `pollen.py` appends the day's measurement.

## Non-goals

- No interactive/HTML output.
- No changes to the fetcher (`pollen.py`) beyond importing its constants.
- No forecasting or aggregation beyond plotting the recorded daily levels.

## Deliverables

- `viz_pollen.py` — the visualization script.
- `test_viz_pollen.py` — tests for its pure functions plus a PNG smoke test.
- `requirements.txt` — `matplotlib`.
- `.venv/` (untracked) — project virtualenv used by cron.
- `.gitignore` — new file ignoring `.venv/` and `__pycache__/`.
- README update — cron example and embedded `pollen.png`.

## CLI

```
.venv/bin/python3 viz_pollen.py [--data pollen.jsonl] [--out pollen.png]
```

Exit 0 on success. Exit 1 with a message on stderr when the data file is missing,
unreadable, or contains no plottable rows.

## Data handling

- Read every line of the JSONL file; skip blank lines; skip malformed JSON lines
  with a warning on stderr (never abort on one bad line).
- Deduplicate rows by `measurement_date`, keeping the last occurrence.
- Sort by `measurement_date`.
- A level of `-1` or `null` means "no data" and produces no point.
- A pollen type is "active" (gets a panel) iff it has at least one real
  measurement (level >= 0) anywhere in the file. Panels therefore appear
  automatically as species come into season.

## Chart

- One PNG, small-multiples layout: one panel per active pollen type, stacked in
  a grid with a shared x-axis of real calendar dates (missing days show as gaps;
  the line breaks across gaps rather than interpolating through them).
- Each panel: the level as a line with dot markers, drawn over horizontal
  background bands for low / moderate / high using the thresholds in
  `POLLEN_LEVEL_INTERVALS`, imported from `pollen.py` (single source of truth).
- Independent y-scale per panel (cladosporium counts in the thousands must not
  flatten grass).
- Figure title: station name and covered date range. Footer: data source
  (astma-allergi.dk) and generation timestamp.
- Rendering uses the `Agg` backend explicitly so cron needs no display.

## Robustness

- Atomic output: render to a temp file in the destination directory, then
  `os.replace` onto `--out`, so a crash never leaves a truncated PNG.
- The script is idempotent; rerunning simply regenerates the same PNG.

## Testing

`test_viz_pollen.py`, runnable with `python3 -m unittest`:

- load/dedup/sort behaviour, including malformed and blank lines;
- no-data handling (`-1`/`null` levels, empty file → error exit);
- active-type selection;
- smoke test: rendering the repo's real `pollen.jsonl` writes a non-empty PNG
  to a temp directory.

No pixel-level image assertions.
