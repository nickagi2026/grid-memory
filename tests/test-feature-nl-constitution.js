#!/usr/bin/env node
/**
 * tests/test-feature-nl-constitution.js — Natural Language Constitution Tests
 *
 * Tests generateFromNaturalLanguage() parsing.
 */

'use strict';

const { generateFromNaturalLanguage, registerConstitution, removeConstitution, validateEntry } = require('../constitution.js');

let passed = 0, failed = 0;
function assert(cond, msg) { if (cond) { passed++; return; } console.error('  ✗ ' + msg); failed++; }

function testBlockAPIKeys() {
  const r = generateFromNaturalLanguage('Never store API keys in content');
  assert(r.rule_count >= 1, 'API key rule generated');
  const apiRule = r.rules.find(x => x.blockedPatterns && x.blockedPatterns.length > 0);
  assert(apiRule !== undefined, 'API key rule has blocked pattern');
  assert(apiRule.blockedPatterns.some(p => /api/i.test(p)), 'Blocked pattern contains api keyword');
  console.log('  ✓ "Never store API keys" generates blocked pattern');
}

function testRequireRationale() {
  const r = generateFromNaturalLanguage('All decisions must include rationale.');
  assert(r.rule_count >= 1, 'Rationale rule generated');
  const rule = r.rules[0];
  assert(rule.requiredWords.includes('rationale'), 'Required word includes rationale');
  console.log('  ✓ "Must include rationale" generates required word');
}

function testBlockPII() {
  const r = generateFromNaturalLanguage("Don't include PII in content. Never store credit cards or SSNs.");
  assert(r.rule_count >= 1, 'PII rules generated');
  const hasBlocked = r.rules.some(x => x.blockedPatterns && x.blockedPatterns.length > 0);
  assert(hasBlocked, 'PII rules have blocked patterns');
  console.log('  ✓ PII blocking generates patterns');
}

function testMultiSentence() {
  const r = generateFromNaturalLanguage('Never store API keys. All decisions must include rationale. Never include PII.');
  assert(r.rule_count === 3, `3 rules from 3 sentences (got ${r.rule_count})`);
  const hasRequired = r.rules.some(x => x.requiredWords.length > 0);
  const hasBlocked = r.rules.some(x => x.blockedPatterns.length > 0);
  assert(hasRequired && hasBlocked, 'Multi-sentence generates both required and blocked rules');
  console.log('  ✓ multi-sentence parsing generates correct rule count');
}

function testEnforceMode() {
  const r = generateFromNaturalLanguage('Never store API keys', 'block');
  assert(r.enforceMode === 'block', 'Enforce mode preserved');
  console.log('  ✓ enforce mode propagated');
}

function testEmptyText() {
  try {
    generateFromNaturalLanguage('');
    assert(false, 'Empty text should throw');
  } catch (e) {
    assert(true, 'Empty text throws: ' + e.message);
  }
  console.log('  ✓ empty text rejected');
}

function testRegisteredValidates() {
  // Clean up first
  try { removeConstitution('test-nl'); } catch(e) {}

  const parsed = generateFromNaturalLanguage('All decisions must include rationale. Never store API keys.');
  const reg = registerConstitution('test-nl', parsed.rules, 'validate');

  // Entry with rationale should pass
  const r1 = validateEntry({ type: 'decision', content: 'Use PostgreSQL. Rationale: ACID compliance.' }, 'test-nl');
  assert(r1.valid, 'Entry with rationale passes constitution');
  assert(r1.errors.length === 0, 'No errors for valid entry');

  // Entry without rationale should warn
  const r2 = validateEntry({ type: 'decision', content: 'Use PostgreSQL' }, 'test-nl');
  assert(r2.warnings.length > 0 || !r2.valid, 'Entry without rationale triggers warning');

  try { removeConstitution('test-nl'); } catch(e) {}
  console.log('  ✓ registered NL constitution validates entries');
}

function testBlockMode() {
  try { removeConstitution('test-nl-block'); } catch(e) {}

  const parsed = generateFromNaturalLanguage('Never store API keys', 'block');
  registerConstitution('test-nl-block', parsed.rules, 'block');

  const r = validateEntry({ type: 'fact', content: 'My API key is abc123' }, 'test-nl-block');
  assert(r.blocked, 'Block mode blocks API key entry');
  assert(r.errors.length > 0, 'Block mode produces errors');

  try { removeConstitution('test-nl-block'); } catch(e) {}
  console.log('  ✓ block mode rejects violations');
}

async function main() {
  console.log('\n═══ NL Constitution Tests ═══\n');
  const tests = [testBlockAPIKeys, testRequireRationale, testBlockPII, testMultiSentence, testEnforceMode, testEmptyText, testRegisteredValidates, testBlockMode];
  for (const t of tests) { try { t(); } catch(e) { console.error('  ✗ CRASH: ' + e.message); failed++; } }
  const total = passed + failed;
  console.log(`\n═══ NL Constitution: ${passed}/${total} passed, ${failed} failed ═══\n`);
  process.exit(failed > 0 ? 1 : 0);
}
main();
