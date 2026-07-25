"""Tests for scripts/sponsor_metrics.py: collection, rollup merge, and report rendering."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).parent.parent / "scripts" / "sponsor_metrics.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("sponsor_metrics", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sm = _load_module()

# ---------------------------------------------------------------------------
# Fixtures — canned API responses
# ---------------------------------------------------------------------------

_REPO_RESPONSE = {"stargazers_count": 120, "forks_count": 30, "subscribers_count": 8, "watchers_count": 120}
_VIEWS_RESPONSE = {
    "count": 100,
    "uniques": 40,
    "views": [
        {"timestamp": "2026-07-24T00:00:00Z", "count": 60, "uniques": 25},
        {"timestamp": "2026-07-25T00:00:00Z", "count": 40, "uniques": 15},
    ],
}
_CLONES_RESPONSE = {
    "count": 10,
    "uniques": 5,
    "clones": [{"timestamp": "2026-07-25T00:00:00Z", "count": 10, "uniques": 5}],
}
_REFERRERS_RESPONSE = [{"referrer": "github.com", "count": 50, "uniques": 20}]
_PATHS_RESPONSE = [{"path": "/", "title": "OpenOSINT", "count": 70, "uniques": 30}]
_PYPI_RESPONSE = {"data": {"last_day": 5, "last_week": 40, "last_month": 200}}


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _fake_get_factory():
    def _fake_get(url, headers=None, timeout=None):
        if url.endswith("/repos/Org/Repo"):
            return _FakeResponse(_REPO_RESPONSE)
        if url.endswith("/traffic/views"):
            return _FakeResponse(_VIEWS_RESPONSE)
        if url.endswith("/traffic/clones"):
            return _FakeResponse(_CLONES_RESPONSE)
        if url.endswith("/traffic/popular/referrers"):
            return _FakeResponse(_REFERRERS_RESPONSE)
        if url.endswith("/traffic/popular/paths"):
            return _FakeResponse(_PATHS_RESPONSE)
        if "pypistats.org" in url:
            return _FakeResponse(_PYPI_RESPONSE)
        raise AssertionError(f"unexpected URL requested: {url}")

    return _fake_get


def _refusing_get(*_args, **_kwargs):
    raise AssertionError("network should not be called")


# ---------------------------------------------------------------------------
# Fetch functions
# ---------------------------------------------------------------------------


def test_fetch_repo_stats(monkeypatch):
    monkeypatch.setattr(sm.requests, "get", _fake_get_factory())
    stats = sm.fetch_repo_stats("Org/Repo", "tok")
    assert stats == {"stars": 120, "forks": 30, "watchers": 8}


def test_fetch_repo_stats_sends_auth_headers(monkeypatch):
    captured = {}

    def _get(url, headers=None, timeout=None):
        captured["headers"] = headers
        return _FakeResponse(_REPO_RESPONSE)

    monkeypatch.setattr(sm.requests, "get", _get)
    sm.fetch_repo_stats("Org/Repo", "secret-token")
    assert captured["headers"]["Authorization"] == "Bearer secret-token"
    assert captured["headers"]["X-GitHub-Api-Version"] == "2022-11-28"


def test_fetch_traffic_views_normalizes_daily(monkeypatch):
    monkeypatch.setattr(sm.requests, "get", _fake_get_factory())
    views = sm.fetch_traffic_views("Org/Repo", "tok")
    assert views["total"] == 100
    assert views["unique_total"] == 40
    assert views["daily"] == [
        {"date": "2026-07-24", "count": 60, "uniques": 25},
        {"date": "2026-07-25", "count": 40, "uniques": 15},
    ]


def test_fetch_pypi_downloads(monkeypatch):
    monkeypatch.setattr(sm.requests, "get", _fake_get_factory())
    downloads = sm.fetch_pypi_downloads("repo")
    assert downloads == {"downloads_last_day": 5, "downloads_last_week": 40, "downloads_last_month": 200}


def test_collect_snapshot_shape(monkeypatch):
    monkeypatch.setattr(sm.requests, "get", _fake_get_factory())
    snapshot = sm.collect_snapshot("Org/Repo", "tok")
    assert snapshot["github"]["stars"] == 120
    assert snapshot["github"]["traffic"]["referrers"] == [{"referrer": "github.com", "count": 50, "uniques": 20}]
    assert snapshot["pypi"]["downloads_last_month"] == 200


# ---------------------------------------------------------------------------
# Rollup merge — last-write-wins on overlapping days
# ---------------------------------------------------------------------------


def _snap(date_str, views_daily):
    return {
        "date": date_str,
        "github": {"traffic": {"views": {"daily": views_daily}, "clones": {"daily": []}}},
    }


def test_merge_daily_last_write_wins_on_overlap():
    older = _snap("2026-07-18", [{"date": "2026-07-17", "count": 10, "uniques": 4}])
    newer = _snap("2026-07-25", [{"date": "2026-07-17", "count": 99, "uniques": 40}])
    merged = sm._merge_daily([older, newer], "views")
    assert merged["2026-07-17"] == {"date": "2026-07-17", "count": 99, "uniques": 40}


def test_merge_daily_keeps_non_overlapping_days():
    a = _snap("2026-07-18", [{"date": "2026-07-15", "count": 1, "uniques": 1}])
    b = _snap("2026-07-25", [{"date": "2026-07-22", "count": 2, "uniques": 2}])
    merged = sm._merge_daily([a, b], "views")
    assert set(merged) == {"2026-07-15", "2026-07-22"}


def test_compute_trailing_30_days_excludes_out_of_window():
    old = _snap("2026-06-01", [{"date": "2026-06-01", "count": 500, "uniques": 500}])
    recent = _snap("2026-07-25", [{"date": "2026-07-25", "count": 10, "uniques": 4}])
    rollup = sm.compute_trailing_30_days([old, recent], "2026-07-25")
    assert rollup["views"]["count"] == 10
    assert rollup["views"]["unique_days_sum"] == 4
    assert rollup["views"]["days_covered"] == 1


# ---------------------------------------------------------------------------
# --report rendering (must never touch the network)
# ---------------------------------------------------------------------------


def test_render_report_no_snapshots(tmp_path, monkeypatch):
    monkeypatch.setattr(sm.requests, "get", _refusing_get)
    report = sm.render_report(tmp_path)
    assert "No snapshots found" in report


def test_render_report_single_snapshot_no_network(tmp_path, monkeypatch):
    monkeypatch.setattr(sm.requests, "get", _refusing_get)
    snapshot = {
        "date": "2026-07-25",
        "github": {"stars": 42, "traffic": {"referrers": [{"referrer": "google.com", "count": 9, "uniques": 3}]}},
        "pypi": {"downloads_last_month": 300},
        "trailing_30_days": {"views": {"count": 100, "unique_days_sum": 40}},
    }
    (tmp_path / "2026-07-25.json").write_text(json.dumps(snapshot), encoding="utf-8")

    report = sm.render_report(tmp_path)
    assert "Stars:" in report and "42" in report
    assert "insufficient history" in report
    assert "google.com" in report


def test_render_report_shows_growth_with_prior_snapshot(tmp_path):
    prior = {
        "date": "2026-06-25",
        "github": {"stars": 100, "traffic": {"referrers": []}},
        "pypi": {"downloads_last_month": 100},
        "trailing_30_days": {"views": {"count": 50, "unique_days_sum": 20}},
    }
    latest = {
        "date": "2026-07-25",
        "github": {"stars": 150, "traffic": {"referrers": []}},
        "pypi": {"downloads_last_month": 150},
        "trailing_30_days": {"views": {"count": 80, "unique_days_sum": 30}},
    }
    (tmp_path / "2026-06-25.json").write_text(json.dumps(prior), encoding="utf-8")
    (tmp_path / "2026-07-25.json").write_text(json.dumps(latest), encoding="utf-8")

    report = sm.render_report(tmp_path)
    assert "+50 vs 2026-06-25" in report
    assert "+50%" in report  # downloads growth 100 -> 150


# ---------------------------------------------------------------------------
# CLI — main()
# ---------------------------------------------------------------------------


def test_main_collect_missing_token_exits_without_network(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sm.requests, "get", _refusing_get)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(sys, "argv", ["sponsor_metrics.py", "--repo", "Org/Repo", "--out-dir", str(tmp_path)])

    with pytest.raises(SystemExit) as exc_info:
        sm.main()
    assert "GITHUB_TOKEN" in str(exc_info.value)


def test_main_collect_writes_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(sm.requests, "get", _fake_get_factory())
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    monkeypatch.setattr(
        sys,
        "argv",
        ["sponsor_metrics.py", "--repo", "Org/Repo", "--out-dir", str(tmp_path), "--date", "2026-07-25"],
    )

    sm.main()

    snapshot_path = tmp_path / "2026-07-25.json"
    assert snapshot_path.exists()
    data = json.loads(snapshot_path.read_text())
    assert data["github"]["stars"] == 120
    assert data["trailing_30_days"]["views"]["count"] == 100


def test_main_collect_refuses_overwrite_without_force(tmp_path, monkeypatch):
    monkeypatch.setattr(sm.requests, "get", _fake_get_factory())
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    argv = ["sponsor_metrics.py", "--repo", "Org/Repo", "--out-dir", str(tmp_path), "--date", "2026-07-25"]
    monkeypatch.setattr(sys, "argv", argv)
    sm.main()

    with pytest.raises(SystemExit) as exc_info:
        sm.main()
    assert "already exists" in str(exc_info.value)


def test_main_collect_force_overwrites(tmp_path, monkeypatch):
    monkeypatch.setattr(sm.requests, "get", _fake_get_factory())
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    base_argv = ["sponsor_metrics.py", "--repo", "Org/Repo", "--out-dir", str(tmp_path), "--date", "2026-07-25"]
    monkeypatch.setattr(sys, "argv", base_argv)
    sm.main()

    monkeypatch.setattr(sys, "argv", [*base_argv, "--force"])
    sm.main()  # should not raise

    assert (tmp_path / "2026-07-25.json").exists()


def test_main_report_no_network(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sm.requests, "get", _refusing_get)
    monkeypatch.setattr(sys, "argv", ["sponsor_metrics.py", "--report", "--out-dir", str(tmp_path)])

    sm.main()

    out = capsys.readouterr().out
    assert "No snapshots found" in out


def test_cli_help_runs_without_env_or_network():
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--help"],
        capture_output=True,
        text=True,
        env={"PATH": ""},  # deliberately no GITHUB_TOKEN / network-dependent env
    )
    assert result.returncode == 0
    assert "sponsorship metrics" in result.stdout.lower()
