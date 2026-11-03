#!/usr/bin/env bash
# ==============================================================================
# Automated US Market Report Generator - Quickstart Launcher
# ==============================================================================
set -e

# Navigate to the project root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 1. Prefer uv if available (lightning-fast environment & dependency management)
if command -v uv >/dev/null 2>&1; then
    if [ ! -d ".venv" ]; then
        echo "⚡ uv detected! Creating virtual environment..."
        uv venv .venv
        uv pip install -r requirements.txt
        uv pip install -e .
    fi
    if [ $# -eq 0 ]; then
        exec .venv/bin/python report.py -O
    else
        exec .venv/bin/python report.py "$@"
    fi
fi

# 2. Fallback to standard Python 3.10+ venv
if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
else
    echo "❌ Error: Python 3.10+ is required but not found in PATH."
    exit 1
fi

if [ ! -d ".venv" ]; then
    echo "📦 Creating virtual environment in .venv..."
    "$PYTHON_BIN" -m venv .venv
    echo "📥 Installing dependencies from requirements.txt (one-time setup)..."
    .venv/bin/python -m pip install --upgrade pip
    .venv/bin/python -m pip install -r requirements.txt
    .venv/bin/python -m pip install -e .
fi

if [ $# -eq 0 ]; then
    exec .venv/bin/python report.py -O
else
    exec .venv/bin/python report.py "$@"
fi
