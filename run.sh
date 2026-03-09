#!/bin/bash

# Auto runner for Private Clinic Management System
# Handles installation, testing, and running the application

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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
    
    log "INFO" "Installing dependencies..."
    if [ "$VERBOSE" = true ]; then
        python3 -m pip install -r "$SCRIPT_DIR/requirements.txt"
    else
        python3 -m pip install -q -r "$SCRIPT_DIR/requirements.txt"
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
    python3 "$SCRIPT_DIR/test_app.py"
    log "SUCCESS" "Tests completed"
}

# Run the app
run_app() {
    if [ ! -f "$SCRIPT_DIR/app.py" ]; then
        log "ERROR" "app.py not found"
        return 1
    fi
    
    log "INFO" "Starting application on http://127.0.0.1:5000"
    python3 "$SCRIPT_DIR/app.py"
}

# Main execution
main() {
    echo "=================================================="
    echo "Private Clinic Management System - Auto Runner"
    echo "=================================================="
    
    install_dependencies || exit 1
    
    if [ "$RUN_TESTS" = true ]; then
        run_tests || exit 1
    fi
    
    if [ "$TEST_ONLY" = false ]; then
        run_app
    fi
}

main
