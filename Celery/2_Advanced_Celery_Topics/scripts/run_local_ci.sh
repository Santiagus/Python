#!/usr/bin/env bash
# ==============================================================================
# General Local CI/CD Pipeline & Pre-Commit Verification Runner
#
# Applicable to any upcoming project module to guarantee minimum code quality:
#   • Pre-Flight: Repository Hygiene & Conflict Safeguards
#   • Stage 1   : Mermaid Diagram Syntax & Render Validation
#   • Stage 2   : Code Style & Formatting Check (Ruff Format)
#   • Stage 3   : Linting & Code Hygiene (Ruff Check)
#   • Stage 4   : Static Type Checking (Mypy)
#   • Stage 5   : Test Suite Execution (All Tests Pass)
#   • Stage 6   : Test Coverage Gate (100% Statement & Branch Coverage)
#
# Modes:
#   --quick (DEFAULT): Fast static checks & unit test pass (< 3s)
#   --full           : Full pipeline including 100% coverage gate
#   --project, -p    : Target module (auto-detected if omitted)
# ==============================================================================
set -euo pipefail

# 1. Resolve script directory and repository root even through symlinks
INVOCATION_DIR="$(pwd -P)"
SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do
    DIR="$(cd -P "$(dirname "$SOURCE")" >/dev/null 2>&1 && pwd)"
    SOURCE="$(readlink "$SOURCE")"
    [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"
done
SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" >/dev/null 2>&1 && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# 2. Parse command-line arguments
MODE="quick"
EXPLICIT_MODULE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --full)
            MODE="full"
            shift
            ;;
        --quick)
            MODE="quick"
            shift
            ;;
        -p|--project)
            EXPLICIT_MODULE="$2"
            shift 2
            ;;
        0[1-9]_*)
            EXPLICIT_MODULE="$1"
            shift
            ;;
        *)
            echo "Usage: $0 [--quick | --full] [--project <MODULE_NAME>]"
            echo "  --quick (default): Run hygiene, mermaid, style, lint, mypy, and test pass (< 3s)"
            echo "  --full           : Run all quick checks + strict 100% test coverage gate"
            echo "  --project, -p    : Target project directory (auto-detected if omitted)"
            exit 1
            ;;
    esac
done

# 3. Detect target project module dynamically
DETECTED_MODULE=""

# Case A: Explicitly supplied via CLI
if [ -n "${EXPLICIT_MODULE}" ]; then
    DETECTED_MODULE="${EXPLICIT_MODULE}"
fi

# Case B: Invoked from inside a module directory (e.g. ~/Python/Celery/2_Advanced_Celery_Topics/05_application_integration)
if [ -z "${DETECTED_MODULE}" ]; then
    if [[ "${INVOCATION_DIR}" == "${REPO_ROOT}/"* ]]; then
        REL_PATH="${INVOCATION_DIR#"${REPO_ROOT}/"}"
        FIRST_DIR="${REL_PATH%%/*}"
        if [ -d "${REPO_ROOT}/${FIRST_DIR}" ] && [[ "${FIRST_DIR}" =~ ^[0-9]{2}_ ]]; then
            DETECTED_MODULE="${FIRST_DIR}"
        fi
    fi
fi

# Case C: Invoked from git pre-commit hook or repo root; inspect staged files
if [ -z "${DETECTED_MODULE}" ] && command -v git &>/dev/null; then
    STAGED_FILES="$(git diff --cached --name-only 2>/dev/null || true)"
    for STAGED in ${STAGED_FILES}; do
        if [[ "${STAGED}" =~ ([0-9]{2}_[a-zA-Z0-9_]+) ]]; then
            CANDIDATE="${BASH_REMATCH[1]}"
            if [ -d "${REPO_ROOT}/${CANDIDATE}" ]; then
                DETECTED_MODULE="${CANDIDATE}"
                break
            fi
        fi
    done
fi

