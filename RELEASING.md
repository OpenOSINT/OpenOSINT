# Releasing

1. **Bump the version** (the docs-consistency test fails if these drift):
   - `pyproject.toml` (`[project] version`)
   - `.claude-plugin/plugin.json` (`version`) and the `openosint==X.Y.Z` pin in `skills/*/SKILL.md`, `skills/osint/references/*.md` and `.mcp.json`; `tests/test_agent_skill.py` fails if either differs from `pyproject.toml`
   - `.mcp/server.json` (`version` and `packages[0].version`)
   - `README.md` image paths: PyPI cannot resolve relative paths, so before the release switch `docs/assets/logo.svg`, `docs/assets/demo-chat.gif` and `assets/demo/skill-demo.gif` to absolute `https://raw.githubusercontent.com/OpenOSINT/OpenOSINT/main/...` URLs.
1a. **Rebuild the site**: `python scripts/build_site.py`. The docs pages show the version from `pyproject.toml`, so `scripts/check_site.py` (and CI) fails until you do. Refresh `stars` in `site/data/site.yaml` if you want the home page count current.
   - Changed `docs/favicon.svg`? Run `python scripts/render_favicons.py` (needs Pillow and Chrome) to regenerate the ICO and PNG icons.
2. **CHANGELOG.md**: rename `[Unreleased]` to `[X.Y.Z] — YYYY-MM-DD` and open a fresh `[Unreleased]`.
3. **Refresh the lock**: `uv lock`, commit it. CI runs `uv lock --check`, so a stale lock fails it.
4. **Check locally**: `pytest tests -q` and `ruff check openosint tests --extend-ignore I001`. Merge to `main` once CI is green.
5. **Tag**: `git tag vX.Y.Z && git push origin vX.Y.Z`. The Release workflow checks the tag against `pyproject.toml` and publishes to PyPI.
6. **PyPI check**: `pip index versions openosint` lists X.Y.Z, then `uvx openosint@X.Y.Z web` starts from a clean directory.
