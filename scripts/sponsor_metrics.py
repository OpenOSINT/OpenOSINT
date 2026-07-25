#!/usr/bin/env python3
"""
Collect sponsorship metrics (GitHub stars/forks/traffic + PyPI downloads)
into a dated JSON snapshot, and print a plain-text summary from them.

Usage:
    python scripts/sponsor_metrics.py                  # collect today's snapshot
    python scripts/sponsor_metrics.py --repo owner/name
    python scripts/sponsor_metrics.py --report          # print email-pasteable summary
    python scripts/sponsor_metrics.py --date 2026-07-25 --force

Requires GITHUB_TOKEN in the environment for collection (needs push access
to the repo — the traffic/* endpoints require it). --report reads only
already-collected snapshots and never touches the network.

GitHub's traffic API only ever returns the last 14 days of daily views/clones
(a rolling window, not history). Each collect run merges the new daily data
with previously saved snapshots to build a running series, from which a
trailing-30-day rollup is computed. That rollup sums each day's unique-visitor
count — it is NOT a deduplicated 30-day unique-visitor count (a visitor
returning on multiple days is counted once per day), which is why it's
labeled "daily-summed" everywhere it's reported.

Running this script is idempotent per date: it refuses to overwrite an
existing dated snapshot unless --force is passed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

_REPO_ROOT = Path(__file__).parent.parent
_DEFAULT_OUT_DIR = _REPO_ROOT / "data" / "metrics"
_DEFAULT_REPO = "OpenOSINT/OpenOSINT"

_GITHUB_API_BASE = "https://api.github.com"
_PYPISTATS_API_BASE = "https://pypistats.org/api"
_TIMEOUT_SECONDS = 15
_TRAILING_WINDOW_DAYS = 30


# ---------------------------------------------------------------------------
# GitHub API
# ---------------------------------------------------------------------------


def _github_headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _github_get(path: str, token: str) -> dict:
    resp = requests.get(
        f"{_GITHUB_API_BASE}{path}",
        headers=_github_headers(token),
        timeout=_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    return resp.json()


def _normalize_daily(raw_daily: list[dict]) -> list[dict]:
    return [
        {"date": entry["timestamp"][:10], "count": entry["count"], "uniques": entry["uniques"]}
        for entry in raw_daily
    ]


def fetch_repo_stats(repo: str, token: str) -> dict:
    data = _github_get(f"/repos/{repo}", token)
    return {
        "stars": data["stargazers_count"],
        "forks": data["forks_count"],
        "watchers": data["subscribers_count"],
    }


def fetch_traffic_views(repo: str, token: str) -> dict:
    data = _github_get(f"/repos/{repo}/traffic/views", token)
    return {
        "total": data["count"],
        "unique_total": data["uniques"],
        "daily": _normalize_daily(data["views"]),
    }


def fetch_traffic_clones(repo: str, token: str) -> dict:
    data = _github_get(f"/repos/{repo}/traffic/clones", token)
    return {
        "total": data["count"],
        "unique_total": data["uniques"],
        "daily": _normalize_daily(data["clones"]),
    }


def fetch_traffic_referrers(repo: str, token: str) -> list[dict]:
    data = _github_get(f"/repos/{repo}/traffic/popular/referrers", token)
    return [{"referrer": e["referrer"], "count": e["count"], "uniques": e["uniques"]} for e in data]


def fetch_traffic_paths(repo: str, token: str) -> list[dict]:
    data = _github_get(f"/repos/{repo}/traffic/popular/paths", token)
    return [{"path": e["path"], "count": e["count"], "uniques": e["uniques"]} for e in data]


# ---------------------------------------------------------------------------
# PyPI (pypistats.org — no auth needed)
# ---------------------------------------------------------------------------


def fetch_pypi_downloads(package: str) -> dict:
    resp = requests.get(
        f"{_PYPISTATS_API_BASE}/packages/{package}/recent",
        timeout=_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    data = resp.json()["data"]
    return {
        "downloads_last_day": data["last_day"],
        "downloads_last_week": data["last_week"],
        "downloads_last_month": data["last_month"],
    }


# ---------------------------------------------------------------------------
# Snapshot collection
# ---------------------------------------------------------------------------


def collect_snapshot(repo: str, token: str) -> dict:
    package = repo.split("/")[-1].lower()
    return {
        "github": {
            **fetch_repo_stats(repo, token),
            "traffic": {
                "views": fetch_traffic_views(repo, token),
                "clones": fetch_traffic_clones(repo, token),
                "referrers": fetch_traffic_referrers(repo, token),
                "paths": fetch_traffic_paths(repo, token),
            },
        },
        "pypi": fetch_pypi_downloads(package),
    }


def load_snapshots(out_dir: Path) -> list[dict]:
    """Load all saved snapshots, sorted ascending by date. Never touches the network."""
    if not out_dir.exists():
        return []
    snapshots = []
    for path in sorted(out_dir.glob("*.json")):
        try:
            snapshots.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return sorted(snapshots, key=lambda s: s["date"])


# ---------------------------------------------------------------------------
# Trailing-30-day rollup (stitches overlapping 14-day windows together)
# ---------------------------------------------------------------------------


def _merge_daily(snapshots: list[dict], series_key: str) -> dict[str, dict]:
    """Merge `daily` entries across snapshots, keyed by calendar date.

    Snapshots are processed oldest-first so a later snapshot's value for a
    given day replaces an earlier one (last-write-wins).
    """
    merged: dict[str, dict] = {}
    for snap in sorted(snapshots, key=lambda s: s["date"]):
        daily = snap.get("github", {}).get("traffic", {}).get(series_key, {}).get("daily", [])
        for entry in daily:
            merged[entry["date"]] = entry
    return merged


def compute_trailing_30_days(snapshots: list[dict], as_of: str) -> dict:
    as_of_date = date.fromisoformat(as_of)
    window_start = as_of_date - timedelta(days=_TRAILING_WINDOW_DAYS - 1)

    result = {}
    for series_key in ("views", "clones"):
        merged = _merge_daily(snapshots, series_key)
        in_window = [
            entry
            for day_str, entry in merged.items()
            if window_start <= date.fromisoformat(day_str) <= as_of_date
        ]
        result[series_key] = {
            "count": sum(e["count"] for e in in_window),
            "unique_days_sum": sum(e["uniques"] for e in in_window),
            "days_covered": len(in_window),
        }
    return result


# ---------------------------------------------------------------------------
# --report rendering (reads local snapshots only, no network)
# ---------------------------------------------------------------------------


def _find_snapshot_near(snapshots: list[dict], target: date, tolerance_days: int = 5) -> dict | None:
    best, best_diff = None, None
    for snap in snapshots:
        diff = abs((date.fromisoformat(snap["date"]) - target).days)
        if diff <= tolerance_days and (best_diff is None or diff < best_diff):
            best, best_diff = snap, diff
    return best


def _pct_change(old: float, new: float) -> str:
    if old == 0:
        return "n/a"
    pct = (new - old) / old * 100
    return f"{'+' if pct >= 0 else ''}{pct:.0f}%"


def render_report(out_dir: Path) -> str:
    snapshots = load_snapshots(out_dir)
    if not snapshots:
        return f"[sponsor_metrics] No snapshots found in {out_dir}. Run without --report to collect one."

    latest = snapshots[-1]
    latest_date = date.fromisoformat(latest["date"])
    prior = _find_snapshot_near(snapshots[:-1], latest_date - timedelta(days=_TRAILING_WINDOW_DAYS))

    lines = [f"OpenOSINT — sponsorship metrics (as of {latest['date']})", ""]

    stars = latest["github"]["stars"]
    stars_line = f"Stars:                                       {stars:,}"
    if prior:
        delta = stars - prior["github"]["stars"]
        stars_line += f"  ({'+' if delta >= 0 else ''}{delta} vs {prior['date']})"
    lines.append(stars_line)

    trailing = latest.get("trailing_30_days", {})
    visits = trailing.get("views", {}).get("unique_days_sum", 0)
    views_count = trailing.get("views", {}).get("count", 0)
    visits_line = f"Trailing 30d unique visits (daily-summed):  {visits:,}"
    if prior:
        prior_visits = prior.get("trailing_30_days", {}).get("views", {}).get("unique_days_sum", 0)
        visits_line += f"  ({_pct_change(prior_visits, visits)} vs prior 30d)"
    lines.append(visits_line)
    lines.append(f"Trailing 30d views:                          {views_count:,}")

    downloads = latest["pypi"]["downloads_last_month"]
    downloads_line = f"PyPI downloads (last 30 days):              {downloads:,}"
    if prior:
        prior_downloads = prior["pypi"]["downloads_last_month"]
        downloads_line += f"  ({_pct_change(prior_downloads, downloads)} vs prior 30d)"
    lines.append(downloads_line)

    referrers = latest["github"]["traffic"].get("referrers", [])
    if referrers:
        top = referrers[0]
        lines.append(f"Top referrer:                                {top['referrer']} ({top['count']} visits)")

    if not prior:
        days_span = (latest_date - date.fromisoformat(snapshots[0]["date"])).days
        lines.append("")
        lines.append(f"(insufficient history for month-over-month growth — {days_span} days collected so far)")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", default=_DEFAULT_REPO, help=f"owner/name (default: {_DEFAULT_REPO}).")
    parser.add_argument("--out-dir", type=Path, default=_DEFAULT_OUT_DIR, help="Snapshot directory.")
    parser.add_argument("--date", default=None, help="Snapshot date, YYYY-MM-DD (default: today, UTC).")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing dated snapshot.")
    parser.add_argument("--report", action="store_true", help="Print a summary from saved snapshots (no network).")
    args = parser.parse_args()

    if args.report:
        print(render_report(args.out_dir))
        return

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit(
            "[sponsor_metrics] ERROR: GITHUB_TOKEN env var is not set. "
            "Needs 'repo' scope (traffic endpoints require push access)."
        )

    snapshot_date = args.date or datetime.now(timezone.utc).date().isoformat()
    snapshot_path = args.out_dir / f"{snapshot_date}.json"
    if snapshot_path.exists() and not args.force:
        sys.exit(f"[sponsor_metrics] {snapshot_path} already exists. Use --force to overwrite.")

    snapshot = collect_snapshot(args.repo, token)
    snapshot["date"] = snapshot_date
    snapshot["repo"] = args.repo
    snapshot["trailing_30_days"] = compute_trailing_30_days(
        [*load_snapshots(args.out_dir), snapshot], snapshot_date
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    print(f"[sponsor_metrics] Wrote {snapshot_path}")


if __name__ == "__main__":
    main()
