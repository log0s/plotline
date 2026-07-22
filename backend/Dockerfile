FROM python:3.12-slim

# System dependencies (gcc + libc/libpq headers for psycopg2, curl for healthchecks)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libc6-dev \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv

WORKDIR /app

# Install locked Python dependencies first (layer-cache friendly)
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --extra dev --no-emit-project -o /tmp/requirements.txt \
    && uv pip install --system --no-cache -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# Copy app source (overridden in dev by volume mount)
COPY . .
RUN uv pip install --system --no-cache --no-deps -e .

# Copy and set entrypoint for auto-migrations
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Make scripts directory available
ENV PYTHONPATH=/app

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
