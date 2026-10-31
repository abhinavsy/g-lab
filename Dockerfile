                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                # Django backend (streaming/, telemetry/, dashboard/) — the REST/WebSocket
# control plane. Not the Jetson mock (see jetson_mock/Dockerfile — separate
# image, separate compose file) and not the Flutter app.
#
# Uses requirements.txt (not pyproject.toml — that one's uv/aiortc-flavored
# for local tooling; this image follows README.md's documented
# `pip install -r requirements.txt` setup) on a stable Python, not the
# 3.15 beta pinned in .python-version for local dev.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# libpq5: runtime lib psycopg2-binary's wheel links against.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh
ENTRYPOINT ["docker-entrypoint.sh"]

# WebSocket support (ws/app/, ws/jetson/) needs an ASGI server — plain
# `runserver` (WSGI) can't do it, per README.md. Use `daphne` in prod too,
# not just "for dev".
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "config.asgi:application"]
