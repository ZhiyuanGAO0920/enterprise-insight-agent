#!/bin/bash
# =============================================================================
# validate_env.sh — Pre-deployment environment validation
# =============================================================================
# Checks that .env exists and required values are not still template placeholders.
# Called automatically by deploy.sh; can also be run standalone.
#
# Usage:
#   bash scripts/validate_env.sh
# =============================================================================
set -e

ENV_FILE="${1:-.env}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

ERRORS=0
WARNINGS=0

check_not_placeholder() {
    local key="$1"
    local placeholder="$2"
    local message="$3"
    if grep -q "${key}=${placeholder}" "$ENV_FILE" 2>/dev/null; then
        echo -e "${RED}[ERROR]${NC} $message"
        echo "        Edit $ENV_FILE and change $key from '$placeholder'"
        ERRORS=$((ERRORS + 1))
    fi
}

check_not_empty() {
    local key="$1"
    local message="$2"
    local value
    value=$(grep "^${key}=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2-)
    if [ -z "$value" ]; then
        echo -e "${RED}[ERROR]${NC} $message"
        echo "        $key is empty or missing in $ENV_FILE"
        ERRORS=$((ERRORS + 1))
    fi
}

check_warning() {
    local key="$1"
    local value_to_check="$2"
    local message="$3"
    if grep -q "^${key}=${value_to_check}" "$ENV_FILE" 2>/dev/null; then
        echo -e "${YELLOW}[WARN]${NC} $message"
        WARNINGS=$((WARNINGS + 1))
    fi
}

echo "========================================"
echo " Validating $ENV_FILE ..."
echo "========================================"
echo ""

# 1. File existence
if [ ! -f "$ENV_FILE" ]; then
    echo -e "${RED}[ERROR]${NC} $ENV_FILE not found."
    echo "        Copy from template: cp .env.production.example .env"
    exit 1
fi
echo -e "${GREEN}[OK]${NC} $ENV_FILE exists"

# 2. Required: DEEPSEEK_API_KEY
check_not_empty "DEEPSEEK_API_KEY" "DEEPSEEK_API_KEY is required for LLM calls"
check_not_placeholder "DEEPSEEK_API_KEY" "sk-xxxxxxxxxxxxxxxx" \
    "DEEPSEEK_API_KEY is still the template placeholder"

# 3. Required: JWT_SECRET_KEY
check_not_empty "JWT_SECRET_KEY" "JWT_SECRET_KEY is required for token signing"
check_not_placeholder "JWT_SECRET_KEY" "change-me-to-random-64-chars" \
    "JWT_SECRET_KEY is still the template placeholder — this is a security risk!"

# 4. Required: POSTGRES_PASSWORD
check_not_empty "POSTGRES_PASSWORD" "POSTGRES_PASSWORD is required for database"
check_not_placeholder "POSTGRES_PASSWORD" "change-me-strong-password" \
    "POSTGRES_PASSWORD is still the template placeholder"

# 5. Warnings
check_warning "POSTGRES_PASSWORD" "admin123" \
    "POSTGRES_PASSWORD is a weak/common password. Consider a stronger one."
check_warning "CORS_ORIGINS" "*" \
    "CORS_ORIGINS is set to '*' — fine for dev, restrict in production."

echo ""
echo "========================================"
if [ $ERRORS -gt 0 ]; then
    echo -e " ${RED}Validation FAILED: $ERRORS error(s), $WARNINGS warning(s)${NC}"
    echo " Fix the errors above, then re-run."
    exit 1
else
    echo -e " ${GREEN}Validation PASSED${NC} ($WARNINGS warning(s))"
fi
echo "========================================"
