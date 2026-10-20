FROM python:3.11-slim

WORKDIR /app

# libicu-dev + a compiler are needed once, to build PyICU (required by the
# graph view's followthemoney dependency); the compiler is purged afterwards.
RUN apt-get update && apt-get install -y --no-install-recommends \
    git build-essential pkg-config libicu-dev \
    && rm -rf /var/lib/apt/lists/*

COPY . .

# Editable on purpose: the docs mount and static files resolve relative to the
# package root. Keys saved from the UI go to $OPENOSINT_HOME/config.env, in the volume.
RUN pip install --no-cache-dir -e ".[graph]" \
    && apt-get purge -y --auto-remove build-essential pkg-config

# Optional OSINT binaries available via pip
RUN pip install --no-cache-dir holehe sherlock-project sublist3r

RUN mkdir -p /app/reports /data

# graph.db and session history live here; mount a volume to persist them.
ENV OPENOSINT_HOME=/data
VOLUME /data

EXPOSE 8080

# --allow-remote is required for a non-loopback bind (GHSA-cqr4-hcfp-m6m4) —
# safe here because the container network boundary is what's actually
# exposed; publish the port only to trusted networks.
# /app/.env stays a symlink into the data volume so a /data/.env from an older
# release keeps loading (and is copied to /data/config.env once). It dangles until
# such a file exists, so the "Loaded .env" line only appears once there really is one.
# Saving keys from the browser needs OPENOSINT_SETUP_TOKEN here: the browser reaches
# the container over the Docker bridge, not loopback.
CMD ["sh", "-c", "ln -sf /data/.env /app/.env && exec openosint web --host 0.0.0.0 --port 8080 --no-browser --allow-remote"]
