FROM node:22-slim AS ui-build

WORKDIR /app/ui

COPY ui/package*.json ./
RUN npm ci

COPY ui/ ./
RUN npm run typecheck && npm run build

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV VIBESENSOR_SERVE_STATIC=1

WORKDIR /app

COPY pi /app/pi
RUN rm -rf /app/pi/public && mkdir -p /app/pi/public
COPY --from=ui-build /app/ui/dist/ /app/pi/public/

RUN pip install --no-cache-dir /app/pi

EXPOSE 8000/tcp
EXPOSE 9000/udp
EXPOSE 9001/udp

CMD ["python", "-m", "vibesensor.app", "--config", "/app/pi/config.docker.yaml"]