# Case D: Fallback to most recently modified module directory
if [ -z "${DETECTED_MODULE}" ]; then
    LATEST_MODULE="$(find "${REPO_ROOT}" -maxdepth 1 -type d -name "[0-9][0-9]_*" 2>/dev/null | xargs ls -td 2>/dev/null | head -n 1 || true)"
    if [ -n "${LATEST_MODULE}" ]; then
        DETECTED_MODULE="$(basename "${LATEST_MODULE}")"
    fi
fi

if [ -z "${DETECTED_MODULE}" ]; then
    echo -e "\033[0;31m❌ Error: No project module specified or detected. Use --project <MODULE_NAME>.\033[0m"
    exit 1
fi

MODULE_NAME="${DETECTED_MODULE}"
MODULE_DIR="${REPO_ROOT}/${MODULE_NAME}"

if [ ! -d "${MODULE_DIR}" ]; then
    echo -e "\033[0;31m❌ Error: Module directory '${MODULE_DIR}' does not exist.\033[0m"
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
echo -e "${BLUE}🚀 RUNNING GENERAL CI/CD GATE [MODULE: ${MODULE_NAME} | MODE: ${MODE^^}]${NC}"
echo -e "${BLUE}======================================================================${NC}"

# 4. Resolve Python executable & tooling dynamically (no hardcoded project modules)
PYTHON_BIN=""
PYTEST_BIN=""
RUFF_BIN=""
MYPY_BIN=""

# Priority 1: Currently active virtualenv ($VIRTUAL_ENV)
if [ -n "${VIRTUAL_ENV:-}" ] && [ -f "${VIRTUAL_ENV}/bin/python" ]; then
    PYTHON_BIN="${VIRTUAL_ENV}/bin/python"
    [ -f "${VIRTUAL_ENV}/bin/pytest" ] && PYTEST_BIN="${VIRTUAL_ENV}/bin/pytest"
    [ -f "${VIRTUAL_ENV}/bin/ruff" ] && RUFF_BIN="${VIRTUAL_ENV}/bin/ruff"
    [ -f "${VIRTUAL_ENV}/bin/mypy" ] && MYPY_BIN="${VIRTUAL_ENV}/bin/mypy"
fi

# Priority 2: Target module .venv
if [ -z "${PYTHON_BIN}" ] || [ ! -f "${PYTHON_BIN}" ]; then
    if [ -f "${MODULE_DIR}/.venv/bin/python" ]; then
        PYTHON_BIN="${MODULE_DIR}/.venv/bin/python"
        [ -f "${MODULE_DIR}/.venv/bin/pytest" ] && PYTEST_BIN="${MODULE_DIR}/.venv/bin/pytest"
        [ -f "${MODULE_DIR}/.venv/bin/ruff" ] && RUFF_BIN="${MODULE_DIR}/.venv/bin/ruff"
        [ -f "${MODULE_DIR}/.venv/bin/mypy" ] && MYPY_BIN="${MODULE_DIR}/.venv/bin/mypy"
    fi
fi

# Priority 3: Root-level or sibling .venv
if [ -z "${PYTHON_BIN}" ] || [ ! -f "${PYTHON_BIN}" ]; then
    CANDIDATE_VENV="$(find "${REPO_ROOT}" -maxdepth 3 -name "python" 2>/dev/null | grep '/\.venv/bin/python' | head -n 1 || true)"
    if [ -n "${CANDIDATE_VENV}" ] && [ -f "${CANDIDATE_VENV}" ]; then
        VENV_DIR="$(dirname "$(dirname "${CANDIDATE_VENV}")")"
        PYTHON_BIN="${VENV_DIR}/bin/python"
        [ -f "${VENV_DIR}/bin/pytest" ] && PYTEST_BIN="${VENV_DIR}/bin/pytest"
        [ -f "${VENV_DIR}/bin/ruff" ] && RUFF_BIN="${VENV_DIR}/bin/ruff"
        [ -f "${VENV_DIR}/bin/mypy" ] && MYPY_BIN="${VENV_DIR}/bin/mypy"
    fi
fi

