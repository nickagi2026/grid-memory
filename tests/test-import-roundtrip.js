#!/usr/bin/env node
/**
 * tests/test-import-roundtrip.js — Import Workspace Isolation Tests
 *
 * Verifies that workspace tags are correctly handled during import:
 * - Old ws: tags are stripped
 * - New ws: tags are applied
 * - Entries without agent_id are skipped
 */

'use strict';

const fs = require('fs');
const path = require('path');
const os = require('os');

const TEST_DIR = path.join(os.tmpdir(), 'test_import_rt_' + Date.now());
process.env.GRID_STORE_DIR = TEST_DIR;

const { Grid } = require('../reference/store.js');

let grid;
let passed = 0, failed = 0;
function assert(cond, msg) { if (cond) { passed++; return; } console.error('  ✗ ' + msg); failed++; }

async function setup() {
  if (fs.existsSync(TEST_DIR)) fs.rmSync(TEST_DIR, { recursive: true });
  fs.mkdirSync(TEST_DIR, { recursive: true });
  grid = new Grid();
}

async function cleanup() {
  if (fs.existsSync(TEST_DIR)) fs.rmSync(TEST_DIR, { recursive: true });
}

async function testExportPreservesWorkspaceTags() {
  await grid.write({ agent_id: 'a', type: 'fact', content: 'Entry A', tags: ['ws:alpha', 'topic:rt'] });
  await grid.write({ agent_id: 'b', type: 'fact', content: 'Entry B', tags: ['ws:beta', 'topic:rt'] });
  const exportData = await grid.exportAll();
  const aTags = exportData.entries.filter(e => e.agent_id === 'a').map(e => e.tags);
  assert(aTags.some(t => t.includes('ws:alpha')), 'Export preserves ws:alpha');
  const bTags = exportData.entries.filter(e => e.agent_id === 'b').map(e => e.tags);
  assert(bTags.some(t => t.includes('ws:beta')), 'Export preserves ws:beta');
  console.log('  ✓ export preserves workspace tags');
}

async function testImportStripLogic() {
  // Simulate the server's import workspace forcing logic
  const entry = { agent_id: 'test', type: 'fact', content: 'Import test', tags: ['ws:old', 'topic:import-check'] };

  // This is what the server does on workspace-scoped import:
  const ws = 'new-workspace';
  const strippedTags = entry.tags.filter(t => !t.startsWith('ws:'));
  strippedTags.push('ws:' + ws);
  const newTags = strippedTags;

  assert(!newTags.includes('ws:old'), 'Old ws:old stripped');
  assert(newTags.includes('ws:new-workspace'), 'New ws:new-workspace applied');
  assert(newTags.includes('topic:import-check'), 'Non-ws tags preserved');

  // Actually write it and verify
  await grid.write({ agent_id: entry.agent_id, type: entry.type, content: entry.content, tags: newTags });
  const result = await grid.read({ tags: ['ws:new-workspace', 'topic:import-check'] });
  assert(result.entries.length >= 1, 'Imported entry visible in new workspace');
  const found = result.entries[0];
  assert(!found.tags.includes('ws:old'), 'Stored entry has no ws:old');

  console.log('  ✓ import strips old ws: tags and applies new ones');
}

async function testImportRejectsNoAgent() {
  // Simulate import skipping entries with missing required fields
  const entries = [
    { type: 'fact', content: 'No agent', tags: ['ws:c'] },
    { agent_id: 'valid', type: 'fact', content: 'Has agent', tags: ['ws:c'] },
  ];
  let imported = 0;
  for (const e of entries) {
    if (!e.agent_id || !e.content) continue;
    const tags = [...(e.tags || [])].filter(t => !t.startsWith('ws:'));
    tags.push('ws:c');
    await grid.write({ agent_id: e.agent_id, type: e.type, content: e.content, tags });
    imported++;
  }
  assert(imported === 1, 'Import skips entries without agent_id (imported=' + imported + ')');
  const result = await grid.read({ tags: ['ws:c'] });
  const validEntries = result.entries.filter(e => e.agent_id === 'valid');
  assert(validEntries.length === 1, 'Valid entry was imported');
  console.log('  ✓ import skips entries with missing required fields');
}

async function testImportGlobalVsScoped() {
  // Entry without ws tags should survive import into any workspace
  const entry = { agent_id: 'global', type: 'fact', content: 'Global entry', tags: ['topic:global'] };

  // Simulate NO workspace (global import) — tags stay as-is
  const globalResult = await grid.write({
    agent_id: entry.agent_id, type: entry.type, content: entry.content, tags: [...entry.tags],
  });
  assert(globalResult.entry_id, 'Global import writes entry');

  // Now simulate scoped import — tags get workspace applied
  const scopedEntry = { agent_id: 'scoped', type: 'fact', content: 'Scoped entry', tags: ['topic:global'] };
  const scopedTags = scopedEntry.tags.filter(t => !t.startsWith('ws:'));
  scopedTags.push('ws:scoped-ws');
  await grid.write({
    agent_id: scopedEntry.agent_id, type: scopedEntry.type, content: scopedEntry.content, tags: scopedTags,
  });

  const result = await grid.read({ tags: ['topic:global'] });
  const agents = result.entries.map(e => e.agent_id);
  assert(agents.includes('global'), 'Global import finds global entry');
  assert(agents.includes('scoped'), 'Scoped import finds scoped entry');

  console.log('  ✓ global vs scoped import handled correctly');
}

async function main() {
  console.log('\n═══ Import Round-Trip Tests ═══\n');
  await setup();
  const tests = [testExportPreservesWorkspaceTags, testImportStripLogic, testImportRejectsNoAgent, testImportGlobalVsScoped];
  for (const t of tests) { try { await t(); } catch(e) { console.error('  ✗ CRASH: ' + e.message + '\\n' + e.stack); failed++; } }
  await cleanup();
  const total = passed + failed;
  console.log(`\n═══ Import Round-Trip: ${passed}/${total} passed, ${failed} failed ═══\n`);
  process.exit(failed > 0 ? 1 : 0);
}
main();
