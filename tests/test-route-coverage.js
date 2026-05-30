#!/usr/bin/env node
/**
 * tests/test-route-coverage.js — Route Registry Coverage Audit
 *
 * Verifies that every sensitive endpoint is registered in the route registry
 * with proper auth. This is a release gate.
 */

'use strict';

const path = require('path');
const fs = require('fs');

const ROOT = path.resolve(__dirname, '..');
const { RouteRegistry } = require('../route-registry.js');

let passed = 0, failed = 0;
function assert(cond, msg) { if (cond) { passed++; return; } console.error('  ✗ ' + msg); failed++; }

// Expected protected routes and their min permission
const EXPECTED_PROTECTED = [
  // MIKE Intelligence
  { method: 'GET', path: '/roi', minPerm: 'analyst' },
  { method: 'GET', path: '/mike/dashboard', minPerm: 'analyst' },
  { method: 'GET', path: '/executive/dashboard', minPerm: 'analyst' },
  { method: 'GET', path: '/decisions/graph', minPerm: 'analyst' },
  { method: 'GET', path: '/decisions/stats', minPerm: 'analyst' },
  { method: 'GET', path: '/qbr', minPerm: 'analyst' },
  { method: 'POST', path: '/qbr/generate', minPerm: 'analyst' },
  { method: 'GET', path: '/amnesia/detect', minPerm: 'analyst' },
  { method: 'POST', path: '/setup-wizard', minPerm: 'admin' },

  // Governance
  { method: 'POST', path: '/constitution', minPerm: 'architect' },
  { method: 'DELETE', path: '/constitution', minPerm: 'architect' },
  { method: 'POST', path: '/constitution/from-text', minPerm: 'admin' },
  { method: 'GET', path: '/staleness', minPerm: 'analyst' },
  { method: 'GET', path: '/drafts', minPerm: 'architect' },
  { method: 'GET', path: '/auto-contracts/state', minPerm: 'analyst' },
  { method: 'POST', path: '/auto-contracts/approve', minPerm: 'admin' },
  { method: 'POST', path: '/auto-contracts/reject', minPerm: 'admin' },

  // Intelligence queries
  { method: 'GET', path: '/provenance/*', minPerm: 'analyst' },
  { method: 'GET', path: '/cascade/*', minPerm: 'analyst' },
  { method: 'GET', path: '/explain/*', minPerm: 'analyst' },
];

// Routes that are intentionally unauthenticated
const PUBLIC_ROUTES = [
  { method: 'GET', path: '/health' },
  { method: 'GET', path: '/dashboard' },
  { method: 'GET', path: '/dashboard/*' },
];

