#!/bin/bash
set -e

# Skip migrations for celery workers — only the API should run them
if [ "$1" != "celery" ]; then
    echo "Running database migrations..."
    cd /app
    alembic upgrade head
    echo "Migrations complete."
fi

echo "Starting service..."
exec "$@"
