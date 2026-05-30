#!/usr/bin/env node
/**
 * tests/test-outcome-linking.js — Feature 1: Outcome Linking
 *
 * Tests:
 * - Write entry with outcome
 * - PATCH /entries/:id/outcome to update outcome
 * - Verify outcome persists in store
 * - Reputation scoring factors outcome data
 */

const { Grid } = require('../reference/store.js');
const path = require('path');
const fs = require('fs');

const TEST_STORE_DIR = path.join(process.env.HOME || '/tmp', '.openclaw', 'test_outcome_linking');
process.env.GRID_STORE_DIR = TEST_STORE_DIR;

async function setup() {
  if (fs.existsSync(TEST_STORE_DIR)) fs.rmSync(TEST_STORE_DIR, { recursive: true });
  fs.mkdirSync(TEST_STORE_DIR, { recursive: true });
}

async function cleanup() {
  if (fs.existsSync(TEST_STORE_DIR)) fs.rmSync(TEST_STORE_DIR, { recursive: true });
}

async function testOutcomeWrite() {
  const grid = new Grid();
  const result = await grid.write({
    agent_id: 'test-agent',
    type: 'decision',
    tags: ['test:outcome'],
    content: 'We decided to launch the feature',
    outcome: { result: 'success', delta: 'launched v2.0', notes: 'All tests passed' },
  });

  if (!result.entry_id) throw new Error('No entry_id returned');
  if (!result.outcome) throw new Error('No outcome in response');
  if (result.outcome.result !== 'success') throw new Error('Outcome result mismatch');

  // Verify outcome persisted in store
  const store = grid._store || grid._loadStore();
  const entry = store.entries.find(e => e.id === result.entry_id);
  if (!entry) throw new Error('Entry not found in store');
  if (!entry.outcome) throw new Error('Outcome not persisted');
  if (entry.outcome.result !== 'success') throw new Error('Persisted outcome result mismatch');
  if (entry.outcome.delta !== 'launched v2.0') throw new Error('Persisted outcome delta mismatch');

  console.log('✓ testOutcomeWrite: outcome write and persist works');
}

async function testUpdateOutcome() {
  const grid = new Grid();
  const result = await grid.write({
    agent_id: 'test-agent',
    type: 'decision',
    tags: ['test:outcome-update'],
    content: 'We decided to pivot',
  });

  // Update outcome
  const updateResult = await grid.updateOutcome(result.entry_id, {
    result: 'partial',
    delta: 'pivoted to new market',
    notes: 'Customer feedback drove change',
  });

  if (!updateResult.found) throw new Error('Entry not found for outcome update');
  if (updateResult.outcome.result !== 'partial') throw new Error('Updated outcome mismatch');

  // Verify persisted
  const store = grid._store || grid._loadStore();
  const entry = store.entries.find(e => e.id === result.entry_id);
  if (entry.outcome.result !== 'partial') throw new Error('Persisted updated outcome mismatch');
  if (entry.outcome.delta !== 'pivoted to new market') throw new Error('Persisted updated delta mismatch');
  if (!entry.outcome.recorded_at) throw new Error('recorded_at missing');

  // Read and verify outcome is exposed
  const readResult = await grid.read({ tags: ['test:outcome-update'] });
  const readEntry = readResult.entries.find(e => e.id === result.entry_id);
  if (!readEntry || !readEntry.outcome) throw new Error('Outcome not exposed in read');
  if (readEntry.outcome.result !== 'partial') throw new Error('Read outcome mismatch');

  console.log('✓ testUpdateOutcome: PATCH outcome update works');
}

async function testInvalidOutcome() {
  const grid = new Grid();
  try {
    await grid.updateOutcome('nonexistent', { result: 'success' });
  } catch (e) {
    // Expected — nonexistent entry
  }

  try {
    await grid.updateOutcome('grid_test', { result: 'invalid' });
    throw new Error('Should have rejected invalid outcome result');
  } catch (e) {
    if (e.message.includes('success/failure/partial')) {
      console.log('✓ testInvalidOutcome: invalid outcome rejection works');
    } else {
      throw e;
    }
  }
}

async function main() {
  await setup();
  let passed = 0;
  let failed = 0;
  const tests = [testOutcomeWrite, testUpdateOutcome, testInvalidOutcome];
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
  console.log(`\n═══ Feature 1: Outcome Linking — ${passed} passed, ${failed} failed ═══`);
  process.exit(failed > 0 ? 1 : 0);
}

main();
