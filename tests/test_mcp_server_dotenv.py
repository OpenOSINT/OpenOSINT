# tests/test_mcp_server_dotenv.py
"""
openosint/mcp_server.py resolves its .env via
openosint.env.load_env(prefer_package_root=True)'s three-step cascade —
OPENOSINT_ENV_FILE override, then the repo-root .env, then python-dotenv's
own cwd-upward search as a last resort.

MCP is the ONE entry point that checks repo-root before cwd search — the
opposite of the CLI/web server priority (see tests/test_env_loading.py).
Claude Desktop and other MCP hosts launch this process with an arbitrary
cwd that has nothing to do with any .env the user intends (often the
user's home directory, or wherever the host itself happens to run from),
so an upward cwd search from there risks silently picking up an unrelated
.env before a real repo-root one is ever considered. A fixed
__file__-anchored path resolves into site-packages/.env under a normal
(non-editable) pip install, a location no user will ever populate — hence
the cwd-search fallback still exists, just last in line for this entry
point. For MCP, OPENOSINT_ENV_FILE (or the client's own `env` config
block) is the reliable way to point at a specific file.

These tests run the real module in a subprocess, with a from-scratch
environment and cwd deliberately set away from the repo, and assert the
resulting os.environ — not the arguments passed to load_dotenv(). A
mock on the call signature would keep passing even if path resolution
were silently broken (e.g. always resolving into site-packages); actually
importing the module and reading back os.environ catches that.

No network access. Case B/C use a throwaway copy of the openosint package
under tmp_path so the real repo .env is never read, touched, or depended
on for its contents.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PACKAGE_DIR = _REPO_ROOT / "openosint"
_PYTHON = sys.executable

_PROBE = (
    "import json, os\n"
    "import openosint.mcp_server\n"
    "print(json.dumps({k: os.environ.get(k) for k in "
    "('MARKER_A', 'MARKER_B', 'MARKER_C')}))\n"
)


def _clean_env(**overrides: str) -> dict[str, str]:
    """A from-scratch subprocess environment: only PATH/HOME (so the
    interpreter and stdlib work) plus explicit overrides — nothing
    inherited from this test process's own env leaks in."""
    base = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")}
    base.update(overrides)
    return base


def _run_probe(*, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [_PYTHON, "-c", _PROBE],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _markers(result: subprocess.CompletedProcess) -> dict:
    import json

    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


class TestExplicitOverride:
    """Cascade step (a): OPENOSINT_ENV_FILE, if set, wins outright."""

    def test_explicit_env_file_is_loaded(self, tmp_path):
        custom_env = tmp_path / "custom.env"
        custom_env.write_text("MARKER_A=explicit-value\n")
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()

        result = _run_probe(
            cwd=elsewhere,  # away from the repo
            env=_clean_env(OPENOSINT_ENV_FILE=str(custom_env)),
        )

        assert _markers(result)["MARKER_A"] == "explicit-value"

    def test_explicit_env_file_does_not_override_real_env_var(self, tmp_path):
        """override=False: a var already in the process env beats the file —
        but the file must still be genuinely loaded. MARKER_B is set only in
        the file, never in the subprocess env directly: without it, this
        test would pass even against code that never calls load_dotenv() at
        all, since it would just be reading back a value it set itself."""
        custom_env = tmp_path / "custom.env"
        custom_env.write_text("MARKER_A=from-file\nMARKER_B=file-loaded\n")
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()

        result = _run_probe(
            cwd=elsewhere,
            env=_clean_env(OPENOSINT_ENV_FILE=str(custom_env), MARKER_A="from-real-env"),
        )

        markers = _markers(result)
        assert markers["MARKER_A"] == "from-real-env"  # pre-set env wins (override=False)
        assert markers["MARKER_B"] == "file-loaded"  # proves the file was actually read

    def test_missing_explicit_env_file_fails_loudly(self, tmp_path):
        missing = tmp_path / "does-not-exist.env"
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()

        result = _run_probe(cwd=elsewhere, env=_clean_env(OPENOSINT_ENV_FILE=str(missing)))

        assert result.returncode != 0
        assert "OPENOSINT_ENV_FILE" in result.stderr
        assert str(missing) in result.stderr


class TestRepoRootAndCwdFallback:
    """Cascade steps (b) repo-root .env and (c) cwd-upward search fallback.

    Both need a throwaway copy of the package so the real repo .env is
    never read: a fixed __file__-anchored path is exactly the bug being
    fixed, so these tests must control what "repo root" resolves to.
    """

    def _copy_package(self, dest_root: Path) -> None:
        shutil.copytree(_PACKAGE_DIR, dest_root / "openosint")

    def test_repo_root_env_used_when_present(self, tmp_path):
        pkgroot = tmp_path / "pkgroot"
        self._copy_package(pkgroot)
        (pkgroot / ".env").write_text("MARKER_B=repo-root-value\n")
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()

        result = _run_probe(
            cwd=elsewhere,  # cwd is NOT pkgroot — proves this isn't a cwd-search hit
            env=_clean_env(PYTHONPATH=str(pkgroot)),
        )

        assert _markers(result)["MARKER_B"] == "repo-root-value"

    def test_falls_back_to_cwd_search_when_no_repo_root_env(self, tmp_path):
        pkgroot = tmp_path / "pkgroot"
        self._copy_package(pkgroot)
        # Deliberately no .env at pkgroot — forces the cascade past step (b).
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        (work_dir / ".env").write_text("MARKER_C=cwd-value\n")

        result = _run_probe(
            cwd=work_dir,
            env=_clean_env(PYTHONPATH=str(pkgroot)),
        )

        assert _markers(result)["MARKER_C"] == "cwd-value"

    def test_repo_root_takes_priority_over_cwd_search(self, tmp_path):
        """When both a repo-root .env and a cwd .env exist, step (b) — the
        repo-root .env — wins. This is the MCP-specific priority: an
        arbitrary host-chosen cwd must not shadow a real repo-root .env,
        unlike the CLI/web server (see
        test_env_loading.py::TestCliWebPreferCwdOverRepoRoot)."""
        pkgroot = tmp_path / "pkgroot"
        self._copy_package(pkgroot)
        (pkgroot / ".env").write_text("MARKER_B=repo-root-value\n")
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        (work_dir / ".env").write_text("MARKER_B=cwd-value\nMARKER_C=cwd-value\n")

        result = _run_probe(cwd=work_dir, env=_clean_env(PYTHONPATH=str(pkgroot)))

        markers = _markers(result)
        assert markers["MARKER_B"] == "repo-root-value"
        assert markers["MARKER_C"] is None
