#!/usr/bin/env bash
# ==============================================================================
# Local CI/CD Pipeline & Pre-Commit Verification Runner
# Mirrors .github/workflows/capacity_gate.yml locally prior to commit/push
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
MODULE_DIR="${REPO_ROOT}/03_routing_and_capacity"

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}======================================================================${NC}"
echo -e "${BLUE}🚀 RUNNING LOCAL CI/CD PRE-COMMIT VERIFICATION GATE${NC}"
echo -e "${BLUE}======================================================================${NC}"

# 1. Resolve Python executable (prefer module virtualenv)
if [ -f "${MODULE_DIR}/.venv/bin/python" ]; then
    PYTHON_BIN="${MODULE_DIR}/.venv/bin/python"
    PYTEST_BIN="${MODULE_DIR}/.venv/bin/pytest"
elif command -v python3 &>/dev/null; then
    PYTHON_BIN="$(command -v python3)"
    PYTEST_BIN="$(command -v pytest)"
else
    echo -e "${RED}❌ Error: Python 3 not found.${NC}"
    exit 1
fi

# 2. Stage 1: Pre-Commit Mermaid Diagram Syntax & Render Validation
echo -e "\n${YELLOW}▶ Stage 1: Mermaid Diagram Syntax & Render Validation${NC}"
"${PYTHON_BIN}" "${SCRIPT_DIR}/verify_mermaid.py" "${MODULE_DIR}"
echo -e "${GREEN}✅ Stage 1 Passed: All Mermaid diagrams valid.${NC}"

# 3. Stage 2: Pytest Suite with 100% Statement & Branch Coverage Gate
echo -e "\n${YELLOW}▶ Stage 2: Pytest Suite (100% Coverage Gate)${NC}"
cd "${MODULE_DIR}"
"${PYTEST_BIN}" --cov=app --cov=services/worker --cov-report=term-missing --cov-fail-under=100
echo -e "${GREEN}✅ Stage 2 Passed: 100% test coverage verified.${NC}"

# 4. Stage 3: Live Docker Compose Services Readiness Check
echo -e "\n${YELLOW}▶ Stage 3: Checking Live Distributed Stack Readiness${NC}"
if curl -sf http://localhost:8010/health/ready &>/dev/null; then
    echo -e "${GREEN}✅ Gateway is healthy on http://localhost:8010/health/ready${NC}"
else
    echo -e "${YELLOW}⚠️ Gateway not responding on port 8010. Starting ephemeral stack...${NC}"
    docker compose -f "${MODULE_DIR}/docker-compose.yml" up -d --scale api_instant=2 --scale api_batch=2
    echo "Waiting for gateway readiness..."
    timeout 45s bash -c "until curl -sf http://localhost:8010/health/ready; do sleep 2; done"
    echo -e "${GREEN}✅ All services healthy.${NC}"
fi

# 5. Stage 4: Automated CI/CD Contention & Capacity Regression Gate
echo -e "\n${YELLOW}▶ Stage 4: Automated Contention & Capacity Regression Gate (150 req/s SLA)${NC}"
"${PYTHON_BIN}" "${MODULE_DIR}/scripts/ci_contention_gate.py" \
    --rate 150 \
    --duration 10 \
    --p99-threshold 100.0 \
    --baseline-p99 83.0 \
    --max-degradation 15.0 \
    --max-db-conns 26

echo -e "\n${GREEN}======================================================================${NC}"
echo -e "${GREEN}🎉 ALL LOCAL CI GATES PASSED! Ready to commit and push.${NC}"
echo -e "${GREEN}======================================================================${NC}"
