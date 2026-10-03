FROM node:26-slim AS ui-build

WORKDIR /app/apps/ui

COPY apps/ui/package*.json ./
RUN npm ci

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
