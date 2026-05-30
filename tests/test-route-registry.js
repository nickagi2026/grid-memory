#!/usr/bin/env node
/**
 * tests/test-route-registry.js — Route Registry Tests
 *
 * Verifies every registered route requires the correct permission level.
 */

'use strict';

const path = require('path');
const { RouteRegistry, PERMISSION_LEVELS } = require('../route-registry.js');

let passed = 0;
let failed = 0;

function assert(condition, msg) {
  if (condition) { passed++; return; }
  console.error(`  ✗ ${msg}`);
  failed++;
}

function testRegistryCreation() {
  const r = new RouteRegistry();
  assert(r instanceof RouteRegistry, 'RouteRegistry can be instantiated');
  assert(Array.isArray(r._routes), 'Registry has routes array');
  assert(r._routes.length === 0, 'Registry starts empty');
  console.log('  ✓ registry creation works');
}

function testRegisterAndMatch() {
  const r = new RouteRegistry();
  r.register('GET', '/test', 'viewer', async () => {});

  const match = r.match('GET', '/test');
  assert(match !== null, 'Registered route matches');
  assert(match.route.permission === 'viewer', 'Matched route has correct permission');
  assert(match.route.method === 'GET', 'Matched route has correct method');

  const noMatch = r.match('POST', '/test');
  assert(noMatch === null, 'Wrong method does not match');

  const notFound = r.match('GET', '/nonexistent');
  assert(notFound === null, 'Unknown route does not match');

  console.log('  ✓ register and match works');
}

function testAllPermissionLevels() {
  const levels = ['viewer', 'analyst', 'architect', 'executive', 'admin'];
  for (const level of levels) {
    const r = new RouteRegistry();
    try {
      r.register('GET', '/' + level, level, async () => {});
      assert(true, `Permission level "${level}" can be registered`);
    } catch (e) {
      assert(false, `Permission level "${level}" failed: ${e.message}`);
    }
  }
  console.log('  ✓ all permission levels register correctly');
}

function testInvalidPermissionRejected() {
  const r = new RouteRegistry();
  try {
    r.register('GET', '/bad', 'superadmin', async () => {});
    assert(false, 'Invalid permission should throw');
  } catch (e) {
    assert(e.message.includes('Invalid permission level'), `Invalid permission rejected: ${e.message}`);
  }
  console.log('  ✓ invalid permission levels are rejected');
}

function testViewerPermission() {
  // This tests the P0 fix — viewer: 0 should not be falsy
  const r = new RouteRegistry();
  try {
    r.register('GET', '/viewer-test', 'viewer', async () => {});
    assert(true, 'viewer permission registers successfully (P0 fix verified)');
  } catch (e) {
    assert(false, `viewer permission failed: ${e.message}`);
  }
  const match = r.match('GET', '/viewer-test');
  assert(match !== null, 'viewer permission route matches');
  assert(match.route.permission === 'viewer', 'viewer permission preserved in route');
  console.log('  ✓ viewer permission (P0 bug fix) works correctly');
}

function testPatternMatching() {
  const r = new RouteRegistry();
  r.register('GET', '/items/:id', 'viewer', async () => {});
  r.register('GET', '/prefix/*', 'analyst', async () => {});

  const paramMatch = r.match('GET', '/items/abc123');
  assert(paramMatch !== null, ':param pattern matches');
  assert(paramMatch.params.id === 'abc123', ':param captures value');

  const wildcardMatch = r.match('GET', '/prefix/anything/here');
  assert(wildcardMatch !== null, 'wildcard pattern matches');

  console.log('  ✓ pattern matching with :param and * works');
}

function testMissingHandler() {
  const r = new RouteRegistry();
  try {
    r.register('GET', '/test', 'viewer', null);
    assert(false, 'Missing handler should throw');
  } catch (e) {
    assert(e.message.includes('handler'), 'Missing handler rejection: ' + e.message);
  }
  console.log('  ✓ missing handler rejected');
}

async function main() {
  console.log('\n═══ Route Registry Tests ═══\n');
  const tests = [testRegistryCreation, testRegisterAndMatch, testAllPermissionLevels, testInvalidPermissionRejected, testViewerPermission, testPatternMatching, testMissingHandler];
  for (const test of tests) {
    try { await test(); } catch (e) { console.error(`  ✗ CRASH: ${e.message}`); failed++; }
  }
  const total = passed + failed;
  console.log(`\n═══ Route Registry: ${passed}/${total} passed, ${failed} failed ═══\n`);
  process.exit(failed > 0 ? 1 : 0);
}

main();
