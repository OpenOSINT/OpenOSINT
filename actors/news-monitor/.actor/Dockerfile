FROM apify/actor-python:3.13

COPY requirements.txt ./

# Optional local-only override: if ../build-local.sh has dropped a wheel here,
# install it and drop the `openosint` line from requirements.txt (its pinned
# version isn't published yet, so pip would otherwise try to "upgrade" past
# the local wheel and hit PyPI anyway). Harmless on the real Apify Cloud
# build, where this directory is always empty (just a committed .gitkeep)
# and the `ls` check below is a no-op.
COPY local-wheels/ /tmp/local-wheels/
RUN if ls /tmp/local-wheels/*.whl >/dev/null 2>&1; then \
        pip install --no-cache-dir /tmp/local-wheels/*.whl && \
        grep -v '^openosint' requirements.txt > requirements.txt.tmp && \
        mv requirements.txt.tmp requirements.txt; \
    fi

RUN echo "Python version:" \
    && python --version \
    && echo "Installing dependencies:" \
    && pip install -U pip setuptools wheel \
    && pip install --no-cache-dir -r requirements.txt \
    && echo "All installed dependencies:" \
    && pip freeze

COPY . ./

CMD ["python", "-m", "src"]
