#!/usr/bin/env bash
# Build an Actor's Docker image locally, using the in-repo `openosint`
# package instead of the PyPI release — needed until openosint>=2.29.0 is
# actually published (the Actors' requirements.txt already pin that version).
#
# Usage: ./actors/build-local.sh <actor-name>
#   e.g. ./actors/build-local.sh username-recon
#
# This never touches the real `.actor/Dockerfile` build path used by
# `apify push` / the Apify Cloud build: it builds from `.actor/Dockerfile.local`
# instead, which drops a wheel into that actor's local-wheels/ directory
# (gitignored, empty otherwise) and installs it if present.
set -euo pipefail

ACTOR_NAME="${1:?Usage: $0 <actor-name>, e.g. $0 username-recon}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACTOR_DIR="$REPO_ROOT/actors/$ACTOR_NAME"
WHEELS_DIR="$ACTOR_DIR/local-wheels"

if [ ! -d "$ACTOR_DIR" ]; then
  echo "No such actor: $ACTOR_NAME (looked in $ACTOR_DIR)" >&2
  exit 1
fi

echo "==> Building openosint wheel from $REPO_ROOT"
rm -f "$WHEELS_DIR"/*.whl
if command -v uv >/dev/null 2>&1; then
  uv build --wheel --out-dir "$WHEELS_DIR" "$REPO_ROOT"
else
  python3 -m pip wheel "$REPO_ROOT" --no-deps -w "$WHEELS_DIR"
fi

echo "==> Building Docker image for $ACTOR_NAME"
docker build -f "$ACTOR_DIR/.actor/Dockerfile.local" -t "openosint-$ACTOR_NAME-local" "$ACTOR_DIR"

echo "==> Done. Run it with, e.g.:"
echo "    docker run --rm -e APIFY_LOCAL_STORAGE_DIR=/tmp/storage openosint-$ACTOR_NAME-local"
