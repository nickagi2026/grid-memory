#!/usr/bin/env node
/**
 * tests/test-feature-staleness.js — Feature 2: Memory Staleness Detection
 *
 * Tests:
 * - findStale identifies old, unread entries
 * - findStale detects contradictions on same tag
 * - findStale detects newer state_update on same topic
 *
 * IMPORTANT: All manual entries must be saved to disk BEFORE
 * calling grid.write(), because grid.write() calls _loadStore()
 * which reads from disk.
 */

const { Grid } = require('../reference/store.js');
const { findStale } = require('../staleness.js');
const path = require('path');
const fs = require('fs');

const TEST_STORE_DIR = path.join(process.env.HOME || '/tmp', '.openclaw', 'test_staleness');
process.env.GRID_STORE_DIR = TEST_STORE_DIR;

async function setup() {
  if (fs.existsSync(TEST_STORE_DIR)) fs.rmSync(TEST_STORE_DIR, { recursive: true });
  fs.mkdirSync(TEST_STORE_DIR, { recursive: true });
}

async function cleanup() {
  if (fs.existsSync(TEST_STORE_DIR)) fs.rmSync(TEST_STORE_DIR, { recursive: true });
}

function makeEntry(id, props) {
  return {
    id, session_id: '', agent_id: 'agent-a',
    type: 'fact', tags: [], content: '',
    ttl_seconds: 86400,
    created_at: new Date().toISOString(),
    expires_at: new Date(Date.now() + 86400 * 1000).toISOString(),
    parent_entry: null, last_read_at: null,
    memory_tier: 'organization', read_count: 0, workspace_id: '',
    status: 'active', outcome: null, requires_approval: null,
    origin_trust: 'native', provenance_trust_score: null, staleness_score: null,
    ...props,
  };
}

async function testFindStaleByAge() {
  const grid = new Grid();
  const store = grid._store || grid._loadStore();

  // Save BOTH entries to disk before findStale
  store.entries.push(makeEntry('grid_stale_001', {
    agent_id: 'agent-b', type: 'fact', tags: ['topic:alpha'],
    content: 'Old stale fact',
    created_at: new Date(Date.now() - 60 * 24 * 60 * 60 * 1000).toISOString(),
  }));
  store.entries.push(makeEntry('grid_fresh_001', {
    agent_id: 'agent-a', type: 'fact', tags: ['topic:alpha'],
    content: 'Fresh fact',
  }));
  grid._saveStore();

  const stale = findStale(grid, { thresholdDays: 30 });
  const staleFound = stale.find(e => e.entry_id === 'grid_stale_001');
  if (!staleFound) throw new Error('Stale entry not detected');
  if (staleFound.staleness_score < 10) throw new Error(`Staleness score too low: ${staleFound.staleness_score}`);

  console.log('✓ testFindStaleByAge: old entry detected as stale');
}

async function testFindStaleByContradiction() {
  const grid = new Grid();
  const store = grid._store || grid._loadStore();

  // Save both decision entries directly (same tag, same type)
  store.entries.push(makeEntry('grid_stale_002', {
    agent_id: 'agent-a', type: 'decision', tags: ['topic:beta'],
    content: 'Decision: Go with option B',
    created_at: new Date(Date.now() - 40 * 24 * 60 * 60 * 1000).toISOString(),
  }));
  store.entries.push(makeEntry('grid_fresh_002', {
    agent_id: 'agent-a', type: 'decision', tags: ['topic:beta'],
    content: 'Decision: Go with option A',
    created_at: new Date(Date.now() - 1 * 24 * 60 * 60 * 1000).toISOString(),
  }));
  grid._saveStore();

  const stale = findStale(grid, { thresholdDays: 30 });
  // grid_stale_002 is 40 days old AND shares tag 'topic:beta' with another decision
  const staleFound = stale.find(e => e.entry_id === 'grid_stale_002');
  if (!staleFound) throw new Error('Contradiction stale entry not detected');
  if (!staleFound.reasons.some(r => r.includes('contradicting'))) {
    throw new Error('Contradiction reason not found in stale entry');
  }

  console.log('✓ testFindStaleByContradiction: contradiction detection works');
}

async function testFindStaleByStateUpdate() {
  const grid = new Grid();
  const store = grid._store || grid._loadStore();

  // Save old state_update entry first (MUST persist to disk before grid.write)
  store.entries.push(makeEntry('grid_stale_003', {
    agent_id: 'agent-a', type: 'state_update', tags: ['topic:gamma'],
    content: 'Old state update',
    created_at: new Date(Date.now() - 45 * 24 * 60 * 60 * 1000).toISOString(),
    read_count: 1,
  }));
  grid._saveStore(); // <-- CRITICAL: persist to disk before grid.write re-reads

  // Then write a NEWER state update via grid.write (creates fresh timestamp, re-reads from disk)
  await grid.write({
    agent_id: 'agent-b', type: 'state_update', tags: ['topic:gamma'],
    content: 'Newer state update',
  });

  // Both entries now on disk

  const stale = findStale(grid, { thresholdDays: 30 });
  const staleFound = stale.find(e => e.entry_id === 'grid_stale_003');
  if (!staleFound) throw new Error('State update stale entry not detected');
  if (!staleFound.reasons.some(r => r.includes('state_update'))) {
    throw new Error(`state_update reason not found. Reasons: ${staleFound.reasons.join(', ')}`);
  }

  console.log('✓ testFindStaleByStateUpdate: newer state_update detection works');
}

async function main() {
  await setup();
  let passed = 0;
  let failed = 0;
  const tests = [testFindStaleByAge, testFindStaleByContradiction, testFindStaleByStateUpdate];
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
  console.log(`\n═══ Feature 2: Staleness Detection — ${passed} passed, ${failed} failed ═══`);
  process.exit(failed > 0 ? 1 : 0);
}

main();
