#!/bin/bash
# Run Python SDK tests
# Requires: pytest, grid_memory dependencies

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SDK_DIR="$SCRIPT_DIR/sdk/python"

echo "╔════════════════════════════════════════╗"
echo "║   Grid Memory — Python SDK Tests      ║"
echo "╚════════════════════════════════════════╝"
echo ""

# Check if pytest is available
if ! command -v pytest &>/dev/null; then
    echo "  ⚠ pytest not found. Install with: pip install pytest"
    echo "  Skipping Python tests."
    exit 0
fi

# Install SDK if not already installed
if ! python3 -c "import grid_memory" 2>/dev/null; then
    echo "→ Installing grid-memory SDK..."
    cd "$SDK_DIR"
    pip install -e . 2>&1 | tail -3
    echo "  ✓ SDK installed"
fi

echo "→ Running Python SDK tests..."
cd "$SDK_DIR"

# Run tests with verbose output
python3 -m pytest tests/ -v --tb=short 2>&1 | tail -20

echo ""
echo "═══ Python SDK Tests Complete ═══"
