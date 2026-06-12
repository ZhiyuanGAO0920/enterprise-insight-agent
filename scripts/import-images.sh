#!/bin/bash
# =============================================================================
# import-images.sh — Load pre-exported Docker images on air-gapped server
# =============================================================================
# Run this on the target server where docker compose will be deployed.
# Requires eia-v4-images.tar.gz (created by scripts/export-images.sh) in the
# project root.
#
# Usage:
#   bash scripts/import-images.sh
# =============================================================================
set -e

ARCHIVE="eia-v4-images.tar.gz"

if [ ! -f "${ARCHIVE}" ]; then
    echo "ERROR: ${ARCHIVE} not found."
    echo "       Copy it from a machine with internet access (use scripts/export-images.sh)."
    exit 1
fi

echo "========================================"
echo " Importing Docker images from ${ARCHIVE}..."
echo " ($(du -h "${ARCHIVE}" | cut -f1))"
echo "========================================"

gunzip -c "${ARCHIVE}" | docker load

echo ""
echo " Done. Images imported successfully."
echo " You can now run: ./deploy.sh"
