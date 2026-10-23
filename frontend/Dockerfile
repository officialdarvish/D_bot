FROM node:20-bookworm-slim AS build
WORKDIR /app

ENV NEXT_TELEMETRY_DISABLED=1 \
    NPM_CONFIG_AUDIT=false \
    NPM_CONFIG_FUND=false \
    NPM_CONFIG_UPDATE_NOTIFIER=false \
    NPM_CONFIG_FETCH_RETRIES=5 \
    NPM_CONFIG_FETCH_RETRY_MINTIMEOUT=20000 \
    NPM_CONFIG_FETCH_RETRY_MAXTIMEOUT=120000 \
    NPM_CONFIG_FETCH_TIMEOUT=600000

COPY package*.json ./
RUN npm install -g npm@10.9.3 --no-audit --no-fund --registry=https://registry.npmjs.org
RUN npm ci --include=dev --no-audit --no-fund --registry=https://registry.npmjs.org
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/out /usr/share/nginx/html
COPY nginx.default.conf /etc/nginx/conf.d/default.conf
EXPOSE 3000
CMD ["nginx", "-g", "daemon off;"]
