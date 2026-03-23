#!/bin/bash

# Auto runner for Private Clinic Management System
# Handles installation, testing, and running the application

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
PYTHON_BIN="python3"
USE_VENV=false
VERBOSE=false
RUN_TESTS=false
TEST_ONLY=false
SKIP_INSTALL=false

# Parse command-line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-install)
            SKIP_INSTALL=true
            shift
            ;;
        --test)
            RUN_TESTS=true
            shift
            ;;
        --test-only)
            TEST_ONLY=true
            RUN_TESTS=true
            shift
            ;;
        --verbose|-v)
            VERBOSE=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--skip-install] [--test] [--test-only] [--verbose]"
            exit 1
            ;;
    esac
done

# Logging function
log() {
    local level=$1
    shift
    echo "[$level] $*"
}

ensure_python_runtime() {
    if [ -x "$VENV_DIR/bin/python" ]; then
        if "$VENV_DIR/bin/python" -m pip --version >/dev/null 2>&1 || "$VENV_DIR/bin/python" -m ensurepip --upgrade >/dev/null 2>&1; then
            PYTHON_BIN="$VENV_DIR/bin/python"
            USE_VENV=true
            return 0
        fi

        log "WARNING" "Existing virtual environment is incomplete; falling back to system Python"
    fi

    if [ "$SKIP_INSTALL" = true ]; then
        PYTHON_BIN="python3"
        USE_VENV=false
        return 0
    fi

    log "INFO" "Creating virtual environment at $VENV_DIR"
    if python3 -m venv "$VENV_DIR" && "$VENV_DIR/bin/python" -m pip --version >/dev/null 2>&1; then
        PYTHON_BIN="$VENV_DIR/bin/python"
        USE_VENV=true
        return 0
    fi

    log "WARNING" "Could not create a usable virtual environment; using system Python instead"
    PYTHON_BIN="python3"
    USE_VENV=false
}

ensure_pip() {
    if [ "$USE_VENV" != true ]; then
        return 0
    fi

    if "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; then
        return 0
    fi

    log "INFO" "Bootstrapping pip inside $VENV_DIR"
    "$PYTHON_BIN" -m ensurepip --upgrade >/dev/null 2>&1
}

# Install dependencies
install_dependencies() {
    if [ "$SKIP_INSTALL" = true ]; then
        log "INFO" "Skipping dependency installation"
        return 0
    fi
    
    if [ ! -f "$SCRIPT_DIR/requirements.txt" ]; then
        log "WARNING" "requirements.txt not found"
        return 1
    fi
    
    ensure_pip || return 1

    log "INFO" "Installing dependencies..."
    if [ "$VERBOSE" = true ]; then
        if [ "$USE_VENV" = true ]; then
            "$PYTHON_BIN" -m pip install -r "$SCRIPT_DIR/requirements.txt"
        else
            "$PYTHON_BIN" -m pip install --break-system-packages -r "$SCRIPT_DIR/requirements.txt"
        fi
    else
        if [ "$USE_VENV" = true ]; then
            "$PYTHON_BIN" -m pip install -q -r "$SCRIPT_DIR/requirements.txt"
        else
            "$PYTHON_BIN" -m pip install --break-system-packages -q -r "$SCRIPT_DIR/requirements.txt"
        fi
    fi
    log "SUCCESS" "Dependencies installed"
}

# Run tests
run_tests() {
    if [ ! -f "$SCRIPT_DIR/test_app.py" ]; then
        log "WARNING" "test_app.py not found"
        return 1
    fi
    
    log "INFO" "Running tests..."
    "$PYTHON_BIN" "$SCRIPT_DIR/test_app.py"
    log "SUCCESS" "Tests completed"
}

# Run the app
run_app() {
    if [ ! -f "$SCRIPT_DIR/app.py" ]; then
        log "ERROR" "app.py not found"
        return 1
    fi
    
    log "INFO" "Starting application on http://127.0.0.1:5000"
    "$PYTHON_BIN" "$SCRIPT_DIR/app.py"
}

# Main execution
main() {
    echo "=================================================="
    echo "Private Clinic Management System - Auto Runner"
    echo "=================================================="

    ensure_python_runtime || exit 1
    
    install_dependencies || exit 1
    
    if [ "$RUN_TESTS" = true ]; then
        run_tests || exit 1
    fi
    
    if [ "$TEST_ONLY" = false ]; then
        run_app
    fi
}

main
