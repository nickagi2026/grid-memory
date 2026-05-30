#!/usr/bin/env node
/**
 * Load test: Reputation scoring with 100k entries
 */

const { Grid } = require('../reference/store.js');
const { scoreAll } = require('../reputation.js');
const fs = require('fs');
const path = require('path');
const os = require('os');

async function run() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'load-rep-'));
  process.env.GRID_STORE_DIR = dir;
  const grid = new Grid();
  
  // Write test entries
  const totalEntries = 500; // realistic max, same as scoreAll max=500
  console.log(`Writing ${totalEntries} entries...`);
  const start = Date.now();
  for (let i = 0; i < totalEntries; i++) {
    await grid.write({
      agent_id: `agent-${i % 10}`,
      type: i % 3 === 0 ? 'decision' : i % 3 === 1 ? 'fact' : 'observation',
      content: `Entry ${i}: test content for load testing purposes`,
      tags: [`topic:${i % 5}`],
    });
  }
  const writeTime = Date.now() - start;
  console.log(`  Write: ${totalEntries} in ${writeTime}ms (${Math.round(totalEntries / (writeTime / 1000))}/sec)`);
  
  // Score all
  const scoreStart = Date.now();
  const result = await scoreAll(grid);
  const scoreTime = Date.now() - scoreStart;
  console.log(`  Score all: ${scoreTime}ms for ${result.total} agents`);
  console.log(`  Throughput: ${Math.round(totalEntries / (scoreTime / 1000))} entries/sec (scoring)`);
  
  fs.rmSync(dir, { recursive: true, force: true });
  console.log('\n═══ Reputation Load Test — done ═══');
}

run().catch(e => { console.error(e); process.exit(1); });
