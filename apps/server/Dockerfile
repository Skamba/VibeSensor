FROM node:22-slim AS ui-build

WORKDIR /app/apps/ui

RUN apt-get update && apt-get install -y --no-install-recommends python3 && rm -rf /var/lib/apt/lists/*
ENV PYTHON=/usr/bin/python3

COPY apps/ui/package*.json ./
RUN npm ci

RUN mkdir -p /app/tools/config /app/apps/server/vibesensor/shared
# Copy the shared-code inputs early so UI rebuilds only invalidate when these contracts change.
COPY tools/config/sync_shared_contracts_to_ui.mjs /app/tools/config/sync_shared_contracts_to_ui.mjs
COPY tools/config/python_runtime.mjs /app/tools/config/python_runtime.mjs
COPY tools/config/generate_ui_shared_constants.py /app/tools/config/generate_ui_shared_constants.py
COPY apps/server/vibesensor/shared/locations.py /app/apps/server/vibesensor/shared/locations.py
COPY apps/ui/ ./
RUN npm run build

FROM python:3.13.5-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIBESENSOR_SERVE_STATIC=1

WORKDIR /app

COPY apps/server /app/apps/server
RUN rm -rf /app/apps/server/vibesensor/static && mkdir -p /app/apps/server/vibesensor/static
COPY --from=ui-build /app/apps/ui/dist/ /app/apps/server/vibesensor/static/

RUN python -m pip install --no-cache-dir /app/apps/server

EXPOSE 8000/tcp
EXPOSE 9000/udp
EXPOSE 9001/udp

STOPSIGNAL SIGINT
CMD ["vibesensor-server", "--config", "/app/apps/server/config.docker.yaml"]
