#!/usr/bin/env node
/**
 * Demo 1 — "Your AI team forgot something"
 *
 * Starts the server, seeds demo data, runs amnesia detection.
 * Shows: blocker contradicted by new deployment decision.
 */

'use strict';
const { spawn } = require('child_process');
const path = require('path');
const http = require('http');
const os = require('os');

const PORT = 19880;
const STORE_DIR = path.join(os.tmpdir(), 'demo-amnesia-' + Date.now());

async function main() {
  console.log('\n╔════════════════════════════════════════╗');
  console.log('║  Demo: Your AI team forgot something  ║');
  console.log('╚════════════════════════════════════════╝\n');

  const server = spawn('node', ['server.js'], {
    cwd: __dirname + '/..',
    env: { ...process.env, GRID_SEED_MODE: 'true', GRID_STORE_DIR: STORE_DIR, PORT: String(PORT) },
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  await new Promise(r => setTimeout(r, 1500));

  async function get(url) {
    return new Promise((resolve, reject) => {
      http.get(`http://localhost:${PORT}${url}`, (res) => {
        let data = '';
        res.on('data', c => data += c);
        res.on('end', () => { try { resolve(JSON.parse(data)); } catch { resolve(null); } });
      }).on('error', reject);
    });
  }

  // 1. Run amnesia detection
  console.log('1. Running amnesia detection...');
  const amnesia = await get('/amnesia/detect');
  console.log(`   Amnesia Score: ${amnesia.amnesia_score}/1.0`);
  console.log(`   Knowledge gaps: ${amnesia.gaps.length}`);
  console.log(`   Orphaned decisions: ${amnesia.orphans.length}`);
  console.log(`   Stale decisions: ${amnesia.stale_decisions.length}`);
  console.log(`   Single points of failure: ${amnesia.single_points_of_failure.length}`);
  console.log(`   Summary: ${amnesia.summary}\n`);

  // 2. Show the decision graph
  console.log('2. Decision graph...');
  const graph = await get('/decisions/graph');
  const nodes = graph.nodes || graph.decisions || [];
  console.log(`   ${nodes.length} decisions tracked\n`);

  // 3. Show developer ROI
  console.log('3. Developer ROI...');
  const roi = await get('/roi');
  console.log(`   Time saved: ${roi.time_saved_estimate}`);
  console.log(`   Contradictions detected: ${roi.contradictions_detected}`);
  console.log(`   Opportunities found: ${roi.opportunities_found}\n`);

  // 4. Generate QBR
  console.log('4. Quarterly Business Review...');
  const qbr = await get('/qbr');
  console.log(`   Title: ${qbr.title}\n`);

  console.log('╔════════════════════════════════════════╗');
  console.log('║  Demo complete.                        ║');
  console.log('║  Server running on http://localhost:' + PORT + '  ║');
  console.log('╚════════════════════════════════════════╝');

  server.kill();
  process.exit(0);
}

main().catch(e => { console.error(e); process.exit(1); });
