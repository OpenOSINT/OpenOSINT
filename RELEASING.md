# Releasing

1. **Bump the version** (the docs-consistency test fails if these drift):
   - `pyproject.toml` (`[project] version`)
   - `.mcp/server.json` (`version` and `packages[0].version`)
   - `README.md` footer (`*OpenOSINT vX.Y.Z — Month YYYY*`, near the end)
1a. **Rebuild the site**: `python scripts/build_site.py`. The docs pages show the version from `pyproject.toml`, so `scripts/check_site.py` (and CI) fails until you do. Refresh `stars` in `site/data/site.yaml` if you want the home page count current.
   - Changed `docs/favicon.svg`? Run `python scripts/render_favicons.py` (needs Pillow and Chrome) to regenerate the ICO and PNG icons.
2. **CHANGELOG.md**: rename `[Unreleased]` to `[X.Y.Z] — YYYY-MM-DD` and open a fresh `[Unreleased]`.
3. **Refresh the lock**: `uv lock`, commit it. CI runs `uv lock --check`; the Heroku build runs `uv sync --locked`, so a stale lock breaks the demo deploy.
4. **Check locally**: `pytest tests -q` and `ruff check openosint tests --extend-ignore I001`. Merge to `main` once CI is green.
5. **Tag**: `git tag vX.Y.Z && git push origin vX.Y.Z`. The Release workflow checks the tag against `pyproject.toml` and publishes to PyPI.
6. **PyPI check**: `pip index versions openosint` lists X.Y.Z, then `uvx openosint@X.Y.Z web` starts from a clean directory.
7. **Deploy the demo** (manual): `git push heroku-demo main:main`.
8. **Health check**: `curl -fsS https://demo.openosint.tech/api/health` returns `"status":"ok"` and `"version":"X.Y.Z"`. If it fails, `heroku logs --tail -a openosint-demo`.

## One-time demo setup

The demo app (`openosint-demo`) needs `OPENOSINT_ALLOWED_HOSTS` set, because its `--allow-remote` bind only checks the `Host` header when it is set: `heroku config:set OPENOSINT_ALLOWED_HOSTS=demo.openosint.tech,openosint-demo-8f67039da343.herokuapp.com -a openosint-demo` (already done; re-run if the app is recreated or the domain changes).
