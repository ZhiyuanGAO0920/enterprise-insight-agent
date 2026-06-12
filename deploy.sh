#!/bin/bash
# =============================================================================
# deploy.sh — Enterprise Insight Agent V4 一键部署（Linux / macOS）
# =============================================================================
# Usage:
#   chmod +x deploy.sh && ./deploy.sh
#
# What it does:
#   1. Check Docker is installed
#   2. Create .env from template if missing
#   3. Validate .env (no placeholder values)
#   4. Check for pre-packaged BGE-M3 model
#   5. Check port availability
#   6. docker compose up -d
#   7. Wait for health check
#   8. Print success message with access URL and credentials
# =============================================================================
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE} Enterprise Insight Agent V4 — 一键部署${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# ---- 1. Check Docker ----
if ! command -v docker >/dev/null 2>&1; then
    echo -e "${RED}[ERROR]${NC} Docker is not installed."
    echo "  Install: https://docs.docker.com/engine/install/"
    exit 1
fi

# Detect docker compose (V2 plugin) vs docker-compose (V1 standalone)
if docker compose version >/dev/null 2>&1; then
    DOCKER_COMPOSE="docker compose"
else
    echo -e "${YELLOW}[WARN]${NC} 'docker compose' not found, trying 'docker-compose'..."
    if command -v docker-compose >/dev/null 2>&1; then
        DOCKER_COMPOSE="docker-compose"
    else
        echo -e "${RED}[ERROR]${NC} Neither 'docker compose' nor 'docker-compose' found."
        exit 1
    fi
fi
echo -e "${GREEN}[OK]${NC} Docker detected (using: ${DOCKER_COMPOSE})"

# ---- 2. Create .env if missing ----
if [ ! -f .env ]; then
    echo ""
    echo -e "${YELLOW}[INFO]${NC} No .env file found. Creating from template..."
    cp .env.production.example .env
    echo ""
    echo -e "${YELLOW}========================================${NC}"
    echo -e "${YELLOW} Please edit .env and fill in your values:${NC}"
    echo -e "${YELLOW}   DEEPSEEK_API_KEY   — your DeepSeek API key${NC}"
    echo -e "${YELLOW}   JWT_SECRET_KEY     — a random string (change from default!)${NC}"
    echo -e "${YELLOW}   POSTGRES_PASSWORD  — a strong database password${NC}"
    echo -e "${YELLOW}========================================${NC}"
    echo ""
    echo "After editing, re-run: ./deploy.sh"
    exit 0
fi
echo -e "${GREEN}[OK]${NC} .env file found"

# ---- 3. Validate .env ----
echo ""
echo "Validating .env configuration..."
bash scripts/validate_env.sh .env

# ---- 4. Check pre-packaged model ----
echo ""
if [ ! -f ollama-models/bge-m3.tar.gz ]; then
    echo -e "${YELLOW}========================================${NC}"
    echo -e "${YELLOW} Pre-packaged BGE-M3 model not found.${NC}"
    echo ""
    echo "  Option 1: Download from the V4 Release page"
    echo "  Option 2: Build locally:"
    echo "    docker run --rm -v ollama_temp:/root/.ollama ollama/ollama pull bge-m3:latest"
    echo "    docker run --rm -v ollama_temp:/root/.ollama -v \$(pwd)/ollama-models:/out alpine \\"
    echo "      tar -czf /out/bge-m3.tar.gz -C /root/.ollama ."
    echo "    docker volume rm ollama_temp"
    echo -e "${YELLOW}========================================${NC}"
    echo ""
    read -p "Continue without model? Ollama will download on first start (slow). [y/N] " answer
    if [ "$answer" != "y" ] && [ "$answer" != "Y" ]; then
        exit 1
    fi
else
    echo -e "${GREEN}[OK]${NC} BGE-M3 model package found ($(du -h ollama-models/bge-m3.tar.gz | cut -f1))"
fi

# ---- 5. Check port availability ----
echo ""
PORTS="${SERVER_PORT:-8002} ${POSTGRES_PORT:-5434} ${REDIS_PORT:-6381} ${OLLAMA_PORT:-11435} ${N8N_PORT:-5680}"
HAS_CONFLICT=0
for port in $PORTS; do
    if ss -tlnp 2>/dev/null | grep -q ":${port} " || netstat -tlnp 2>/dev/null | grep -q ":${port} "; then
        echo -e "${YELLOW}[WARN]${NC} Port ${port} is already in use!"
        HAS_CONFLICT=1
    fi
done
if [ $HAS_CONFLICT -eq 1 ]; then
    echo ""
    echo "  Some ports are already in use. Edit .env to change:"
    echo "  SERVER_PORT, POSTGRES_PORT, REDIS_PORT, OLLAMA_PORT, N8N_PORT"
    echo ""
    read -p "Continue anyway? [y/N] " answer
    if [ "$answer" != "y" ] && [ "$answer" != "Y" ]; then
        exit 1
    fi
else
    echo -e "${GREEN}[OK]${NC} All ports available"
fi

# ---- 6. Start services ----
echo ""
echo "Starting services..."
$DOCKER_COMPOSE -f docker-compose.prod.yml up -d

# ---- 7. Wait for health check ----
echo ""
echo "Waiting for application to be ready..."
SERVER_PORT="${SERVER_PORT:-8002}"
MAX_WAIT=60
for i in $(seq 1 $MAX_WAIT); do
    if curl -s "http://localhost:${SERVER_PORT}/health" > /dev/null 2>&1; then
        echo ""
        echo -e "${GREEN}========================================${NC}"
        echo -e "${GREEN}  Deploy successful!${NC}"
        echo ""
        echo -e "  Access URL:  ${BLUE}http://localhost:${SERVER_PORT}${NC}"
        echo -e "  Username:    ${BLUE}admin${NC}"
        echo -e "  Password:    ${BLUE}admin123${NC}"
        echo ""
        echo "  Next steps:"
        echo "  1. Log in at the URL above"
        echo "  2. Connect your business database: edit customer_schema.yaml"
        echo "  3. Run schema discovery: see 启动指南.md Step 9"
        echo ""
        echo "  Management:"
        echo "    Logs:   ${DOCKER_COMPOSE} -f docker-compose.prod.yml logs -f"
        echo "    Stop:   ${DOCKER_COMPOSE} -f docker-compose.prod.yml down"
        echo "    Backup: bash scripts/backup.sh"
        echo -e "${GREEN}========================================${NC}"
        exit 0
    fi
    printf "."
    sleep 2
done

echo ""
echo -e "${YELLOW} Startup is taking longer than expected.${NC}"
echo "  Check logs: ${DOCKER_COMPOSE} -f docker-compose.prod.yml logs"
echo "  The application should be available shortly at http://localhost:${SERVER_PORT}"
