#!/usr/bin/env bash
# shared-memory-grid/scripts/setup.sh
# Creates local directory scaffolding for The Grid.
# Makes no network calls, installs no packages.

set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE_DIR="${OPENCLAW_WORKSPACE:-$HOME/.openclaw/workspace}"

echo "═══ Shared Memory Grid — Setup ═══"
echo ""
echo "This script creates the data directory for The Grid."
echo "No network calls. No package installations."
echo ""

# Create data directory
DATA_DIR="${SKILL_DIR}/data"
mkdir -p "${DATA_DIR}"

# Create empty store if not exists
STORE_FILE="${DATA_DIR}/store.json"
if [ ! -f "${STORE_FILE}" ]; then
  echo "{\"version\":1,\"created_at\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",\"entries\":[]}" > "${STORE_FILE}"
  echo "  ✓ Created store: ${STORE_FILE}"
else
  echo "  • Store exists: ${STORE_FILE}"
fi

# Create index file
INDEX_FILE="${DATA_DIR}/index.json"
if [ ! -f "${INDEX_FILE}" ]; then
  echo "{\"version\":1,\"tags\":{},\"agents\":{},\"types\":{}}" > "${INDEX_FILE}"
  echo "  ✓ Created index: ${INDEX_FILE}"
else
  echo "  • Index exists: ${INDEX_FILE}"
fi

echo ""
echo "═══ Setup Complete ═══"
echo ""
echo "To verify: node ${SKILL_DIR}/reference/store.js info"
echo ""
echo "Usage examples:"
echo "  Write:  node ${SKILL_DIR}/reference/store.js write --agent main --type decision --tags project:alpha --content \"Decided to use Express\""
echo "  Read:   node ${SKILL_DIR}/reference/store.js read --tags project:alpha"
echo "  Inject: node ${SKILL_DIR}/reference/store.js inject --context \"building auth module\""
echo "  Info:   node ${SKILL_DIR}/reference/store.js info"
echo "  Prune:  node ${SKILL_DIR}/reference/store.js prune"
