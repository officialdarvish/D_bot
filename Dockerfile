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
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY --from=frontend-build /frontend/out ./frontend_out

CMD ["python", "-m", "app.main"]
