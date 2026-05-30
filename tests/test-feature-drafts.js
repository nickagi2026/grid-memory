#!/usr/bin/env node
/**
 * tests/test-feature-drafts.js — Feature 3: Draft Entries & Memory Diff
 *
 * Tests:
 * - Write draft entry, verify it's hidden from normal reads
 * - Read with include_drafts: true reveals drafts
 * - Promote draft to active
 * - requires_approval field works
 */

const { Grid } = require('../reference/store.js');
const path = require('path');
const fs = require('fs');

const TEST_STORE_DIR = path.join(process.env.HOME || '/tmp', '.openclaw', 'test_drafts');
process.env.GRID_STORE_DIR = TEST_STORE_DIR;

async function setup() {
  if (fs.existsSync(TEST_STORE_DIR)) fs.rmSync(TEST_STORE_DIR, { recursive: true });
  fs.mkdirSync(TEST_STORE_DIR, { recursive: true });
}

async function cleanup() {
  if (fs.existsSync(TEST_STORE_DIR)) fs.rmSync(TEST_STORE_DIR, { recursive: true });
}

async function testDraftHiddenFromNormalReads() {
  const grid = new Grid();

  // Write a draft entry
  const draftResult = await grid.write({
    agent_id: 'agent-a',
    type: 'decision',
    tags: ['test:drafts'],
    content: 'Draft decision pending review',
    status: 'draft',
  });

  if (!draftResult.entry_id) throw new Error('No entry_id from draft write');
  if (draftResult.status !== 'draft') throw new Error('Status not persisted as draft');

  // Normal read should NOT include draft
  const normalRead = await grid.read({ tags: ['test:drafts'] });
  const foundInNormal = normalRead.entries.find(e => e.id === draftResult.entry_id);
  if (foundInNormal) throw new Error('Draft entry visible in normal read');

  // Read with include_drafts should include it
  const draftRead = await grid.read({ tags: ['test:drafts'], include_drafts: true });
  const foundInDraft = draftRead.entries.find(e => e.id === draftResult.entry_id);
  if (!foundInDraft) throw new Error('Draft not visible when include_drafts is true');
  if (foundInDraft.status !== 'draft') throw new Error('Status not exposed in read');

  console.log('✓ testDraftHiddenFromNormalReads: draft filtering works');
}

async function testPromoteDraft() {
  const grid = new Grid();

  const draftResult = await grid.write({
    agent_id: 'agent-a',
    type: 'fact',
    tags: ['test:promote'],
    content: 'Draft fact to be promoted',
    status: 'draft',
  });

  // Promote
  const promoteResult = await grid.promoteEntry(draftResult.entry_id);
  if (!promoteResult.found) throw new Error('Promote failed');
  if (promoteResult.status !== 'active') throw new Error('Promoted status not active');

  // Now should be visible in normal reads
  const normalRead = await grid.read({ tags: ['test:promote'] });
  const found = normalRead.entries.find(e => e.id === draftResult.entry_id);
  if (!found) throw new Error('Promoted draft not visible in normal read');
  if (found.status !== 'active') throw new Error('Promoted status not active in read');

  console.log('✓ testPromoteDraft: draft promotion works');
}

async function testRequiresApproval() {
  const grid = new Grid();

  const result = await grid.write({
    agent_id: 'agent-a',
    type: 'decision',
    tags: ['test:approval'],
    content: 'Decision needing approval',
    status: 'draft',
    requires_approval: 'human',
  });

  if (result.requires_approval !== 'human') throw new Error('requires_approval not persisted');

  const store = grid._store || grid._loadStore();
  const entry = store.entries.find(e => e.id === result.entry_id);
  if (entry.requires_approval !== 'human') throw new Error('requires_approval not stored');

  console.log('✓ testRequiresApproval: requires_approval field works');
}

async function main() {
  await setup();
  let passed = 0;
  let failed = 0;
  const tests = [testDraftHiddenFromNormalReads, testPromoteDraft, testRequiresApproval];
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
  console.log(`\n═══ Feature 3: Draft Entries — ${passed} passed, ${failed} failed ═══`);
  process.exit(failed > 0 ? 1 : 0);
}

main();
