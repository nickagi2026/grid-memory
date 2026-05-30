#!/bin/bash
# Grid Memory — One-Command Install
# Usage: curl -sSL https://grid-memory.ai/install.sh | bash
# Or:    ./install.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "╔════════════════════════════════════════╗"
echo "║     Grid Memory — Quick Install       ║"
echo "╚════════════════════════════════════════╝"
echo ""

# ─── Check Prerequisites ───
echo "→ Checking prerequisites..."
if command -v node &>/dev/null; then
  NODE_VER=$(node --version)
  echo "  ✓ Node.js: $NODE_VER"
else
  echo "  ✗ Node.js is required. Install from: https://nodejs.org"
  echo "    Then re-run this script."
  exit 1
fi

if [ "$(node -e "console.log(process.version.slice(1).split('.')[0] >= 18 ? 'ok' : 'old')")" != "ok" ]; then
  echo "  ✗ Node.js 18+ required. Current: $(node --version)"
  exit 1
fi

# ─── Locate Grid Files ───
GRID_DIR="$SCRIPT_DIR"
if [ ! -f "$GRID_DIR/server.js" ]; then
  # Check parent (running from scripts/)
  GRID_DIR="$(dirname "$SCRIPT_DIR")"
fi
if [ ! -f "$GRID_DIR/server.js" ]; then
  echo "  ✗ Grid Memory files not found alongside this script."
  echo "    Place install.sh in the shared-memory-grid directory and re-run."
  exit 1
fi

echo "  ✓ Grid Memory files found at: $GRID_DIR"
echo ""

# ─── Install Dependencies ───
echo "→ Installing dependencies..."
cd "$GRID_DIR"
npm install 2>&1 | tail -3
echo "  ✓ Dependencies installed"
echo ""

# ─── Start Server ───
echo "→ Starting Grid Memory on http://localhost:8080"
echo "  (Seed mode enabled — demo data loads automatically)"
echo ""
echo "  Press Ctrl+C to stop the server"
echo ""

GRID_SEED_MODE=true node server.js
