#!/usr/bin/env node
/**
 * tests/test-setup-wizard.js — Setup Wizard Async Test
 *
 * Verifies that applyConfig() returns only after seed entries exist.
 */

'use strict';

const fs = require('fs');
const path = require('path');
const os = require('os');

const TEST_DIR = path.join(os.tmpdir(), 'test_wizard_' + Date.now());
process.env.GRID_STORE_DIR = TEST_DIR;

const { Grid } = require('../reference/store.js');
const { wizard, applyConfig, isConfigured } = require('../setup-wizard.js');

let passed = 0;
let failed = 0;

function assert(condition, msg) {
  if (condition) { passed++; return; }
  console.error(`  ✗ ${msg}`);
  failed++;
}

async function setup() {
  if (fs.existsSync(TEST_DIR)) fs.rmSync(TEST_DIR, { recursive: true });
  fs.mkdirSync(TEST_DIR, { recursive: true });
}

async function cleanup() {
  if (fs.existsSync(TEST_DIR)) fs.rmSync(TEST_DIR, { recursive: true });
}

async function testIsConfiguredAsync() {
  const grid = new Grid();
  const status = await isConfigured(grid);
  assert(typeof status === 'object', 'isConfigured returns an object');
  assert('configured' in status, 'isConfigured has configured field');
  assert('hasEntries' in status, 'isConfigured has hasEntries field');
  assert(!status.hasEntries, 'Fresh Grid reports no entries');
  console.log('  ✓ isConfigured is async and correctly reports empty Grid');
}

async function testWizardReturnsSteps() {
  const grid = new Grid();
  const result = await wizard(grid);
  assert(result.needs_setup === true, 'Empty Grid needs setup');
  assert(Array.isArray(result.steps), 'Wizard returns steps array');
  assert(result.steps.length === 3, 'Wizard returns 3 steps (purpose, agents, compliance)');
  assert(result.steps[0].id === 'purpose', 'First step is purpose');
  console.log('  ✓ wizard returns steps for unconfigured Grid');
}

async function testConfiguredGridNoSteps() {
  const grid = new Grid();
  // Write an entry so Grid is configured
  await grid.write({ agent_id: 'test', type: 'fact', content: 'Pre-configured', tags: ['test'] });
  const result = await wizard(grid);
  assert(result.needs_setup === false, 'Configured Grid does not need setup');
  assert(result.configured === true, 'Configured Grid reports configured');
  console.log('  ✓ wizard detects configured Grid');
}

async function testApplyConfigSeedsData() {
  const grid = new Grid();
  const result = await applyConfig({
    purpose: 'Agent team coordination',
    agents: '1–5',
    compliance: 'No',
  }, grid);

  assert(result.configured === true, 'applyConfig returns configured');
  assert(typeof result === 'object', 'applyConfig returns object');

  // Verify entries were created (seed completes before applyConfig returns)
  const info = await grid.info();
  assert(info.total_entries > 0, `Seed created entries (got ${info.total_entries})`);

  console.log('  ✓ applyConfig seeds data (async — entries exist after return)');
}

async function main() {
  console.log('\n═══ Setup Wizard Tests ═══\n');
  await setup();
  const tests = [testIsConfiguredAsync, testWizardReturnsSteps, testConfiguredGridNoSteps, testApplyConfigSeedsData];
  for (const test of tests) {
    try { await test(); } catch (e) { console.error(`  ✗ CRASH: ${e.message}`); failed++; }
  }
  await cleanup();
  const total = passed + failed;
  console.log(`\n═══ Setup Wizard: ${passed}/${total} passed, ${failed} failed ═══\n`);
  process.exit(failed > 0 ? 1 : 0);
}

main();
