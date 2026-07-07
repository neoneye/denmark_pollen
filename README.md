# denmark_pollen

Daily Copenhagen pollen counts from [astma-allergi.dk](https://www.astma-allergi.dk),
logged to `pollen.jsonl` and charted to `pollen.webp`.

![Pollen chart](pollen.webp)

## Scripts

- `pollen.py` — fetches today's counts and appends one JSONL row per measurement
  day (stdlib only).
- `viz_pollen.py` — renders `pollen.jsonl` as a small-multiples chart (webp by
  default; the `--out` extension picks the format), one panel per in-season pollen
  type, with the site's low/moderate/high thresholds as background bands. Needs
  matplotlib.

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
