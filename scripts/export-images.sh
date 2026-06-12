#!/bin/bash
# =============================================================================
# export-images.sh — Export Docker images for offline/air-gapped deployment
# =============================================================================
# Run this on a machine WITH internet access to pre-download all required
# Docker images. The resulting tar.gz can be copied to the air-gapped server
# and imported with scripts/import-images.sh.
#
# Usage:
#   bash scripts/export-images.sh
#   # → creates eia-v4-images.tar.gz (~2 GB)
# =============================================================================
set -e

IMAGES=(
    "pgvector/pgvector:pg16"
    "redis:7-alpine"
    "ollama/ollama:latest"
    "n8nio/n8n:latest"
)

OUTPUT="eia-v4-images.tar.gz"

echo "========================================"
echo " Exporting Docker images for offline deployment"
echo "========================================"
echo ""

for img in "${IMAGES[@]}"; do
    echo "Pulling ${img}..."
    docker pull "${img}"
done

echo ""
echo "Saving images to ${OUTPUT}..."
docker save "${IMAGES[@]}" | gzip > "${OUTPUT}"

echo ""
echo "========================================"
echo " Done: ${OUTPUT} ($(du -h "${OUTPUT}" | cut -f1))"
echo ""
echo " Copy this file to the target server, then run:"
echo "   bash scripts/import-images.sh"
echo "========================================"
