#!/usr/bin/env bash
# ==============================================================================
# Local CI/CD Pipeline & Pre-Commit Verification Runner
# Supports:
#   --quick (DEFAULT): Fast static checks (Mermaid, style, lint, mypy, configs, unit tests) [< 3s]
#   --full           : Full pipeline (Stages 1-6 + 100% coverage gate + 150 req/s contention gate) [~25s]
# ==============================================================================
set -euo pipefail

# Resolve script directory even if invoked through a symlink (e.g. .git/hooks/pre-commit)
SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do
    DIR="$(cd -P "$(dirname "$SOURCE")" >/dev/null 2>&1 && pwd)"
    SOURCE="$(readlink "$SOURCE")"
    [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"
done
SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" >/dev/null 2>&1 && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
MODULE_DIR="${REPO_ROOT}/03_routing_and_capacity"

# Default to --quick unless --full is explicitly specified
MODE="quick"
if [ "${1:-}" = "--full" ]; then
    MODE="full"
elif [ "${1:-}" = "--quick" ] || [ -z "${1:-}" ]; then
    MODE="quick"
else
    echo "Usage: $0 [--quick | --full]"
    echo "  --quick (default): Run style, lint, mypy, configs, mermaid, and unit tests (< 3s)"
    echo "  --full           : Run all quick checks + 100% coverage gate + live contention gate (~25s)"
    exit 1
fi

# Colors for terminal output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${BLUE}======================================================================${NC}"
echo -e "${BLUE}🚀 RUNNING LOCAL CI/CD GATE [MODE: ${MODE^^}]${NC}"
echo -e "${BLUE}======================================================================${NC}"

# 1. Resolve Python executable & tools
if [ -f "${MODULE_DIR}/.venv/bin/python" ]; then
    PYTHON_BIN="${MODULE_DIR}/.venv/bin/python"
    PYTEST_BIN="${MODULE_DIR}/.venv/bin/pytest"
    RUFF_BIN="${MODULE_DIR}/.venv/bin/ruff"
    MYPY_BIN="${MODULE_DIR}/.venv/bin/mypy"
else
    PYTHON_BIN="$(command -v python3)"
    PYTEST_BIN="$(command -v pytest)"
    RUFF_BIN="$(command -v ruff)"
    MYPY_BIN="$(command -v mypy)"
fi

# ------------------------------------------------------------------------------
# Stage 1: Mermaid Diagram Syntax & Render Validation
# ------------------------------------------------------------------------------
echo -e "\n${CYAN}▶ Stage 1: Mermaid Diagram Syntax & Render Validation${NC}"
"${PYTHON_BIN}" "${SCRIPT_DIR}/verify_mermaid.py" "${MODULE_DIR}"
echo -e "${GREEN}✅ Stage 1 Passed: All Mermaid diagrams valid.${NC}"

# Set working directory to REPO_ROOT (VS Code workspace root) so paths match workspace links
cd "${REPO_ROOT}"

# ------------------------------------------------------------------------------
# Stage 2: Code Style & Formatting Check (Ruff Format)
# ------------------------------------------------------------------------------
echo -e "\n${CYAN}▶ Stage 2: Code Style & Formatting Check (Ruff Format)${NC}"
"${RUFF_BIN}" format --check --config "${MODULE_DIR}/pyproject.toml" 03_routing_and_capacity/app 03_routing_and_capacity/services/worker
echo -e "${GREEN}✅ Stage 2 Passed: Code formatting adheres to PEP 8 standards.${NC}"

# ------------------------------------------------------------------------------
# Stage 3: Linting & Code Hygiene (Ruff Check)
# ------------------------------------------------------------------------------
echo -e "\n${CYAN}▶ Stage 3: Linting & Code Hygiene (Ruff Check)${NC}"
"${RUFF_BIN}" check --config "${MODULE_DIR}/pyproject.toml" 03_routing_and_capacity/app 03_routing_and_capacity/services/worker
echo -e "${GREEN}✅ Stage 3 Passed: Zero linter errors or warnings.${NC}"

# ------------------------------------------------------------------------------
# Stage 4: Static Type Checking (Mypy)
# ------------------------------------------------------------------------------
echo -e "\n${CYAN}▶ Stage 4: Static Type Checking (Mypy)${NC}"
"${MYPY_BIN}" --config-file "${MODULE_DIR}/pyproject.toml" 03_routing_and_capacity/app 03_routing_and_capacity/services/worker --ignore-missing-imports
echo -e "${GREEN}✅ Stage 4 Passed: Type checking verified with zero errors.${NC}"

# ------------------------------------------------------------------------------
# Stage 5: Configuration & Infrastructure Validation
# ------------------------------------------------------------------------------
echo -e "\n${CYAN}▶ Stage 5: Configuration & Infrastructure Validation${NC}"
# 5a. Docker Compose specification check
docker compose -f "${MODULE_DIR}/docker-compose.yml" config -q
echo -e "  • Docker Compose config: ${GREEN}Valid${NC}"

# 5b. Nginx configuration syntax check (if gateway container is running)
if docker ps --format '{{.Names}}' | grep -q "^payment_gateway$"; then
    docker exec payment_gateway nginx -t -q
    echo -e "  • Nginx Gateway config:  ${GREEN}Valid (tested in container)${NC}"
fi

# 5c. Settings / .env validation
PYTHONPATH="${MODULE_DIR}:${PYTHONPATH:-}" "${PYTHON_BIN}" -c "from app.config import get_settings; get_settings()"
echo -e "  • Pydantic Settings:     ${GREEN}Valid${NC}"
echo -e "${GREEN}✅ Stage 5 Passed: All configuration schemas verified.${NC}"

# ------------------------------------------------------------------------------
# ------------------------------------------------------------------------------
# Stage 6: Fast Unit Tests
# ------------------------------------------------------------------------------
echo -e "\n${CYAN}▶ Stage 6: Fast Unit Tests (In-Memory Isolation)${NC}"
cd "${MODULE_DIR}"
"${PYTEST_BIN}" -c pytest.ini tests/unit/ -q
cd "${REPO_ROOT}"
echo -e "${GREEN}✅ Stage 6 Passed: All unit tests succeeded.${NC}"

# ------------------------------------------------------------------------------
# If in --quick mode, finish early
# ------------------------------------------------------------------------------
if [ "${MODE}" = "quick" ]; then
    echo -e "\n${GREEN}======================================================================${NC}"
    echo -e "${GREEN}🎉 ALL QUICK CHECKS PASSED (< 3s)! Clean to commit.${NC}"
    echo -e "${YELLOW}💡 Tip: Run '$0 --full' before pushing to remote.${NC}"
    echo -e "${GREEN}======================================================================${NC}"
    exit 0
fi

# ------------------------------------------------------------------------------
# FULL MODE ONLY: Coverage Gate, Live Stack Health & Contention Gate
# ------------------------------------------------------------------------------
echo -e "\n${BLUE}--- Entering Full Verification Mode (Coverage & Contention Gates) ---${NC}"

# Stage 7: Pytest Suite with 100% Statement & Branch Coverage Gate
echo -e "\n${CYAN}▶ Stage 7: Full Pytest Suite (100% Statement & Branch Coverage Gate)${NC}"
cd "${MODULE_DIR}"
"${PYTEST_BIN}" -c pytest.ini tests --cov=app --cov=services/worker --cov-report=term-missing --cov-fail-under=100
cd "${REPO_ROOT}"
echo -e "${GREEN}✅ Stage 7 Passed: 100% statement and branch coverage verified.${NC}"

# Stage 8: Live Docker Compose Stack Readiness Check
echo -e "\n${CYAN}▶ Stage 8: Live Distributed Stack Readiness Check${NC}"
if curl -sf http://localhost:8010/health/ready &>/dev/null; then
    echo -e "${GREEN}✅ Gateway is healthy on http://localhost:8010/health/ready${NC}"
else
    echo -e "${YELLOW}⚠️ Gateway not responding on port 8010. Starting stack...${NC}"
    docker compose -f "${MODULE_DIR}/docker-compose.yml" up -d --scale api_instant=2 --scale api_batch=2
    echo "Waiting for gateway readiness..."
    timeout 45s bash -c "until curl -sf http://localhost:8010/health/ready; do sleep 2; done"
    echo -e "${GREEN}✅ All services healthy.${NC}"
fi

# Stage 9: Automated Contention & Capacity Regression Gate
echo -e "\n${CYAN}▶ Stage 9: Automated Contention & Capacity Regression Gate (150 req/s SLA)${NC}"
"${PYTHON_BIN}" "${MODULE_DIR}/scripts/ci_contention_gate.py" \
    --rate 150 \
    --duration 10 \
    --p99-threshold 100.0 \
    --baseline-p99 83.0 \
    --max-degradation 15.0 \
    --max-db-conns 26

echo -e "\n${GREEN}======================================================================${NC}"
echo -e "${GREEN}🎉 ALL FULL CI/CD GATES PASSED! Fully verified and ready to push.${NC}"
echo -e "${GREEN}======================================================================${NC}"