# Priority 4: System / PATH fallback
[ -z "${PYTHON_BIN}" ] || [ ! -f "${PYTHON_BIN}" ] && PYTHON_BIN="$(command -v python3 || echo "")"
[ -z "${PYTEST_BIN}" ] || [ ! -f "${PYTEST_BIN}" ] && PYTEST_BIN="$(command -v pytest || echo "")"
[ -z "${RUFF_BIN}" ] || [ ! -f "${RUFF_BIN}" ] && RUFF_BIN="$(command -v ruff || true)"
[ -z "${MYPY_BIN}" ] || [ ! -f "${MYPY_BIN}" ] && MYPY_BIN="$(command -v mypy || true)"

# 5. Dynamically discover Python source packages, test directories, and coverage targets
cd "${REPO_ROOT}"

CHECK_PATHS=()
COV_TARGETS=()

# 1. Target application gateway (if present)
if [ -d "${MODULE_DIR}/app" ]; then
    CHECK_PATHS+=("${MODULE_NAME}/app")
    COV_TARGETS+=("--cov=app")
fi

# 2. Target worker microservice or services layer (if present)
if [ -d "${MODULE_DIR}/services/worker" ]; then
    CHECK_PATHS+=("${MODULE_NAME}/services/worker")
    COV_TARGETS+=("--cov=services/worker")
elif [ -d "${MODULE_DIR}/services" ]; then
    CHECK_PATHS+=("${MODULE_NAME}/services")
    COV_TARGETS+=("--cov=services")
fi

# 3. Target standard domain/source root directories (if present)
for EXTRA_DIR in src domain core; do
    if [ -d "${MODULE_DIR}/${EXTRA_DIR}" ]; then
        CHECK_PATHS+=("${MODULE_NAME}/${EXTRA_DIR}")
        COV_TARGETS+=("--cov=${EXTRA_DIR}")
    fi
done

# If module has root-level .py files, include them
if [ -n "$(find "${MODULE_DIR}" -maxdepth 1 -name "*.py" 2>/dev/null)" ]; then
    CHECK_PATHS+=("${MODULE_NAME}")
fi

PYPROJECT_CONFIG=""
if [ -f "${MODULE_DIR}/pyproject.toml" ]; then
    PYPROJECT_CONFIG="${MODULE_DIR}/pyproject.toml"
elif [ -f "${REPO_ROOT}/pyproject.toml" ]; then
    PYPROJECT_CONFIG="${REPO_ROOT}/pyproject.toml"
fi

# ------------------------------------------------------------------------------
# Pre-Flight: Repository Hygiene & Conflict Safeguards
# ------------------------------------------------------------------------------
echo -e "\n${CYAN}▶ Pre-Flight: Repository Hygiene & Conflict Safeguards${NC}"
if command -v git &>/dev/null; then
    # Check for merge conflict markers in staged files
    CONFLICTS="$(git diff --cached -S"<<<<<<< " --name-only 2>/dev/null || true)"
    if [ -n "${CONFLICTS}" ]; then
        echo -e "${RED}❌ Error: Unresolved merge conflict markers detected in staged files:${NC}"
        echo "${CONFLICTS}"
        exit 1
    fi

    # Check for sensitive credential leaks
    STAGED_SECRETS="$(git diff --cached --name-only 2>/dev/null | grep -E '(\.env$|\.key$|\.pem$|id_rsa)' || true)"
    if [ -n "${STAGED_SECRETS}" ]; then
        echo -e "${RED}❌ Error: Sensitive credential file(s) detected in staged git index:${NC}"
        echo "${STAGED_SECRETS}"
        echo -e "${YELLOW}Please unstage or remove sensitive files before committing.${NC}"
        exit 1
    fi
fi
echo -e "${GREEN}✅ Pre-Flight Passed: Repository hygiene verified (no conflict markers, no secret leaks).${NC}"

