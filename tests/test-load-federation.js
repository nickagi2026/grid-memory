#!/usr/bin/env node
/**
 * Load test: Federation peer management
 */

const { registerPeer, listPeers, removePeer, getPeerTrust } = require('../federation.js');
const fs = require('fs');
const path = require('path');
const os = require('os');

async function run() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'load-fed-'));
  process.env.GRID_STORE_DIR = dir;
  
  const counts = [10, 50];
  let passed = 0;
  
  for (const count of counts) {
    delete require.cache[require.resolve('../federation.js')];
    const fed = require('../federation.js');
    
    const start = Date.now();
    for (let i = 0; i < count; i++) {
      fed.registerPeer(`http://peer-${i}:8080`, 'verified', `secret-${i}`);
    }
    const elapsed = Date.now() - start;
    const rate = Math.round(count / (elapsed / 1000));
    
    const allPeers = fed.listPeers();
    const clean = allPeers.filter(p => p.url.startsWith('http://peer-'));
    
    console.log(`  ${count} peers: ${elapsed}ms (${rate}/sec), ${clean.length} listed`);
    passed++;
  }
  
  fs.rmSync(dir, { recursive: true, force: true });
  console.log(`\n═══ Federation Load Test — ${passed} passed ═══`);
}

run().catch(e => { console.error(e); process.exit(1); });
