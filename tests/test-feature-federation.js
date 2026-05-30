#!/usr/bin/env node
/**
 * tests/test-feature-federation.js — Feature 8: Cross-Grid Federation
 *
 * Tests:
 * - registerPeer stores peer with trust level
 * - listPeers returns peers
 * - removePeer cleans up
 * - getPeerTrust returns trust score
 *
 * Uses unique peer URLs per test to avoid cross-contamination.
 */

const fs = require('fs');
const path = require('path');
const os = require('os');

const TEST_STORE_DIR = path.join(os.tmpdir(), 'test_federation_' + Date.now());
process.env.GRID_STORE_DIR = TEST_STORE_DIR;

// Force reload the module with the correct env
delete require.cache[require.resolve('../federation.js')];
const { registerPeer, listPeers, removePeer, getPeerTrust } = require('../federation.js');

async function setup() {
  if (fs.existsSync(TEST_STORE_DIR)) fs.rmSync(TEST_STORE_DIR, { recursive: true });
  fs.mkdirSync(TEST_STORE_DIR, { recursive: true });
}

async function cleanup() {
  if (fs.existsSync(TEST_STORE_DIR)) fs.rmSync(TEST_STORE_DIR, { recursive: true });
}

async function testRegisterPeer() {
  const result = registerPeer('http://register-peer:8080', 'verified');
  if (!result.registered) throw new Error('Registration failed');
  if (result.trustLevel !== 'verified') throw new Error('Trust level mismatch');
  if (result.updated) throw new Error('Should be new, not updated');

  // Re-register (update)
  const updateResult = registerPeer('http://register-peer:8080', 'quarantine');
  if (!updateResult.updated) throw new Error('Should be an update');

  console.log('✓ testRegisterPeer: peer registration and update works');
}

async function testListAndRemovePeers() {
  registerPeer('http://list-test-a:8080', 'verified');
  registerPeer('http://list-test-b:8080', 'unverified');

  const peers = listPeers();
  // Filter to only include our test peers
  const ourPeers = peers.filter(p => p.url.startsWith('http://list-test'));
  if (ourPeers.length !== 2) throw new Error(`Expected 2 peers, got ${ourPeers.length}`);

  const removeResult = removePeer('http://list-test-a:8080');
  if (!removeResult.removed) throw new Error('Remove failed');

  const afterRemove = listPeers().filter(p => p.url.startsWith('http://list-test'));
  if (afterRemove.length !== 1) throw new Error(`Expected 1 peer after remove, got ${afterRemove.length}`);

  console.log('✓ testListAndRemovePeers: peer listing and removal works');
}

async function testGetPeerTrust() {
  registerPeer('http://trust-test:8080', 'verified');
  const trust = getPeerTrust('http://trust-test:8080');
  if (!trust.found) throw new Error('Peer not found');
  if (trust.trustLevel !== 'verified') throw new Error('Trust level mismatch');
  if (typeof trust.trustScore !== 'number') throw new Error('Trust score not a number');

  const missing = getPeerTrust('http://nonexistent:8080');
  if (missing.found) throw new Error('Nonexistent peer should not be found');

  console.log('✓ testGetPeerTrust: trust score retrieval works');
}

async function main() {
  await setup();
  let passed = 0;
  let failed = 0;
  const tests = [testRegisterPeer, testListAndRemovePeers, testGetPeerTrust];
  for (const test of tests) {
    try {
      await test();
      passed++;
    } catch (e) {
      console.error(`✗ ${test.name}: ${e.message}`);
      failed++;
    }
    // Don't cleanup between tests — use unique URLs instead
  }
  await cleanup();
  console.log(`\n═══ Feature 8: Cross-Grid Federation — ${passed} passed, ${failed} failed ═══`);
  process.exit(failed > 0 ? 1 : 0);
}

main();
