#!/bin/bash
# =============================================================================
# backup.sh — PostgreSQL database backup
# =============================================================================
# Creates a compressed SQL dump of the system database.
# Recommended: run daily via cron.
#
# Usage:
#   bash scripts/backup.sh
#
# Cron example (daily at 2 AM):
#   0 2 * * * /opt/eia/scripts/backup.sh >> /opt/eia/backups/backup.log 2>&1
# =============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="${PROJECT_DIR}/backups"
RETENTION_DAYS=30

# Load .env if present
if [ -f "${PROJECT_DIR}/.env" ]; then
    set -a
    source "${PROJECT_DIR}/.env"
    set +a
fi

mkdir -p "${BACKUP_DIR}"

POSTGRES_USER="${POSTGRES_USER:-admin}"
POSTGRES_DB="${POSTGRES_DB:-enterprise_db}"
CONTAINER="${POSTGRES_CONTAINER:-eia-postgres-v4-prod}"

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/backup-${TIMESTAMP}.sql.gz"

echo "[backup] $(date) — Starting backup of ${POSTGRES_DB}..."
docker exec "${CONTAINER}" pg_dump -U "${POSTGRES_USER}" "${POSTGRES_DB}" | gzip > "${BACKUP_FILE}"

echo "[backup] Backup created: ${BACKUP_FILE} ($(du -h "${BACKUP_FILE}" | cut -f1))"

# Clean up old backups
DELETED=$(find "${BACKUP_DIR}" -name "backup-*.sql.gz" -mtime +${RETENTION_DAYS} -delete -print | wc -l)
if [ "${DELETED}" -gt 0 ]; then
    echo "[backup] Cleaned up ${DELETED} old backup(s) older than ${RETENTION_DAYS} days"
fi

echo "[backup] Done."
