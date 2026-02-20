FROM node:22-slim AS ui-build

WORKDIR /app/apps/ui

COPY apps/ui/package*.json ./
RUN npm ci

RUN mkdir -p /app/tools/config
COPY tools/config/sync_shared_contracts_to_ui.mjs /app/tools/config/sync_shared_contracts_to_ui.mjs
COPY libs/ /app/libs/
COPY apps/ui/ ./
RUN npm run typecheck && npm run build

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV VIBESENSOR_SERVE_STATIC=1

WORKDIR /app

COPY apps/server /app/apps/server
COPY apps/simulator /app/apps/simulator
COPY tools/config /app/tools/config
COPY libs /app/libs
RUN rm -rf /app/apps/server/public && mkdir -p /app/apps/server/public
COPY --from=ui-build /app/apps/ui/dist/ /app/apps/server/public/

RUN pip install --no-cache-dir -e /app/apps/server

EXPOSE 8000/tcp
EXPOSE 9000/udp
EXPOSE 9001/udp

CMD ["vibesensor-server", "--config", "/app/apps/server/config.docker.yaml"]
