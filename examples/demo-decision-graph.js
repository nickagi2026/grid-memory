#!/usr/bin/env node
/**
 * Demo 3 — "Show me every decision that led to this incident"
 *
 * Builds a decision DAG from seed data, shows the causal chain.
 */

'use strict';
const { spawn } = require('child_process');
const http = require('http');
const path = require('path');
const os = require('os');

const PORT = 19882;
const STORE_DIR = path.join(os.tmpdir(), 'demo-graph-' + Date.now());

async function main() {
  console.log('\n╔══════════════════════════════════════════════╗');
  console.log('║  Demo: Every decision that led to incident  ║');
  console.log('╚══════════════════════════════════════════════╝\n');

  const server = spawn('node', ['server.js'], {
    cwd: __dirname + '/..',
    env: { ...process.env, GRID_SEED_MODE: 'true', GRID_STORE_DIR: STORE_DIR, PORT: String(PORT) },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  await new Promise(r => setTimeout(r, 1500));

  async function get(url) {
    return new Promise((resolve) => {
      http.get(`http://localhost:${PORT}${url}`, (res) => {
        let d = '';
        res.on('data', c => d += c);
        res.on('end', () => { try { resolve(JSON.parse(d)); } catch { resolve(null); } });
      });
    });
  }

  console.log('1. Fetching decision graph...');
  const graph = await get('/decisions/graph');
  const nodes = graph.nodes || graph.decisions || [];
  console.log(`   ${nodes.length} decision nodes found\n`);

  console.log('2. Decision statistics...');
  const stats = await get('/decisions/stats');
  if (stats && stats.decision_makers) {
    console.log(`   Top decision makers:`);
    for (const dm of stats.decision_makers.slice(0, 3)) {
      console.log(`     ${dm.agent}: ${dm.count} decisions`);
    }
    console.log(`   Overall success rate: ${stats.success_rate || stats.overall_success_rate}`);
  }
  console.log();

  console.log('3. Executive summary...');
  const exec = await get('/executive/dashboard');
  console.log(`   ${exec.summary.total_entries} total entries`);
  console.log(`   ${exec.summary.unique_agents} unique agents\n`);

  console.log('╔══════════════════════════════════════════════╗');
  console.log('║  Demo complete.                              ║');
  console.log('╚══════════════════════════════════════════════╝');
  server.kill();
  process.exit(0);
}
main().catch(e => { console.error(e); process.exit(1); });
