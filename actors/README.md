# OpenOSINT Apify Actors

One folder per Actor (`username-recon/`, `domain-recon/`, `news-monitor/`), each following the standard Apify Python Actor layout (`.actor/`, `src/`, `requirements.txt`, `Dockerfile`, `README.md`, `PRICING.md`, `tests/`).

Each Actor's `requirements.txt` pins `openosint>=2.29.0` — a version that isn't published to PyPI yet. Until it is, `apify run` works locally (it uses this repo's own editable install), but a real `docker build` of `.actor/Dockerfile` will fail trying to fetch `openosint` from PyPI.

## Testing the Docker image before openosint is published

```bash
./actors/build-local.sh <actor-name>   # e.g. ./actors/build-local.sh username-recon
```

This builds a wheel from the current repo state (via `uv build`, falling back to `pip wheel`) into that Actor's `local-wheels/` directory, then builds the Actor's real `.actor/Dockerfile`. The Dockerfile installs that wheel and drops the `openosint` line from `requirements.txt` for that build only — the real Apify Cloud build never sees this (the `local-wheels/` directory is committed empty, via `.gitkeep`, and the actual wheel file is gitignored).

Once `openosint>=2.29.0` is actually on PyPI, this script (and the Dockerfile's local-wheel branch) can be deleted.
