#!/usr/bin/env node
/**
 * tests/test-ask-isolation.js — Prove /ask workspace isolation
 *
 * Verifies that a workspace-scoped /ask equivalent only retrieves
 * entries from that workspace.
 */

const { Grid } = require('../reference/store.js');
const fs = require('fs');
const path = require('path');
const os = require('os');

const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ask-test-'));
process.env.GRID_STORE_DIR = dir;

async function main() {
  let passed = 0, failed = 0;
  const g = new Grid();
  
  // Write entries to different workspaces
  await g.write({ agent_id: 'a', type: 'fact', content: 'WS-A secret', tags: ['ws:ws-a', 'topic'], workspace_id: 'ws-a' });
  await g.write({ agent_id: 'b', type: 'fact', content: 'WS-B secret', tags: ['ws:ws-b', 'topic'], workspace_id: 'ws-b' });

  // Workspace-scoped read (simulates /ask with workspace isolation)
  const wsA = await g.read({ tags: ['ws:ws-a', 'topic'], max: 50, tagMode: 'AND' });
  const wsAEntries = wsA.entries.filter(e => (e.tags || []).includes('topic'));

  const wsB = await g.read({ tags: ['ws:ws-b', 'topic'], max: 50, tagMode: 'AND' });
  const wsBEntries = wsB.entries.filter(e => (e.tags || []).includes('topic'));

  // WS-A query should only return WS-A data
  if (wsAEntries.some(e => e.workspace_id === 'ws-b')) {
    console.error('✗ testAskIsolation: WS-A query returned WS-B entries');
    failed++;
  } else {
    console.log('✓ testAskIsolation: WS-A query isolated from WS-B');
    passed++;
  }

  // WS-B query should only return WS-B data
  if (wsBEntries.some(e => e.workspace_id === 'ws-a')) {
    console.error('✗ testAskIsolation: WS-B query returned WS-A entries');
    failed++;
  } else {
    console.log('✓ testAskIsolation: WS-B query isolated from WS-A');
    passed++;
  }

  // Each query should find its own entry
  if (wsAEntries.length < 1) {
    console.error('✗ testAskIsolation: WS-A query returned no entries');
    failed++;
  } else {
    console.log('✓ testAskIsolation: WS-A found its entry');
    passed++;
  }

  fs.rmSync(dir, { recursive: true, force: true });
  console.log(`\n═══ /Ask Isolation — ${passed} passed, ${failed} failed ═══`);
  process.exit(failed > 0 ? 1 : 0);
}

main().catch(e => { console.error(e); process.exit(1); });
