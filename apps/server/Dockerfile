FROM node:22.14-slim AS ui-build

WORKDIR /app/apps/ui

RUN apt-get update && apt-get install -y --no-install-recommends python3 && rm -rf /var/lib/apt/lists/*

COPY apps/ui/package*.json ./
RUN npm ci

RUN mkdir -p /app/tools/config /app/apps/server/vibesensor/shared
COPY tools/config/sync_shared_contracts_to_ui.mjs /app/tools/config/sync_shared_contracts_to_ui.mjs
COPY tools/config/generate_ui_shared_constants.py /app/tools/config/generate_ui_shared_constants.py
COPY apps/server/vibesensor/shared/locations.py /app/apps/server/vibesensor/shared/locations.py
COPY apps/server/vibesensor/shared/strength_fields.py /app/apps/server/vibesensor/shared/strength_fields.py
COPY apps/ui/ ./
RUN npm run build

FROM python:3.11.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIBESENSOR_SERVE_STATIC=1

WORKDIR /app

COPY apps/server/pyproject.toml /app/apps/server/pyproject.toml
COPY apps/server/README.md /app/apps/server/README.md
RUN python - <<'PY'
import subprocess
import sys
import tomllib
from pathlib import Path

pyproject = Path("/app/apps/server/pyproject.toml")
data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
dependencies = list(data["project"]["dependencies"])
dependencies.extend(data["project"].get("optional-dependencies", {}).get("esp", ()))
subprocess.check_call([sys.executable, "-m", "pip", "install", "--no-cache-dir", "--upgrade", "pip", *dependencies])
PY

COPY apps/server /app/apps/server
RUN rm -rf /app/apps/server/vibesensor/static && mkdir -p /app/apps/server/vibesensor/static
COPY --from=ui-build /app/apps/ui/dist/ /app/apps/server/vibesensor/static/

RUN pip install --no-cache-dir --no-deps /app/apps/server

EXPOSE 8000/tcp
EXPOSE 9000/udp
EXPOSE 9001/udp

STOPSIGNAL SIGINT
CMD ["vibesensor-server", "--config", "/app/apps/server/config.docker.yaml"]
