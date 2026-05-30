#!/usr/bin/env node
/**
 * tests/test-feature-constitution.js — Feature 7: Constitutional Memory
 *
 * Tests:
 * - registerConstitution stores rules per workspace
 * - validateEntry enforces required words
 * - validateEntry blocks forbidden patterns
 * - removeConstitution deletes workspace rules
 */

const { registerConstitution, listConstitutions, removeConstitution, validateEntry } = require('../constitution.js');
const fs = require('fs');
const path = require('path');
const os = require('os');

const TEST_STORE_DIR = path.join(os.tmpdir(), '.openclaw', 'test_constitution');
process.env.GRID_STORE_DIR = TEST_STORE_DIR;

async function setup() {
  if (fs.existsSync(TEST_STORE_DIR)) fs.rmSync(TEST_STORE_DIR, { recursive: true });
  fs.mkdirSync(TEST_STORE_DIR, { recursive: true });
}

async function cleanup() {
  if (fs.existsSync(TEST_STORE_DIR)) fs.rmSync(TEST_STORE_DIR, { recursive: true });
}

async function testRegisterAndList() {
  const result = registerConstitution('workspace-a', [
    { name: 'All decisions need rationale', entryTypes: ['decision'], requiredWords: ['because', 'rationale'] },
    { name: 'No API keys', blockedPatterns: ['sk-[A-Za-z0-9]{32,}'] },
  ], 'block');

  if (!result.registered) throw new Error('Registration failed');
  if (result.rule_count !== 2) throw new Error(`Expected 2 rules, got ${result.rule_count}`);

  // List for specific workspace
  const listed = listConstitutions('workspace-a');
  if (!listed.rules || listed.rules.length !== 2) throw new Error('List rules count mismatch');
  if (listed.enforceMode !== 'block') throw new Error('Enforce mode mismatch');

  console.log('✓ testRegisterAndList: constitution registration and listing works');
}

async function testValidateRequiredWords() {
  registerConstitution('workspace-b', [
    { name: 'Decisions need rationale', entryTypes: ['decision'], requiredWords: ['because', 'rationale'] },
  ], 'block');

  // Entry that passes
  const passResult = validateEntry({ type: 'decision', content: 'We chose A because B, rationale: cost' }, 'workspace-b');
  if (!passResult.valid) throw new Error('Valid entry should pass');
  if (passResult.blocked) throw new Error('Valid entry should not be blocked');

  // Entry that fails
  const failResult = validateEntry({ type: 'decision', content: 'We chose A.' }, 'workspace-b');
  if (failResult.valid) throw new Error('Entry without rationale should fail');
  if (!failResult.blocked) throw new Error('Entry without rationale should be blocked');
  if (failResult.errors.length === 0) throw new Error('Should have at least one error');

  console.log('✓ testValidateRequiredWords: required words validation works');
}

async function testValidateBlockedPatterns() {
  registerConstitution('workspace-c', [
    { name: 'No secrets', blockedPatterns: ['ghp_[A-Za-z0-9]{36}'] },
  ], 'block');

  const failResult = validateEntry({ type: 'fact', content: 'My key is ghp_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0' }, 'workspace-c');
  if (failResult.valid) throw new Error('Should detect blocked pattern');
  if (!failResult.blocked) throw new Error('Should be blocked');

  console.log('✓ testValidateBlockedPatterns: blocked pattern detection works');
}

async function testRemoveConstitution() {
  registerConstitution('workspace-d', [{ name: 'Rule 1', requiredWords: ['test'] }], 'validate');
  
  const removeResult = removeConstitution('workspace-d');
  if (!removeResult.removed) throw new Error('Remove failed');

  const listResult = listConstitutions('workspace-d');
  if (listResult.rules.length !== 0) throw new Error('Rules should be empty after removal');

  console.log('✓ testRemoveConstitution: constitution removal works');
}

async function main() {
  await setup();
  let passed = 0;
  let failed = 0;
  const tests = [testRegisterAndList, testValidateRequiredWords, testValidateBlockedPatterns, testRemoveConstitution];
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
  console.log(`\n═══ Feature 7: Constitutional Memory — ${passed} passed, ${failed} failed ═══`);
  process.exit(failed > 0 ? 1 : 0);
}

main();
