# Plan: `scripts/sponsor_metrics.py` — sponsorship metrics snapshotting

Goal: stop screenshotting GitHub Insights by hand. One script collects GitHub
stats + traffic + PyPI downloads into a dated JSON snapshot, a weekly Action
commits the snapshot so traffic history accumulates past GitHub's 14-day
window, and a `--report` flag turns snapshots into an email-pasteable summary.

## Research findings that shape this plan

- `scripts/` already exists as a non-package location for standalone tooling
  (excluded from setuptools via `exclude = ["scripts*", ...]`). Closest
  precedent: `scripts/render_sponsors.py` — stdlib-only except no HTTP calls,
  argparse-based, `sys.exit(f"[tag] ERROR: ...")` on bad input, idempotent
  writes with a clear "Updated" vs "already up to date" message. This script
  follows the same shape.
- **`requests>=2.31.0` is already a hard dependency** (`pyproject.toml:35`).
  Both GitHub's REST API and pypistats' JSON API are plain `requests.get`
  calls — no new dependency needed anywhere.
- GitHub API auth pattern to mirror (`openosint/tools/search_github.py`):
  `Authorization: Bearer {token}`, `Accept: application/vnd.github+json`,
  `X-GitHub-Api-Version: 2022-11-28`, explicit timeout, `raise_for_status()`.
  That file uses `aiohttp` because the rest of `openosint/` is async; this
  script is a standalone sync CLI, so plain `requests` is the right fit, not
  a reason to pull `aiohttp` in.
- `docs/assets/metrics.js` already fetches stars/forks client-side and has a
  `ponytail:` comment explaining pypistats has no CORS header, so a *browser*
  fetch is blocked. That's irrelevant here — this script runs server-side
  (locally or in Actions), so plain `requests.get` to pypistats works fine.
- No `.github/workflows/` file today runs tests, lint, or commits generated
  content back to the repo. `release.yml` is the closest style reference for
  Actions conventions: `ubuntu-latest`, `actions/checkout@v4`,
  `actions/setup-python@v5` with `python-version: '3.11'`. The "generate
  then commit" mechanic (used for demo GIFs) has so far always been a manual
  local commit by the maintainer — this workflow introduces the first
  auto-commit-back Action in the repo, so it needs its own care (loop
  avoidance, `contents: write` permission).
- No `data/` directory exists yet — this plan creates `data/metrics/`.
- No caller: this script is a standalone CLI invoked by a human or by the
  new Actions workflow, not imported by anything in `openosint/`.

## Script: `scripts/sponsor_metrics.py`

Stdlib (`argparse`, `json`, `os`, `sys`, `datetime`, `pathlib`) + `requests`.
No import from `openosint/` — self-contained, same reasoning as
`render_sponsors.py`'s docstring ("no openosint import so the script is
self-contained").

### Commands / flags

```
python scripts/sponsor_metrics.py                 # collect today's snapshot
python scripts/sponsor_metrics.py --repo owner/name
python scripts/sponsor_metrics.py --report         # print email summary, no network calls
python scripts/sponsor_metrics.py --date 2026-07-25 --force  # overwrite an existing snapshot
```

