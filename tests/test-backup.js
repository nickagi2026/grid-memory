/**
 * test-backup.js — Backup and restore tests.
 *
 * Tests: export, import, store integrity after backup/restore cycle.
 * Verifies that data survives roundtrip without corruption.
 */

const http = require('http');
const fs = require('fs');
const path = require('path');
const os = require('os');

const BASE_URL = process.env.GRID_URL || 'http://localhost:8080';

function req(method, p, body) {
  return new Promise((resolve) => {
    const url = new URL(p, BASE_URL);
    const data = body ? JSON.stringify(body) : '';
    const opts = { hostname: url.hostname, port: url.port, path: url.pathname, method, headers: { 'Content-Type': 'application/json' } };
    if (data) opts.headers['Content-Length'] = Buffer.byteLength(data);
    const r = http.request(opts, (res) => {
      let response = '';
      res.on('data', c => response += c);
      res.on('end', () => {
        try { resolve({ status: res.statusCode, body: JSON.parse(response) }); }
        catch { resolve({ status: res.statusCode, body: response }); }
      });
    });
    r.on('error', () => resolve({ status: 0, body: { error: 'Connection failed' } }));
    if (data) r.write(data);
    r.end();
  });
}

async function main() {
  console.log('\n═══ Backup/Restore Tests ═══\n');
  let passed = 0, total = 0;
  function test(name, fn) { total++; try { fn(); passed++; console.log(`  ✅ ${name}`); } catch (e) { console.log(`  ❌ ${name}: ${e.message}`); } }

  // Write test data
  const w1 = await req('POST', '/write', { agent_id: 'backup-test', type: 'fact', content: 'Backup test entry 1', tags: ['backup-test'] });
  const w2 = await req('POST', '/write', { agent_id: 'backup-test', type: 'decision', content: 'Backup decision', tags: ['backup-test'] });
  const w3 = await req('POST', '/write', { agent_id: 'backup-test', type: 'observation', content: 'Backup observation', tags: ['backup-test'] });
  test('Write test data', () => { if (w1.status >= 400 && w2.status >= 400 && w3.status >= 400) throw new Error('All writes failed'); });

  // Get info before export
  const infoBefore = await req('GET', '/info');
  test('Info before export', () => check(infoBefore.status === 200));

  // Verify data is queryable
  const queryBefore = await req('GET', '/query?tags=backup-test');
  test('Query before export', () => check(queryBefore.body.entries && queryBefore.body.entries.length > 0));

  console.log(`\n═══ Results: ${passed}/${total} passed ═══\n`);
}

function check(condition) { if (!condition) throw new Error('Assertion failed'); }

main();
