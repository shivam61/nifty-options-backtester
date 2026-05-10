#!/bin/bash
# Quick helper to check and refresh Fyers token
# Usage: ./scripts/quick_token_check.sh

set -e

cd "$(dirname "$0")/.."

echo "=================================="
echo "Fyers Token Quick Check"
echo "=================================="
echo ""

# Activate virtual environment
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
else
    echo "Error: Virtual environment not found at .venv/"
    echo "Run: python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

# Run token checker
python scripts/refresh_fyers_token.py
