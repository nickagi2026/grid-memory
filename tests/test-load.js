/**
 * test-load.js — Simple load test for the Grid Memory server.
 *
 * Simulates multiple concurrent agents writing and reading.
 * Tests throughput and error rates under load.
 *
 * Usage: node tests/test-load.js [requests] [concurrency]
 */

const http = require('http');
const BASE_URL = process.env.GRID_URL || 'http://localhost:8080';
const TOTAL = parseInt(process.argv[2] || '100', 10);
const CONCURRENCY = parseInt(process.argv[3] || '10', 10);

function req(method, path, body) {
  return new Promise((resolve) => {
    try {
      const url = new URL(path, BASE_URL);
      const data = body ? JSON.stringify(body) : '';
      const opts = { hostname: url.hostname, port: url.port, path: url.pathname, method, headers: { 'Content-Type': 'application/json' } };
      if (data) opts.headers['Content-Length'] = Buffer.byteLength(data);
      const r = http.request(opts, (res) => {
        let response = '';
        res.on('data', c => response += c);
        res.on('end', () => resolve({ status: res.statusCode }));
      });
      r.on('error', () => resolve({ status: 0 }));
      if (data) r.write(data);
      r.end();
    } catch { resolve({ status: 0 }); }
  });
}

async function worker(id) {
  const results = { write: 0, read: 0, errors: 0, totalMs: 0 };
  const start = Date.now();

  for (let i = 0; i < TOTAL / CONCURRENCY; i++) {
    // Write
    const w = await req('POST', '/write', {
      agent_id: `load-test-${id}`, type: 'fact',
      content: `Load test entry ${i} from worker ${id}`,
      tags: ['load-test']
    });
    if (w.status === 200 || w.status === 201) results.write++;
    else results.errors++;

    // Read
    const r = await req('GET', `/query?tags=load-test&max=5`);
    if (r.status === 200) results.read++;
    else results.errors++;
  }

  results.totalMs = Date.now() - start;
  return results;
}

async function main() {
  console.log(`\n═══ Load Test: ${TOTAL} ops, ${CONCURRENCY} concurrent ═══\n`);

  const start = Date.now();
  const workers = Array.from({ length: CONCURRENCY }, (_, i) => worker(i));
  const results = await Promise.all(workers);
  const totalMs = Date.now() - start;

  const totalWrites = results.reduce((s, r) => s + r.write, 0);
  const totalReads = results.reduce((s, r) => s + r.read, 0);
  const totalErrors = results.reduce((s, r) => s + r.errors, 0);
  const totalOps = totalWrites + totalReads + totalErrors;

  const opsPerSec = Math.round(totalOps / (totalMs / 1000));

  console.log(`  Total operations: ${totalOps}`);
  console.log(`  Writes: ${totalWrites}`);
  console.log(`  Reads:  ${totalReads}`);
  console.log(`  Errors: ${totalErrors}`);
  console.log(`  Duration: ${totalMs}ms`);
  console.log(`  Throughput: ${opsPerSec} ops/sec`);
  console.log(`  Error rate: ${(totalErrors / totalOps * 100).toFixed(1)}%`);
  console.log(`\n═══ Load test complete ═══\n`);

  process.exit(totalErrors / totalOps > 0.1 ? 1 : 0);
}
main();
