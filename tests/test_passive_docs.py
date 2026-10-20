"""Docs guards for passive mode: the README noise table is generated from tool_policy
and the absolute hallucination claims stay out of the repo."""

from __future__ import annotations

import pytest

from openosint import tool_policy as tp

# ---------------------------------------------------------------------------
# Docs: the README table can't drift from the code, and overclaims stay out
# ---------------------------------------------------------------------------


def _repo_text_files():
    import subprocess
    from pathlib import Path

    root = Path(__file__).parent.parent
    out = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True).stdout
    for rel in out.splitlines():
        if rel.endswith((".md", ".html", ".py", ".txt")) and rel != "CHANGELOG.md" and not rel.startswith(("tests/", "legal/", "marketing/")):
            yield rel, (root / rel).read_text(encoding="utf-8", errors="ignore")


def test_readme_noise_table_is_generated_from_tool_policy():
    from pathlib import Path

    readme = (Path(__file__).parent.parent / "README.md").read_text(encoding="utf-8")
    block = readme.split("<!-- NOISE-TABLE:START", 1)[1].split("-->", 1)[1].split("<!-- NOISE-TABLE:END", 1)[0]
    assert block.strip() == tp.markdown_table().strip(), "run `python -m openosint.tool_policy` and paste into README"


@pytest.mark.parametrize(
    "phrase",
    ["structurally impossible", "cannot be hallucinated", "prevents fabrication", "cannot generate OSINT findings"],
)
def test_no_absolute_hallucination_claims_in_repo(phrase):
    offenders = [rel for rel, text in _repo_text_files() if phrase.lower() in text.lower()]
    assert not offenders, f"overclaiming copy {phrase!r} in {offenders}"
