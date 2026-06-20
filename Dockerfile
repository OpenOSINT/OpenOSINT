# Multi-platform build — supports linux/amd64 and linux/arm64
FROM python:3.11-slim

ARG TARGETARCH

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY . .

RUN pip install --no-cache-dir -e ".[web]"

# Optional OSINT binaries available via pip
RUN pip install --no-cache-dir holehe sherlock-project sublist3r

ARG PHONEINFOGA_VERSION=v2.10.6
RUN apt-get update && apt-get install -y --no-install-recommends wget ca-certificates && \
    if [ "$TARGETARCH" = "arm64" ]; then \
        PHONEINFOGA_ARCH="arm64"; \
    else \
        PHONEINFOGA_ARCH="x86_64"; \
    fi && \
    wget -q https://github.com/sundowndev/phoneinfoga/releases/download/${PHONEINFOGA_VERSION}/phoneinfoga_Linux_${PHONEINFOGA_ARCH}.tar.gz -O /tmp/phoneinfoga.tar.gz && \
    tar xzf /tmp/phoneinfoga.tar.gz -C /usr/local/bin phoneinfoga && \
    rm /tmp/phoneinfoga.tar.gz && \
    apt-get purge -y wget && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/reports

RUN useradd -m -u 1000 openosint && chown -R openosint:openosint /app
USER openosint

EXPOSE 8080

CMD ["openosint", "web", "--host", "0.0.0.0", "--port", "8080", "--no-browser"]
