FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pi /app/pi

RUN pip install --no-cache-dir -e /app/pi

EXPOSE 8000/tcp
EXPOSE 9000/udp
EXPOSE 9001/udp

CMD ["python", "-m", "vibesensor.app", "--config", "/app/pi/config.docker.yaml"]
