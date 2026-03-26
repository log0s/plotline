#!/bin/bash
set -e

echo "Running database migrations..."
cd /app
alembic upgrade head
echo "Migrations complete. Starting service..."
exec "$@"
