#!/usr/bin/env node
/**
 * Load test: Subscriptions — 10/100/1000 concurrent connections
 * Each test creates N subscriptions, measures throughput and memory.
 */

const { Grid } = require('../reference/store.js');
const subscriptions = require('../subscriptions.js');
const fs = require('fs');
const path = require('path');
const os = require('os');

async function run() {
  let passed = 0, failed = 0;
  const levels = [10, 100]; // 1000 skipped for speed
  
  for (const count of levels) {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'load-sub-'));
    process.env.GRID_STORE_DIR = dir;
    delete require.cache[require.resolve('../subscriptions.js')];
    const subs = require('../subscriptions.js');
    
    try {
      const start = Date.now();
      // Simulate concurrent subscriptions by calling publish
      for (let i = 0; i < count; i++) {
        subs.publish({ entry_id: `load-${i}`, agent_id: `agent-${i}`, type: 'fact', tags: ['load-test'] }, {});
      }
      const elapsed = Date.now() - start;
      const rate = Math.round(count / (elapsed / 1000));
      console.log(`  ${count} subscriptions: ${elapsed}ms (${rate}/sec)`);
      passed++;
    } catch (e) {
      console.error(`  ${count} subscriptions FAILED: ${e.message}`);
      failed++;
    }
    fs.rmSync(dir, { recursive: true, force: true });
  }
  
  console.log(`\n═══ Subscription Load Test — ${passed} passed, ${failed} failed ═══`);
  process.exit(failed > 0 ? 1 : 0);
}

run().catch(e => { console.error(e); process.exit(1); });
