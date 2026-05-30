#!/usr/bin/env node
/**
 * tests/test-feature-dreaming.js — Feature 4: Grid Dreaming
 *
 * Tests:
 * - Synthesis: multiple agents on same tag create synthesis entry
 * - Upgrade: facts with confirmation_count > 3 upgrade tier
 * - Retire: old unread entries get _retired tag
 */

const { Grid } = require('../reference/store.js');
const { runDreamCycle } = require('../dreaming.js');
const path = require('path');
const fs = require('fs');

const TEST_STORE_DIR = path.join(process.env.HOME || '/tmp', '.openclaw', 'test_dreaming');
process.env.GRID_STORE_DIR = TEST_STORE_DIR;

async function setup() {
  if (fs.existsSync(TEST_STORE_DIR)) fs.rmSync(TEST_STORE_DIR, { recursive: true });
  fs.mkdirSync(TEST_STORE_DIR, { recursive: true });
}

async function cleanup() {
  if (fs.existsSync(TEST_STORE_DIR)) fs.rmSync(TEST_STORE_DIR, { recursive: true });
}

async function testSynthesisCreation() {
  const grid = new Grid();

  // 3 agents write about same tag
  await grid.write({ agent_id: 'agent-a', type: 'observation', tags: ['shared:topic'], content: 'Agent A observation' });
  await grid.write({ agent_id: 'agent-b', type: 'decision', tags: ['shared:topic'], content: 'Agent B decision' });
  await grid.write({ agent_id: 'agent-c', type: 'fact', tags: ['shared:topic'], content: 'Agent C fact' });

  // Run dream cycle (disable auto-prune via options)
  const result = await runDreamCycle(grid);
  if (!result.dreamt) throw new Error('Dream cycle did not run');

  // Check for synthesis entry in store
  const synthesisAction = result.actions.find(a => a.type === 'synthesis');
  if (!synthesisAction) throw new Error('No synthesis action created');
  
  // Verify synthesis entry was created via grid.write()
  const store = grid._store || grid._loadStore();
  const synEntry = store.entries.find(e => e.type === 'synthesis' && e.agent_id === '_dream');
  if (!synEntry) throw new Error('Synthesis entry not found in store');

  console.log('✓ testSynthesisCreation: synthesis entry created from multiple agents');
}

async function testFactUpgrade() {
  const grid = new Grid();

  // Write a fact
  const fact1 = await grid.write({ agent_id: 'agent-a', type: 'fact', tags: ['topic:upgrade'], content: 'Key fact about topic', memory_tier: 'working' });

  // Add 4 entries referencing it as parent
  for (let i = 0; i < 4; i++) {
    await grid.write({
      agent_id: 'agent-x',
      type: 'observation',
      tags: ['topic:upgrade'],
      content: `Confirmation ${i} of key fact`,
      parent_entry: fact1.entry_id,
    });
  }

  const result = await runDreamCycle(grid);
  const upgradeAction = result.actions.find(a => a.type === 'upgrade');
  if (!upgradeAction) throw new Error('No upgrade action');

  const store = grid._store || grid._loadStore();
  const upgradedEntry = store.entries.find(e => e.id === fact1.entry_id);
  if (upgradedEntry.memory_tier !== 'organization') throw new Error('Fact not upgraded to organization tier');

  console.log('✓ testFactUpgrade: fact upgraded to organization tier');
}

async function testStaleRetirement() {
  const grid = new Grid();

  const oldEntry = {
    id: 'grid_retire_test',
    session_id: '',
    agent_id: 'agent-a',
    type: 'observation',
    tags: ['topic:stale'],
    content: 'Old unread entry',
    ttl_seconds: 3600, // 1 hour TTL
    created_at: new Date(Date.now() - 10 * 24 * 60 * 60 * 1000).toISOString(), // 10 days ago
    expires_at: new Date(Date.now() + 3600 * 1000).toISOString(),
    parent_entry: null,
    last_read_at: null,
    memory_tier: 'working',
    read_count: 0,
    workspace_id: '',
    status: 'active',
    outcome: null,
    requires_approval: null,
    origin_trust: 'native',
    provenance_trust_score: null,
    staleness_score: null,
  };

  const store = grid._store || grid._loadStore();
  store.entries.push(oldEntry);
  grid._saveStore();

  const result = await runDreamCycle(grid, { ttlMultiplier: 1 }); // instant retirement
  const retireAction = result.actions.find(a => a.type === 'retire');
  if (!retireAction) throw new Error('No retire action for old unread entry');

  const retired = store.entries.find(e => e.id === 'grid_retire_test');
  if (!retired.tags.includes('_retired')) throw new Error('Entry not tagged as _retired');

  console.log('✓ testStaleRetirement: stale entry retired');
}

async function main() {
  await setup();
  let passed = 0;
  let failed = 0;
  const tests = [testSynthesisCreation, testFactUpgrade, testStaleRetirement];
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
  console.log(`\n═══ Feature 4: Grid Dreaming — ${passed} passed, ${failed} failed ═══`);
  process.exit(failed > 0 ? 1 : 0);
}

main();
