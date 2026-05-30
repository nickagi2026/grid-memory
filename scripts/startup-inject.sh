#!/usr/bin/env bash
# shared-memory-grid/scripts/startup-inject.sh
# Run at session start to inject shared memory context.
# Output: a system context block that the agent reads on wake.
# Usage: node $(dirname "$0")/../reference/store.js inject --context "session start"
set -euo pipefail
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
node "${SKILL_DIR}/reference/store.js" inject --context "session start"
