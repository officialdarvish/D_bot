# syntax=docker/dockerfile:1
# Official multi-architecture Xray image, pinned to the existing 26.9.9 release.
ARG XRAY_IMAGE=ghcr.io/xtls/xray-core:26.9.9@sha256:45338c4df61fda061c47ce62aafda6c5d7d59cbdefc33f2e335d8b0c748b748a
ARG XRAY_SOURCE=image
FROM ${XRAY_IMAGE} AS xray-image

FROM node:20-bookworm-slim AS frontend-build
WORKDIR /frontend

ENV NEXT_TELEMETRY_DISABLED=1 \
    NPM_CONFIG_AUDIT=false \
    NPM_CONFIG_FUND=false \
    NPM_CONFIG_UPDATE_NOTIFIER=false \
    NPM_CONFIG_FETCH_RETRIES=5 \
    NPM_CONFIG_FETCH_RETRY_MINTIMEOUT=20000 \
    NPM_CONFIG_FETCH_RETRY_MAXTIMEOUT=120000 \
    NPM_CONFIG_FETCH_TIMEOUT=600000

COPY frontend/package*.json ./
RUN npm install -g npm@10.9.3 --no-audit --no-fund --registry=https://registry.npmjs.org
RUN npm ci --include=dev --no-audit --no-fund --registry=https://registry.npmjs.org \
    && test -x node_modules/.bin/next
COPY frontend ./
RUN npm run build

FROM python:3.11-slim AS runtime-base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates fonts-dejavu-core unzip \
    && rm -rf /var/lib/apt/lists/*

# Optional archive/local-file route; BuildKit skips it for the default image source.
FROM runtime-base AS xray-archive
ARG XRAY_VERSION=26.9.9
ARG TARGETARCH
COPY scripts/install-xray.sh /tmp/install-xray.sh
COPY build/xray/ /tmp/dbot-xray-local/
RUN --mount=type=cache,id=dbot-xray-archives,target=/var/cache/dbot-xray,sharing=locked \
    XRAY_VERSION="${XRAY_VERSION}" TARGETARCH="${TARGETARCH}" sh /tmp/install-xray.sh

FROM xray-${XRAY_SOURCE} AS xray-source

FROM runtime-base AS runtime
# Independent of Python requirements and application source: reuse Docker's Xray layers.
COPY --from=xray-source /usr/local/bin/xray /usr/local/bin/xray
RUN /usr/local/bin/xray version

COPY requirements.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY app ./app
COPY scripts ./scripts
# Stop incomplete source deployments before an image with broken bot buttons is released.
RUN python scripts/check_runtime_files.py
COPY --from=frontend-build /frontend/out ./frontend_out

CMD ["python", "-m", "app.main"]
