# =============================================================================
# =============================================================================
# Enterprise Insight Agent V4 — Multi-stage Dockerfile
# =============================================================================
# Stages:
#   builder      — compile-time deps (gcc, libpq-dev), builds wheels
#   development  — hot-reload, all deps including dev tools
#   production   — minimal runtime image, no dev deps
#
# Build:
#   docker build --target development -t eia-v4:dev .
#   docker build --target production  -t eia-v4:prod .
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1: Builder — install build dependencies & compile wheels
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy only dependency declarations to leverage Docker caching
COPY pyproject.toml .

# Install ALL deps (runtime + dev) to ensure everything is built
RUN pip install --no-cache-dir -e ".[dev]"

# ---------------------------------------------------------------------------
# Stage 2: Development — full environment with hot-reload
# ---------------------------------------------------------------------------
FROM builder AS development

WORKDIR /app

# Copy application code (mounted as volume in dev, but baked for fallback)
COPY app/ ./app/
COPY prompts/ ./prompts/
COPY alembic/ ./alembic/
COPY alembic.ini .
COPY customer_schema.yaml .
COPY .env.example .

RUN mkdir -p /app/app/api/static

EXPOSE 8000

CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ---------------------------------------------------------------------------
# Stage 3: Production — minimal runtime image
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS production

WORKDIR /app

# Runtime system deps:
#   libpq5, postgresql-client — PostgreSQL client tools (pg_isready/psql)
#   libpango, libcairo, etc. — WeasyPrint PDF rendering (HTML/CSS → PDF)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 postgresql-client \
    libpango-1.0-0 libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 libcairo2 libffi8 \
    && rm -rf /var/lib/apt/lists/*

# Copy pyproject.toml and install runtime + PDF dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[pdf]" && pip uninstall -y setuptools pip

# Copy application code
COPY app/ ./app/
COPY prompts/ ./prompts/
COPY alembic/ ./alembic/
COPY alembic.ini .
COPY customer_schema.yaml .

# Copy deployment scripts (before USER switch so we can chmod/chown)
COPY docker-entrypoint.sh /app/
RUN chmod +x /app/docker-entrypoint.sh
COPY scripts/ /app/scripts/

RUN mkdir -p /app/app/api/static /app/backups

# Create non-root user and transfer ownership
RUN useradd --create-home --shell /bin/bash appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
