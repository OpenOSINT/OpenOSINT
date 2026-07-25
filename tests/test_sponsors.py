"""Tests for the sponsors data system: loader, validator, and README renderer."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from openosint.sponsors import (
    REQUIRED_FIELDS,
    VALID_TIERS,
    SponsorsValidationError,
    get_by_tier,
    get_featured,
    load_sponsors,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_VALID_ENTRY = {
    "name": "Acme Corp",
    "tagline": "Fast, reliable data for OSINT",
    "url": "https://acme.example.com/?utm_source=openosint",
    "logo": "https://img.shields.io/badge/Acme-blue",
    "tier": "featured",
    "tool": "search_acme",
}

_VALID_INTEGRATION = {**_VALID_ENTRY, "tier": "integration", "name": "Beta Inc"}
_VALID_SUPPORTER = {**_VALID_ENTRY, "tier": "supporter", "name": "Gamma LLC"}

_RENDERER = Path(__file__).parent.parent / "scripts" / "render_sponsors.py"


def _write_sponsors(tmp_path: Path, data: object) -> Path:
    p = tmp_path / "sponsors.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# load_sponsors — happy path
# ---------------------------------------------------------------------------


def test_load_sponsors_valid_single(tmp_path):
    p = _write_sponsors(tmp_path, [_VALID_ENTRY])
    sponsors = load_sponsors(p)
    assert len(sponsors) == 1
    assert sponsors[0]["name"] == "Acme Corp"
    assert sponsors[0]["tier"] == "featured"


def test_load_sponsors_valid_all_tiers(tmp_path):
    p = _write_sponsors(tmp_path, [_VALID_ENTRY, _VALID_INTEGRATION, _VALID_SUPPORTER])
    sponsors = load_sponsors(p)
    assert len(sponsors) == 3
    tiers = {s["tier"] for s in sponsors}
    assert tiers == {"featured", "integration", "supporter"}


def test_load_sponsors_empty_list(tmp_path):
    p = _write_sponsors(tmp_path, [])
    assert load_sponsors(p) == []


# ---------------------------------------------------------------------------
# load_sponsors — validation errors
# ---------------------------------------------------------------------------


def test_missing_required_field_raises(tmp_path):
    bad = {k: v for k, v in _VALID_ENTRY.items() if k != "tagline"}
    p = _write_sponsors(tmp_path, [bad])
    with pytest.raises(SponsorsValidationError, match="tagline"):
        load_sponsors(p)


def test_unknown_tier_raises(tmp_path):
    bad = {**_VALID_ENTRY, "tier": "platinum"}
    p = _write_sponsors(tmp_path, [bad])
    with pytest.raises(SponsorsValidationError, match="platinum"):
        load_sponsors(p)


def test_empty_required_field_raises(tmp_path):
    bad = {**_VALID_ENTRY, "name": ""}
    p = _write_sponsors(tmp_path, [bad])
    with pytest.raises(SponsorsValidationError, match="name"):
        load_sponsors(p)


def test_non_array_root_raises(tmp_path):
    p = _write_sponsors(tmp_path, {"name": "solo"})
    with pytest.raises(SponsorsValidationError, match="JSON array"):
        load_sponsors(p)


def test_non_object_entry_raises(tmp_path):
    p = _write_sponsors(tmp_path, ["not-an-object"])
    with pytest.raises(SponsorsValidationError, match="entry 0"):
        load_sponsors(p)


def test_invalid_json_raises(tmp_path):
    p = tmp_path / "sponsors.json"
    p.write_text("{bad json", encoding="utf-8")
    with pytest.raises(SponsorsValidationError, match="not valid JSON"):
        load_sponsors(p)


def test_file_not_found_raises(tmp_path):
    p = tmp_path / "nonexistent.json"
    with pytest.raises(SponsorsValidationError, match="not found"):
        load_sponsors(p)


# ---------------------------------------------------------------------------
# get_by_tier / get_featured
# ---------------------------------------------------------------------------


def test_get_featured_returns_only_featured(tmp_path):
    p = _write_sponsors(tmp_path, [_VALID_ENTRY, _VALID_INTEGRATION, _VALID_SUPPORTER])
    featured = get_featured(p)
    assert len(featured) == 1
    assert featured[0]["name"] == "Acme Corp"


def test_get_by_tier_supporter(tmp_path):
    p = _write_sponsors(tmp_path, [_VALID_ENTRY, _VALID_SUPPORTER])
    supporters = get_by_tier("supporter", p)
    assert len(supporters) == 1
    assert supporters[0]["name"] == "Gamma LLC"


def test_get_by_tier_empty_when_none_match(tmp_path):
    p = _write_sponsors(tmp_path, [_VALID_ENTRY])
    assert get_by_tier("supporter", p) == []


# ---------------------------------------------------------------------------
# Renderer helpers
# ---------------------------------------------------------------------------


def _run_renderer(
    *extra_args: str,
    sponsors_data: object = None,
    readme_text: str = "# Test\n",
    tmp_path: Path,
) -> tuple[int, str, Path]:
    sponsors_path = tmp_path / "sponsors.json"
    sponsors_path.write_text(json.dumps(sponsors_data or [_VALID_ENTRY]), encoding="utf-8")
    readme_path = tmp_path / "README.md"
    readme_path.write_text(readme_text, encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(_RENDERER),
            "--readme",
            str(readme_path),
            "--sponsors",
            str(sponsors_path),
            *extra_args,
        ],
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout + result.stderr, readme_path


# ---------------------------------------------------------------------------
# Renderer — marker creation
# ---------------------------------------------------------------------------


def test_renderer_creates_markers_when_absent(tmp_path):
    code, _out, readme = _run_renderer(readme_text="# Title\n\nSome content.\n", tmp_path=tmp_path)
    assert code == 0
    content = readme.read_text()
    assert "<!-- SPONSORS:START -->" in content
    assert "<!-- SPONSORS:END -->" in content


def test_renderer_includes_featured_sponsor(tmp_path):
    code, _out, readme = _run_renderer(tmp_path=tmp_path)
    assert code == 0
    content = readme.read_text()
    assert "Acme Corp" in content
    assert "Featured Integrations" in content


# ---------------------------------------------------------------------------
# Renderer — idempotency
# ---------------------------------------------------------------------------


def test_renderer_idempotent(tmp_path):
    _run_renderer(tmp_path=tmp_path)
    readme = tmp_path / "README.md"
    content_after_first = readme.read_text()

    sponsors_path = tmp_path / "sponsors.json"
    result = subprocess.run(
        [sys.executable, str(_RENDERER), "--readme", str(readme), "--sponsors", str(sponsors_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert readme.read_text() == content_after_first


# ---------------------------------------------------------------------------
# Renderer — marker replacement
# ---------------------------------------------------------------------------


def test_renderer_replaces_existing_block(tmp_path):
    readme_with_markers = textwrap.dedent("""\
        # Title

        <!-- SPONSORS:START -->
        ### OLD CONTENT
        <!-- SPONSORS:END -->

        ## After
    """)
    code, _out, readme = _run_renderer(readme_text=readme_with_markers, tmp_path=tmp_path)
    assert code == 0
    content = readme.read_text()
    assert "OLD CONTENT" not in content
    assert "Acme Corp" in content
    assert "# Title" in content
    assert "## After" in content


# ---------------------------------------------------------------------------
# Renderer — --check mode
# ---------------------------------------------------------------------------


def test_renderer_check_mode_detects_mismatch(tmp_path):
    readme_with_old = textwrap.dedent("""\
        # Title
        <!-- SPONSORS:START -->
        old stuff
        <!-- SPONSORS:END -->
    """)
    code, out, _readme = _run_renderer("--check", readme_text=readme_with_old, tmp_path=tmp_path)
    assert code == 1
    assert "out of sync" in out


def test_renderer_check_mode_passes_when_synced(tmp_path):
    _run_renderer(tmp_path=tmp_path)
    readme = tmp_path / "README.md"
    sponsors_path = tmp_path / "sponsors.json"
    result = subprocess.run(
        [
            sys.executable,
            str(_RENDERER),
            "--check",
            "--readme",
            str(readme),
            "--sponsors",
            str(sponsors_path),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "up to date" in result.stdout + result.stderr


# ---------------------------------------------------------------------------
# Renderer — bad input
# ---------------------------------------------------------------------------


def test_renderer_fails_on_bad_sponsors_json(tmp_path):
    sponsors_path = tmp_path / "sponsors.json"
    sponsors_path.write_text("[{}]", encoding="utf-8")
    readme_path = tmp_path / "README.md"
    readme_path.write_text("# Title\n", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(_RENDERER),
            "--readme",
            str(readme_path),
            "--sponsors",
            str(sponsors_path),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0


# ---------------------------------------------------------------------------
# Renderer — all tiers rendered
# ---------------------------------------------------------------------------


def test_renderer_all_tiers(tmp_path):
    data = [_VALID_ENTRY, _VALID_INTEGRATION, _VALID_SUPPORTER]
    code, _out, readme = _run_renderer(sponsors_data=data, tmp_path=tmp_path)
    assert code == 0
    content = readme.read_text()
    assert "Featured Integrations" in content
    assert "Integrations" in content
    assert "Supporters" in content
    assert "Acme Corp" in content
    assert "Beta Inc" in content
    assert "Gamma LLC" in content


def test_renderer_includes_integration_doc_link(tmp_path):
    entry = {**_VALID_ENTRY, "integration_doc": "docs/integrations/acme.md"}
    code, _out, readme = _run_renderer(sponsors_data=[entry], tmp_path=tmp_path)
    assert code == 0
    content = readme.read_text()
    assert "[Integration guide](docs/integrations/acme.md)" in content


def test_renderer_omits_integration_doc_link_when_absent(tmp_path):
    code, _out, readme = _run_renderer(tmp_path=tmp_path)
    assert code == 0
    assert "Integration guide" not in readme.read_text()


# ---------------------------------------------------------------------------
# Real sponsors.json smoke test
# ---------------------------------------------------------------------------


def test_real_sponsors_json_is_valid():
    """Ensure the committed sponsors.json always passes validation."""
    real_path = Path(__file__).parent.parent / "sponsors.json"
    assert real_path.exists(), "sponsors.json not found at repo root"
    sponsors = load_sponsors(real_path)
    assert isinstance(sponsors, list)
    for s in sponsors:
        assert s["tier"] in VALID_TIERS
        for field in REQUIRED_FIELDS:
            assert field in s
            assert s[field].strip()
