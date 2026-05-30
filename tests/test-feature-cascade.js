#!/usr/bin/env node
/**
 * tests/test-feature-cascade.js — Feature 6: Cascade Firewall
 *
 * Tests:
 * - trackPropagation records propagation links
 * - getCascade builds full tree
 * - recallEntry marks source + descendants
 * - getContaminationStatus checks ancestry
 */

const { Grid } = require('../reference/store.js');
const { trackPropagation, getCascade, recallEntry, getContaminationStatus } = require('../cascade.js');
const path = require('path');
const fs = require('fs');

const TEST_STORE_DIR = path.join(process.env.HOME || '/tmp', '.openclaw', 'test_cascade');
process.env.GRID_STORE_DIR = TEST_STORE_DIR;

async function setup() {
  if (fs.existsSync(TEST_STORE_DIR)) fs.rmSync(TEST_STORE_DIR, { recursive: true });
  fs.mkdirSync(TEST_STORE_DIR, { recursive: true });
}

async function cleanup() {
  if (fs.existsSync(TEST_STORE_DIR)) fs.rmSync(TEST_STORE_DIR, { recursive: true });
}

async function testTrackAndGetCascade() {
  const grid = new Grid();

  // Create source entry
  const source = await grid.write({
    agent_id: 'agent-a', type: 'decision', tags: ['topic:cascade'],
    content: 'Original decision',
  });

  // Create child entry (with parent_entry)
  const child = await grid.write({
    agent_id: 'agent-b', type: 'observation', tags: ['topic:cascade'],
    content: 'Child observation based on decision',
    parent_entry: source.entry_id,
  });

  // Track propagation (done automatically by server.js, but test directly)
  trackPropagation(grid, source.entry_id, child.entry_id, 'test-workspace');

  // Get cascade tree
  const cascade = getCascade(grid, source.entry_id);
  if (!cascade.tree) throw new Error('No tree returned');
  if (cascade.source_agent !== 'agent-a') throw new Error('Source agent mismatch');
  if (cascade.node_count < 2) throw new Error('Tree should have at least 2 nodes');

  console.log('✓ testTrackAndGetCascade: propagation tracking and cascade tree works');
}

async function testRecallAndContamination() {
  const grid = new Grid();

  // Create chain: source → child → grandchild
  const source = await grid.write({
    agent_id: 'agent-a', type: 'decision', tags: ['topic:recall'],
    content: 'Original source',
  });

  const child = await grid.write({
    agent_id: 'agent-b', type: 'observation', tags: ['topic:recall'],
    content: 'Child entry',
    parent_entry: source.entry_id,
  });

  const grandchild = await grid.write({
    agent_id: 'agent-c', type: 'fact', tags: ['topic:recall'],
    content: 'Grandchild entry',
    parent_entry: child.entry_id,
  });

  // Track prop
  trackPropagation(grid, source.entry_id, child.entry_id, '');
  trackPropagation(grid, child.entry_id, grandchild.entry_id, '');

  // Recall source
  const recallResult = await recallEntry(grid, source.entry_id, 'Poisoned data');
  if (!recallResult.recalled) throw new Error('Recall failed');
  if (recallResult.total_affected < 2) throw new Error('Should affect at least source + descendants');
  if (!recallResult.recalled_entries.includes(source.entry_id)) throw new Error('Source not in recalled list');
  if (!recallResult.contaminated_entries.includes(child.entry_id)) throw new Error('Child not in contaminated list');

  // Check contamination status
  const childStatus = getContaminationStatus(grid, child.entry_id);
  if (!childStatus.contaminated) throw new Error('Child should be contaminated');

  const grandchildStatus = getContaminationStatus(grid, grandchild.entry_id);
  if (!grandchildStatus.contaminated) throw new Error('Grandchild should be contaminated via ancestry');

  console.log('✓ testRecallAndContamination: recall + contamination detection works');
}

async function testContaminationCleanEntry() {
  const grid = new Grid();
  const clean = await grid.write({
    agent_id: 'agent-a', type: 'fact', tags: ['topic:clean'],
    content: 'Clean entry with no bad ancestry',
  });

  const status = getContaminationStatus(grid, clean.entry_id);
  if (status.contaminated) throw new Error('Clean entry should not be contaminated');

  console.log('✓ testContaminationCleanEntry: clean entries not falsely flagged');
}

async function main() {
  await setup();
  let passed = 0;
  let failed = 0;
  const tests = [testTrackAndGetCascade, testRecallAndContamination, testContaminationCleanEntry];
  for (const test of tests) {
    try {
      await test();
      passed++;
    } catch (e) {
      console.error(`✗ ${test.name}: ${e.message}`);
      failed++;
    }
    await cleanup();
    await setup();
  }
  await cleanup();
  console.log(`\n═══ Feature 6: Cascade Firewall — ${passed} passed, ${failed} failed ═══`);
  process.exit(failed > 0 ? 1 : 0);
}

main();