- `--repo` default `OpenOSINT/OpenOSINT`.
- `--out-dir` default `data/metrics/`.
- `--date` default today (UTC), for backfill/testing.
- `--force` required to overwrite an existing dated snapshot (default:
  refuse and print the existing path, mirroring render_sponsors' "already up
  to date" pattern rather than silently clobbering a day's data).
- `--report`: reads snapshots already on disk under `--out-dir` and prints a
  plain-text summary. **Never calls the network** — report generation is
  decoupled from collection so it works fully offline and can't fail because
  a token is missing.

### Token handling

```python
token = os.environ.get("GITHUB_TOKEN")
if not token:
    sys.exit("[sponsor_metrics] ERROR: GITHUB_TOKEN env var is not set. "
              "Needs 'repo' scope (traffic endpoints require push access).")
```

Checked before any network call, in collect mode only (`--report` needs no
token). Never read from a CLI flag or file — env only, per constraint.

### What gets collected (per run)

1. `GET /repos/{repo}` → `stargazers_count`, `forks_count`,
   `subscribers_count` (true "watching" count — `watchers_count` is a legacy
   alias for stars, would be a misleading field to report).
2. `GET /repos/{repo}/traffic/views?per=day` → 14 daily `{date, count,
   uniques}` + totals.
3. `GET /repos/{repo}/traffic/clones?per=day` → same shape for clones.
4. `GET /repos/{repo}/traffic/popular/referrers` → top 10 referrers.
5. `GET /repos/{repo}/traffic/popular/paths` → top 10 paths.
6. `GET https://pypistats.org/api/packages/openosint/recent` → downloads
   `last_day` / `last_week` / `last_month` (no auth required).

### Snapshot schema — `data/metrics/YYYY-MM-DD.json`

All values below are synthetic placeholders illustrating field names and
shape, not real repo data:

```json
{
  "date": "2026-07-25",
  "repo": "OpenOSINT/OpenOSINT",
  "github": {
    "stars": 0,
    "forks": 0,
    "watchers": 0,
    "traffic": {
      "views": {"total": 0, "unique_total": 0, "daily": [{"date": "2026-07-20", "count": 0, "uniques": 0}]},
      "clones": {"total": 0, "unique_total": 0, "daily": [{"date": "2026-07-20", "count": 0, "uniques": 0}]},
      "referrers": [{"referrer": "google.com", "count": 0, "uniques": 0}],
      "paths": [{"path": "/", "count": 0, "uniques": 0}]
    }
  },
  "pypi": {
    "downloads_last_day": 0,
    "downloads_last_week": 0,
    "downloads_last_month": 0
  }
}
```

### Trailing-30-day rollup (the part that stitches snapshots together)

GitHub's traffic API only ever returns the **last 14 days** of daily
`views`/`clones` data — it's a rolling window, not cumulative history. To get
a real 30-day trend the script has to merge each week's `daily` arrays into
one running time series on disk:

- On each collect run, after fetching the new snapshot, scan the last ~6
  existing `data/metrics/*.json` files, merge all `daily` entries for
  `views` and `clones` into a dict keyed by calendar date (`{date: {count,
  uniques}}`), **last-write-wins** on duplicate dates (the newest snapshot's
  value for a given day replaces older ones — matters if GitHub revises a
  day's count after it's fully closed out).
- Store this merged series in the snapshot too, under
  `"trailing_30_days": {"views": {"count": N, "unique_days_sum": M}, "clones": {...}}`,
  computed from whatever merged days fall within the last 30 calendar days.
- **Caveat to document in the script's docstring and in `--report` output**:
  summing daily `uniques` across 30 days is **not** the same as a true
  30-day unique-visitor count — a visitor who returns on multiple days is
  counted once per day. GitHub's API gives no way to deduplicate across
  days. Label the report field "unique visits (daily-summed)" rather than
  implying a deduplicated monthly-active-visitor number, so it's never
  misquoted in a sponsorship pitch.
- Weekly cadence (7 days) is comfortably inside the 14-day window, so no
  gaps as long as the Action runs on schedule; a `--report` run should warn
  (not fail) if it detects a gap >14 days between consecutive snapshots,
  since that means real data was lost to the rolling window.

### `--report` output (plain text, paste into an email)

```
OpenOSINT — sponsorship metrics (as of 2026-07-25)

Stars:              1,234  (+56 vs 2026-06-25)
Trailing 30d unique visits (daily-summed): 890  (+12% vs prior 30d)
Trailing 30d views:                         3,410
PyPI downloads (last 30 days):              2,105  (+8% vs prior 30d)
Top referrer:                               github.com (410 visits)
```

Growth-vs-previous-month lines only appear when a snapshot ~30 days older
exists; otherwise print `(insufficient history — N days collected so far)`
instead of a fabricated 0%.

## GitHub Actions workflow: `.github/workflows/sponsor-metrics.yml`

```yaml
name: Sponsor Metrics

on:
  schedule:
    - cron: '0 6 * * 1'   # weekly, Monday 06:00 UTC
  workflow_dispatch: {}

permissions:
  contents: write

jobs:
  snapshot:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install requests
        run: pip install requests
      - name: Collect snapshot
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: python scripts/sponsor_metrics.py
      - name: Commit snapshot
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add data/metrics/
          git diff --cached --quiet || git commit -m "chore: weekly sponsor metrics snapshot [skip ci]"
          git push
```

Open question to verify during implementation, not before: whether the
default `secrets.GITHUB_TOKEN` (auto-provided, scoped to the current repo)
is sufficient for the `/traffic/*` endpoints, or whether it needs the same
kind of PAT the repo already uses in `cla.yml`
(`secrets.PERSONAL_ACCESS_TOKEN`). GitHub's docs say traffic endpoints need
push access to the repo, which the default token has for its own repo — but
this is exactly the kind of thing that's cheap to prove with one manual
`workflow_dispatch` run before trusting the weekly cron.

`[skip ci]` avoids loop risk even though no CI currently runs on push — kept
as cheap insurance since this is the first workflow in the repo that commits
back.

## Verification criteria (before this plan is considered done)

1. `python scripts/sponsor_metrics.py --help` runs with no env vars set and
   no network access.
2. Unset `GITHUB_TOKEN` → collect mode exits non-zero with the exact
   stderr message above, and makes zero network calls (verifiable by
   mocking `requests.get` to raise if called).
3. With a valid token exported locally, one collect run produces
   `data/metrics/<today>.json` matching the schema above, validated by a
   small pytest (`tests/test_sponsor_metrics.py`) that mocks `requests.get`
   responses per endpoint rather than hitting the real API.
4. Running collect twice for the same `--date` without `--force` refuses
   and prints the existing path; with `--force` it overwrites.
5. `--report` works from `data/metrics/` alone with `requests.get` mocked to
   raise on any call — proves it never touches the network.
6. Rollup merge logic has a unit test for the last-write-wins overlap case
   (two synthetic snapshots with an overlapping day where the second has a
   different count — merged result must take the second).
7. `ruff check scripts/sponsor_metrics.py` passes under the repo's existing
   config (`target-version py310`, `line-length 100`, `select E,F,I,W`).
8. Workflow YAML is valid (`actionlint` if available locally, otherwise
   careful manual review) and is first exercised via manual
   `workflow_dispatch`, not the cron, to confirm the commit-back step and
   token scope actually work before relying on the schedule.

## Explicitly out of scope (YAGNI)

- No new dependency for pypistats — hitting its JSON API directly with
  `requests` covers the one endpoint needed.
- No database, no charting, no HTML report — `--report` is plain text
  because that's what gets pasted into an email.
- No historical backfill tooling beyond `--date` — if 14 days of traffic
  history are missing before this script's first run, they're gone; nothing
  to build here recovers that.
