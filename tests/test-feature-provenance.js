#!/usr/bin/env node
/**
 * tests/test-feature-provenance.js — Feature 5: Memory Provenance Shield
 *
 * Tests:
 * - scoreProvenance returns trust score with details
 * - quarantineEntry marks entry as quarantined
 * - reviewEntry approves or rejects quarantined entries
 */

const { Grid } = require('../reference/store.js');
const { scoreProvenance, quarantineEntry, reviewEntry } = require('../provenance.js');
const path = require('path');
const fs = require('fs');

const TEST_STORE_DIR = path.join(process.env.HOME || '/tmp', '.openclaw', 'test_provenance');
process.env.GRID_STORE_DIR = TEST_STORE_DIR;

async function setup() {
  if (fs.existsSync(TEST_STORE_DIR)) fs.rmSync(TEST_STORE_DIR, { recursive: true });
  fs.mkdirSync(TEST_STORE_DIR, { recursive: true });
}

async function cleanup() {
  if (fs.existsSync(TEST_STORE_DIR)) fs.rmSync(TEST_STORE_DIR, { recursive: true });
}

async function testScoreProvenance() {
  const grid = new Grid();
  const result = await grid.write({
    agent_id: 'test-agent', type: 'fact', tags: ['test:provenance'],
    content: 'Trusted fact',
  });

  const score = scoreProvenance(grid, result.entry_id);
  if (!score) throw new Error('No score returned');
  if (typeof score.trust_score !== 'number') throw new Error('trust_score not a number');
  if (score.trust_score < 0 || score.trust_score > 100) throw new Error(`trust_score out of range: ${score.trust_score}`);
  if (score.confirmation_count === undefined) throw new Error('confirmation_count missing');
  if (!Array.isArray(score.flags)) throw new Error('flags not an array');

  console.log('✓ testScoreProvenance: trust score calculation works');
}

async function testQuarantineEntry() {
  const grid = new Grid();
  const result = await grid.write({
    agent_id: 'test-agent', type: 'decision', tags: ['test:quarantine'],
    content: 'Questionable decision',
  });

  const qResult = await quarantineEntry(grid, result.entry_id, 'Suspicious content detected');
  if (!qResult.quarantined) throw new Error('Quarantine failed');
  if (qResult.reason !== 'Suspicious content detected') throw new Error('Reason mismatch');

  // Verify quarantine flag (schema field, survives export)
  const store = grid._store || grid._loadStore();
  const entry = store.entries.find(e => e.id === result.entry_id);
  if (!entry.quarantined) throw new Error('quarantined flag not set');
  if (entry.quarantine_reason !== 'Suspicious content detected') throw new Error('quarantine_reason mismatch');

  // Verify score reflects quarantine
  const score = scoreProvenance(grid, result.entry_id);
  if (!score.quarantined) throw new Error('quarantined flag not set in score');
  if (score.trust_score > 50) throw new Error('Trust score should be lowered for quarantined entry');

  console.log('✓ testQuarantineEntry: quarantine works and affects trust score');
}

async function testReviewEntry() {
  const grid = new Grid();
  const result = await grid.write({
    agent_id: 'test-agent', type: 'decision', tags: ['test:review'],
    content: 'Entry to be reviewed',
  });

  // Quarantine first
  await quarantineEntry(grid, result.entry_id, 'Needs review');

  // Approve
  const reviewResult = await reviewEntry(grid, result.entry_id, 'approve');
  if (!reviewResult.reviewed) throw new Error('Review failed');
  if (reviewResult.decision !== 'approved') throw new Error('Decision not approved');

  // Verify quarantine flag removed
  const store = grid._store || grid._loadStore();
  const entry = store.entries.find(e => e.id === result.entry_id);
  if (entry.quarantined) throw new Error('quarantined flag not removed after approval');

  // Reject another entry
  const result2 = await grid.write({
    agent_id: 'test-agent', type: 'decision', tags: ['test:review'],
    content: 'Entry to be rejected',
  });
  await quarantineEntry(grid, result2.entry_id, 'Spam');
  const rejectResult = await reviewEntry(grid, result2.entry_id, 'reject');
  if (rejectResult.decision !== 'rejected') throw new Error('Decision not rejected');

  console.log('✓ testReviewEntry: review workflow (approve/reject) works');
}

async function main() {
  await setup();
  let passed = 0;
  let failed = 0;
  const tests = [testScoreProvenance, testQuarantineEntry, testReviewEntry];
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
  console.log(`\n═══ Feature 5: Provenance Shield — ${passed} passed, ${failed} failed ═══`);
  process.exit(failed > 0 ? 1 : 0);
}

main();
