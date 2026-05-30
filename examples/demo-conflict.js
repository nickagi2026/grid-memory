#!/usr/bin/env node
/**
 * Demo 2 — "Two agents silently disagreed"
 *
 * Shows conflict detection between contradicting decisions.
 */

'use strict';
const { spawn } = require('child_process');
const http = require('http');
const path = require('path');
const os = require('os');

const PORT = 19881;
const STORE_DIR = path.join(os.tmpdir(), 'demo-conflict-' + Date.now());

async function main() {
  console.log('\n╔════════════════════════════════════════╗');
  console.log('║  Demo: Two agents silently disagreed  ║');
  console.log('╚════════════════════════════════════════╝\n');

  const server = spawn('node', ['server.js'], {
    cwd: __dirname + '/..',
    env: { ...process.env, GRID_SEED_MODE: 'true', GRID_STORE_DIR: STORE_DIR, PORT: String(PORT) },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  await new Promise(r => setTimeout(r, 1500));

  async function post(url, body) {
    return new Promise((resolve, reject) => {
      const data = JSON.stringify(body);
      const req = http.request(`http://localhost:${PORT}${url}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) },
      }, (res) => { let d=''; res.on('data',c=>d+=c); res.on('end',()=>{try{resolve(JSON.parse(d))}catch{resolve(null)}}); });
      req.on('error', reject);
      req.write(data);
      req.end();
    });
  }

  // Write contradicting decisions
  console.log('1. Agent A decides: Use PostgreSQL...');
  await post('/write', { agent_id: 'arch-agent', type: 'decision', content: 'Use PostgreSQL. Rationale: ACID compliance.', tags: ['topic:database'] });
  console.log('   ✓ Entry written\n');

  console.log('2. Agent B decides: Use MongoDB...');
  await post('/write', { agent_id: 'ops-agent', type: 'decision', content: 'Not PostgreSQL. Use MongoDB. Rationale: schema flexibility.', tags: ['topic:database'] });
  console.log('   ✓ Entry written\n');

  console.log('3. Checking ROI for contradictions...');
  const roi = await new Promise(r => http.get(`http://localhost:${PORT}/roi`, (res) => { let d=''; res.on('data',c=>d+=c); res.on('end',()=>r(JSON.parse(d))); }));
  console.log(`   Contradictions detected: ${roi.contradictions_detected}`);
  console.log(`   Evidence: ${JSON.stringify(roi.details.contradiction_pairs.slice(0, 2))}\n`);

  console.log('╔════════════════════════════════════════╗');
  console.log('║  Demo complete.                        ║');
  console.log('╚════════════════════════════════════════╝');
  server.kill();
  process.exit(0);
}
main().catch(e => { console.error(e); process.exit(1); });
