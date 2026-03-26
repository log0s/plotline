FROM python:3.12-slim

# System dependencies (GDAL for rasterio/GeoAlchemy2, curl for healthchecks)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    libgdal-dev \
    libproj-dev \
    proj-bin \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (layer-cache friendly)
COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -e ".[dev]"

# Copy app source (overridden in dev by volume mount)
COPY . .

# Copy and set entrypoint for auto-migrations
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Make scripts directory available
ENV PYTHONPATH=/app

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
