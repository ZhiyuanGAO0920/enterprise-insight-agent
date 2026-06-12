#!/bin/bash
# =============================================================================
# docker-entrypoint.sh — V4 Container Startup Script
# =============================================================================
# Runs at container start before the application.
# Handles: Docker Secrets → wait-for-deps → migrations → seed data → start app
#
# ENTRYPOINT ["/app/docker-entrypoint.sh"]
# CMD        ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
# =============================================================================
set -e

# ---- Docker Secrets compatibility ----
# When Docker Secrets are used (docker-compose.prod.yml), sensitive values
# are mounted as files under /run/secrets/ rather than environment variables.
# We read them here so downstream tools (pg_isready, psql, alembic, uvicorn)
# can use the standard environment variable names.
if [ -f /run/secrets/postgres_password ]; then
    export POSTGRES_PASSWORD=$(cat /run/secrets/postgres_password)
fi
if [ -f /run/secrets/deepseek_api_key ]; then
    export DEEPSEEK_API_KEY=$(cat /run/secrets/deepseek_api_key)
fi
if [ -f /run/secrets/jwt_secret_key ]; then
    export JWT_SECRET_KEY=$(cat /run/secrets/jwt_secret_key)
fi

# ---- Wait for PostgreSQL ----
echo "[entrypoint] Waiting for PostgreSQL (${POSTGRES_USER}@postgres/${POSTGRES_DB})..."
until PGPASSWORD="${POSTGRES_PASSWORD}" pg_isready -h postgres -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" 2>/dev/null; do
    sleep 2
done
echo "[entrypoint] PostgreSQL ready"

# ---- Wait for Redis ----
echo "[entrypoint] Waiting for Redis (${REDIS_URL})..."
until python -c "import redis; r=redis.from_url('${REDIS_URL}'); r.ping()" 2>/dev/null; do
    sleep 2
done
echo "[entrypoint] Redis ready"

# ---- Run database migrations ----
echo "[entrypoint] Running database migrations..."
alembic upgrade head
echo "[entrypoint] Migrations complete"

# ---- Seed data (first run only) ----
TENANT_COUNT=$(PGPASSWORD="${POSTGRES_PASSWORD}" psql -h postgres -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -tAc "SELECT COUNT(*) FROM tenants" 2>/dev/null || echo "0")
if [ "$TENANT_COUNT" = "0" ]; then
    echo "[entrypoint] First run detected — seeding initial data..."
    python /app/scripts/seed_data.py
    echo "[entrypoint] Seed data complete"
else
    echo "[entrypoint] Existing data found (${TENANT_COUNT} tenant(s)), skipping seed"
fi

# ---- Start application ----
echo "[entrypoint] Starting application..."
exec "$@"