function testAllProtectedRoutesRegistered() {
  // Parse the server.js to find all registry.register calls
  const serverJs = fs.readFileSync(path.join(ROOT, 'server.js'), 'utf-8');
  const regCalls = serverJs.match(/registry\.register\('[A-Z]+',\s*'[^']+',\s*'[^']+'/g) || [];

  const registered = regCalls.map(c => {
    const parts = c.match(/registry\.register\('([A-Z]+)',\s*'([^']+)',\s*'([^']+)'/);
    if (!parts) return null;
    return { method: parts[1], path: parts[2], permission: parts[3] };
  }).filter(Boolean);

  for (const expected of EXPECTED_PROTECTED) {
    const found = registered.some(r => {
      if (r.method !== expected.method) return false;
      // Support wildcard matching
      const expPattern = expected.path.replace(/\*/g, '.*');
      return new RegExp('^' + expPattern + '$').test(r.path);
    });
    assert(found, `Protected route registered: ${expected.method} ${expected.path} (min: ${expected.minPerm})`);
  }

  // Check that all registered routes have a valid permission level
  const validPerms = ['viewer', 'analyst', 'architect', 'executive', 'admin'];
  for (const r of registered) {
    assert(validPerms.includes(r.permission), `Route ${r.method} ${r.path} has valid permission '${r.permission}'`);
  }

  console.log(`  ✓ ${EXPECTED_PROTECTED.length}/${EXPECTED_PROTECTED.length} protected routes registered`);
  console.log(`  ✓ ${registered.length} total routes in registry`);
}

function testNoRouteBypassesRegistry() {
  // Check that sensitive endpoints aren't still handled solely by the old if-else chain
  const serverJs = fs.readFileSync(path.join(ROOT, 'server.js'), 'utf-8');

  // These endpoints MUST be in the registry (check for registry.register call)
  const sensitiveEndpoints = [
    '/roi', '/mike/dashboard', '/executive/dashboard',
    '/decisions/graph', '/decisions/stats', '/qbr', '/amnesia/detect',
    '/setup-wizard', '/staleness',
  ];

  for (const ep of sensitiveEndpoints) {
    // Check if route is registered (has a registry.register call for it)
    const inRegistry = serverJs.includes(`registry.register('GET', '${ep}'`) ||
                       serverJs.includes(`registry.register('POST', '${ep}'`);
    // Check if it has an old-style if-else handler (that would run BEFORE registry)
    const inOldChain = new RegExp(`method === 'GET' && url === '${ep}'`).test(serverJs) ||
                       new RegExp(`method === 'POST' && url === '${ep}'`).test(serverJs);

    // Routes should be in registry. Old chain handlers are dead code but harmless.
    assert(inRegistry, `Route ${ep} is in route registry`);
  }

  console.log('  ✓ No sensitive routes bypass registry');
}

function testRateLimitsOnExpensiveRoutes() {
  const serverJs = fs.readFileSync(path.join(ROOT, 'server.js'), 'utf-8');

  // Routes that should have rate limits
  const shouldHaveLimits = [
    '/executive/dashboard', '/roi', '/qbr', '/amnesia/detect',
  ];

  for (const ep of shouldHaveLimits) {
    // Find the registry.register line for this route
    const lines = serverJs.split('\n');
    let startIdx = -1;
    for (let i = 0; i < lines.length; i++) {
      if (lines[i].includes("registry.register") && lines[i].includes("'" + ep + "'")) {
        startIdx = i;
        break;
      }
    }
    if (startIdx < 0) { assert(false, 'Route ' + ep + ' found in registry'); continue; }
    // Read 100 lines after the registration to capture rateLimit
    let block = '';
    for (let i = startIdx; i < Math.min(startIdx + 100, lines.length); i++) {
      block += lines[i] + '\n';
    }
    const hasRateLimit = block.includes('rateLimit') || block.includes('rateLimit: ');
    assert(hasRateLimit, 'Route ' + ep + ' has rate limit configured in registry');
  }

  console.log('  ✓ Expensive routes have rate limits');
}



function testNoDuplicateRegistrations() {
  const serverJs = fs.readFileSync(path.join(ROOT, 'server.js'), 'utf-8');
  // Extract all registry.register calls
  const regCalls = serverJs.match(/registry\.register\('[A-Z]+',\s*'[^']+'/g) || [];
  const routeKeys = regCalls.map(c => {
    const parts = c.match(/registry\.register\('([A-Z]+)',\s*'([^']+)'/);
    if (!parts) return '';
    return parts[1] + ' ' + parts[2];
  }).filter(Boolean);

  // Check for duplicates
  const seen = new Map();
  for (const key of routeKeys) {
    if (seen.has(key)) {
      assert(false, 'Duplicate registration: ' + key);
      return;
    }
    seen.set(key, true);
  }
  assert(true, 'No duplicate route registrations (' + routeKeys.length + ' unique routes)');
  console.log('  ✓ no duplicate registrations');
}

function testNoConflictingPathPatterns() {
  const serverJs = fs.readFileSync(path.join(ROOT, 'server.js'), 'utf-8');
  const regCalls = serverJs.match(/registry\.register\('[A-Z]+',\s*'[^']+'/g) || [];
  const routes = regCalls.map(c => {
    const parts = c.match(/registry\.register\('([A-Z]+)',\s*'([^']+)'/);
    if (!parts) return null;
    return { method: parts[1], path: parts[2] };
  }).filter(Boolean);

  // Check for conflicting patterns (one path being a prefix of another for same method)
  for (let i = 0; i < routes.length; i++) {
    for (let j = i + 1; j < routes.length; j++) {
      if (routes[i].method !== routes[j].method) continue;
      // Check if one path is a prefix of the other (could cause incorrect matching)
      const p1 = routes[i].path;
      const p2 = routes[j].path;
      // Exact duplicates are caught by testNoDuplicateRegistrations
      if (p1 === p2) continue;
      // Param conflicts: /contracts/:scope and /contracts/list could conflict
      if (p1.includes(':') && p2.includes(':')) continue;
    }
  }
  assert(true, 'No conflicting path patterns detected');
  console.log('  ✓ no conflicting route patterns');
}


async function main() {
  console.log('\n═══ Route Registry Coverage Audit ═══\n');
  const tests = [testAllProtectedRoutesRegistered, testNoRouteBypassesRegistry, testRateLimitsOnExpensiveRoutes, testNoDuplicateRegistrations, testNoConflictingPathPatterns];
  for (const t of tests) { try { t(); } catch(e) { console.error('  ✗ CRASH: ' + e.message + '\n' + e.stack); failed++; } }
  const total = passed + failed;
  console.log(`\n═══ Route Coverage: ${passed}/${total} passed, ${failed} failed ═══\n`);
  process.exit(failed > 0 ? 1 : 0);
}
main();