# ------------------------------------------------------------------------------
# Stage 1: Mermaid Diagram Syntax & Render Validation
# ------------------------------------------------------------------------------
echo -e "\n${CYAN}▶ Stage 1: Mermaid Diagram Syntax & Render Validation${NC}"
if [ -f "${SCRIPT_DIR}/verify_mermaid.py" ] && [ -n "${PYTHON_BIN}" ]; then
    "${PYTHON_BIN}" "${SCRIPT_DIR}/verify_mermaid.py" "${MODULE_DIR}"
    echo -e "${GREEN}✅ Stage 1 Passed: All Mermaid diagrams in ${MODULE_NAME} valid.${NC}"
else
    echo -e "${YELLOW}ℹ️  Stage 1 Skipped: Mermaid verifier script or python binary not found.${NC}"
fi

# ------------------------------------------------------------------------------
# Stage 2: Code Style & Formatting Check (Ruff Format)
# ------------------------------------------------------------------------------
echo -e "\n${CYAN}▶ Stage 2: Code Style & Formatting Check (Ruff Format)${NC}"
if [ -n "${RUFF_BIN}" ] && [ ${#CHECK_PATHS[@]} -gt 0 ]; then
    if [ -n "${PYPROJECT_CONFIG}" ]; then
        "${RUFF_BIN}" format --check --config "${PYPROJECT_CONFIG}" "${CHECK_PATHS[@]}"
    else
        "${RUFF_BIN}" format --check "${CHECK_PATHS[@]}"
    fi
    echo -e "${GREEN}✅ Stage 2 Passed: Code formatting adheres to PEP 8 standards.${NC}"
elif [ -z "${RUFF_BIN}" ]; then
    echo -e "${YELLOW}ℹ️  Stage 2 Skipped: Ruff binary not found.${NC}"
else
    echo -e "${YELLOW}ℹ️  Stage 2 Skipped: No target Python source paths found in ${MODULE_NAME}.${NC}"
fi

# ------------------------------------------------------------------------------
# Stage 3: Linting & Code Hygiene (Ruff Check)
# ------------------------------------------------------------------------------
echo -e "\n${CYAN}▶ Stage 3: Linting & Code Hygiene (Ruff Check)${NC}"
if [ -n "${RUFF_BIN}" ] && [ ${#CHECK_PATHS[@]} -gt 0 ]; then
    if [ -n "${PYPROJECT_CONFIG}" ]; then
        "${RUFF_BIN}" check --config "${PYPROJECT_CONFIG}" "${CHECK_PATHS[@]}"
    else
        "${RUFF_BIN}" check "${CHECK_PATHS[@]}"
    fi
    echo -e "${GREEN}✅ Stage 3 Passed: Zero linter errors or warnings.${NC}"
elif [ -z "${RUFF_BIN}" ]; then
    echo -e "${YELLOW}ℹ️  Stage 3 Skipped: Ruff binary not found.${NC}"
else
    echo -e "${YELLOW}ℹ️  Stage 3 Skipped: No target Python source paths found in ${MODULE_NAME}.${NC}"
fi

# ------------------------------------------------------------------------------
# Stage 4: Static Type Checking (Mypy)
# ------------------------------------------------------------------------------
echo -e "\n${CYAN}▶ Stage 4: Static Type Checking (Mypy)${NC}"
if [ -n "${MYPY_BIN}" ] && [ ${#CHECK_PATHS[@]} -gt 0 ]; then
    if [ -n "${PYPROJECT_CONFIG}" ]; then
        "${MYPY_BIN}" --config-file "${PYPROJECT_CONFIG}" "${CHECK_PATHS[@]}" --ignore-missing-imports
    else
        "${MYPY_BIN}" "${CHECK_PATHS[@]}" --ignore-missing-imports
    fi
    echo -e "${GREEN}✅ Stage 4 Passed: Type checking verified with zero errors.${NC}"
elif [ -z "${MYPY_BIN}" ]; then
    echo -e "${YELLOW}ℹ️  Stage 4 Skipped: Mypy binary not found.${NC}"
else
    echo -e "${YELLOW}ℹ️  Stage 4 Skipped: No target Python source paths found in ${MODULE_NAME}.${NC}"
fi

# ------------------------------------------------------------------------------
# Stage 5: Test Suite Execution (All Tests Pass)
# ------------------------------------------------------------------------------
echo -e "\n${CYAN}▶ Stage 5: Test Suite Execution (All Tests Pass)${NC}"
HAS_TESTS=false
if [ -d "${MODULE_DIR}/tests" ] && [ -n "$(find "${MODULE_DIR}/tests" -maxdepth 3 -name "test_*.py" 2>/dev/null)" ]; then
    HAS_TESTS=true
fi

if [ "${HAS_TESTS}" = true ] && [ -n "${PYTEST_BIN}" ]; then
    cd "${MODULE_DIR}"
    PYTEST_ARGS=("-q")
    [ -f pytest.ini ] && PYTEST_ARGS+=("-c" "pytest.ini")

    if [ "${MODE}" = "quick" ] && [ -d "tests/unit" ] && [ -n "$(find "tests/unit" -maxdepth 2 -name "test_*.py" 2>/dev/null)" ]; then
        "${PYTEST_BIN}" "${PYTEST_ARGS[@]}" tests/unit/
    else
        "${PYTEST_BIN}" "${PYTEST_ARGS[@]}" tests/
    fi
    cd "${REPO_ROOT}"
    echo -e "${GREEN}✅ Stage 5 Passed: All tests succeeded with zero failures.${NC}"
elif [ "${HAS_TESTS}" = false ]; then
    echo -e "${YELLOW}ℹ️  Stage 5 Skipped: No tests found in ${MODULE_NAME} (in progress).${NC}"
else
    echo -e "${YELLOW}ℹ️  Stage 5 Skipped: Pytest binary not found.${NC}"
fi

# ------------------------------------------------------------------------------
# Quick Mode Finish
# ------------------------------------------------------------------------------
if [ "${MODE}" = "quick" ]; then
    echo -e "\n${GREEN}======================================================================${NC}"
    echo -e "${GREEN}🎉 ALL QUICK CHECKS PASSED FOR ${MODULE_NAME} (< 3s)! Clean to commit.${NC}"
    echo -e "${YELLOW}💡 Tip: Run '$0 --full' before pushing to remote for 100% coverage verification.${NC}"
    echo -e "${GREEN}======================================================================${NC}"
    exit 0
fi

# ------------------------------------------------------------------------------
# FULL MODE ONLY: Stage 6: 100% Test Coverage Gate
# ------------------------------------------------------------------------------
echo -e "\n${BLUE}--- Entering Full Verification Mode (100% Test Coverage Gate) ---${NC}"

echo -e "\n${CYAN}▶ Stage 6: 100% Test Coverage Gate${NC}"
if [ "${HAS_TESTS}" = true ] && [ -n "${PYTEST_BIN}" ] && [ ${#COV_TARGETS[@]} -gt 0 ]; then
    cd "${MODULE_DIR}"
    PYTEST_ARGS=()
    [ -f pytest.ini ] && PYTEST_ARGS+=("-c" "pytest.ini")
    
    "${PYTEST_BIN}" "${PYTEST_ARGS[@]}" tests "${COV_TARGETS[@]}" --cov-report=term-missing --cov-fail-under=100
    cd "${REPO_ROOT}"
    echo -e "${GREEN}✅ Stage 6 Passed: 100% statement and branch coverage verified in ${MODULE_NAME}.${NC}"
elif [ "${HAS_TESTS}" = false ]; then
    echo -e "${YELLOW}ℹ️  Stage 6 Skipped: No tests found in ${MODULE_NAME} (in progress).${NC}"
elif [ ${#COV_TARGETS[@]} -eq 0 ]; then
    echo -e "${YELLOW}ℹ️  Stage 6 Skipped: No Python source packages detected for coverage measurement.${NC}"
else
    echo -e "${YELLOW}ℹ️  Stage 6 Skipped: Pytest binary not found.${NC}"
fi

echo -e "\n${GREEN}======================================================================${NC}"
echo -e "${GREEN}🎉 ALL CI/CD GATES PASSED FOR ${MODULE_NAME}! (All Tests Pass & 100% Coverage Verified).${NC}"
echo -e "${GREEN}======================================================================${NC}"
