#!/bin/sh
# Runs once per container start, before handing off to CMD (daphne by
# default — see Dockerfile). Applies migrations so `docker compose up`
# alone is enough to get a working backend; skip with SKIP_MIGRATE=true if
# you'd rather run `manage.py migrate` yourself (e.g. against a shared DB
# multiple backend replicas point at).
set -e

if [ "${SKIP_MIGRATE:-false}" != "true" ]; then
    echo "docker-entrypoint: applying migrations..."
    python manage.py migrate --noinput
fi

exec "$@"
