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

FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates fonts-dejavu-core unzip \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

# Local Xray core is used only when Admin Web > Connection selects a V2 link.
# Pin the release so deployments are reproducible and support amd64/arm64 builds.
ARG XRAY_VERSION=26.9.9
ARG TARGETARCH
RUN set -eux; \
    arch="${TARGETARCH:-$(dpkg --print-architecture)}"; \
    case "$arch" in \
      amd64) xray_arch="64" ;; \
      arm64) xray_arch="arm64-v8a" ;; \
      arm) xray_arch="arm32-v7a" ;; \
      *) echo "Unsupported architecture for Xray: $arch" >&2; exit 1 ;; \
    esac; \
    curl -fL --retry 4 --connect-timeout 20 \
      "https://github.com/XTLS/Xray-core/releases/download/v${XRAY_VERSION}/Xray-linux-${xray_arch}.zip" \
      -o /tmp/xray.zip; \
    unzip -j /tmp/xray.zip xray -d /usr/local/bin; \
    chmod 0755 /usr/local/bin/xray; \
    rm -f /tmp/xray.zip; \
    /usr/local/bin/xray version

COPY app ./app
COPY scripts ./scripts
COPY --from=frontend-build /frontend/out ./frontend_out

CMD ["python", "-m", "app.main"]
