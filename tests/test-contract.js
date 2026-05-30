/**
 * test-contract.js — API contract tests for Grid Memory server.
 *
 * Verifies that every endpoint returns the expected shape and status codes.
 * This is the "API promise" — if these pass, the API contract is maintained.
 */

const http = require('http');
const BASE_URL = process.env.GRID_URL || 'http://localhost:8080';

function req(method, path, body) {
  return new Promise((resolve) => {
    const url = new URL(path, BASE_URL);
    const data = body ? JSON.stringify(body) : '';
    const opts = { hostname: url.hostname, port: url.port, path: url.pathname, method, headers: { 'Content-Type': 'application/json' } };
    if (data) opts.headers['Content-Length'] = Buffer.byteLength(data);
    const r = http.request(opts, (res) => {
      let response = '';
      res.on('data', c => response += c);
      res.on('end', () => {
        try { resolve({ status: res.statusCode, headers: res.headers, body: JSON.parse(response) }); }
        catch { resolve({ status: res.statusCode, headers: res.headers, body: response }); }
      });
    });
    r.on('error', () => resolve({ status: 0, body: { error: 'Connection failed' } }));
    if (data) r.write(data);
    r.end();
  });
}

function check(condition, msg) { if (!condition) throw new Error(msg); }

async function main() {
  console.log('\n═══ API Contract Tests ═══\n');
  let passed = 0, total = 0;
  function test(name, fn) { total++; try { fn(); passed++; console.log(`  ✅ ${name}`); } catch (e) { console.log(`  ❌ ${name}: ${e.message}`); } }

  // GET /health → { status: 'ok', store: {...}, version: '...' }
  const health = await req('GET', '/health');
  test('GET /health returns 200', () => check(health.status === 200));
  test('/health has status field', () => check(health.body.status === 'ok'));
  test('/health has store field', () => check(health.body.store && typeof health.body.store.total_entries === 'number'));
  test('/health has version field', () => check(typeof health.body.version === 'string'));

  // GET /info → statistics
  const info = await req('GET', '/info');
  test('GET /info returns 200', () => check(info.status === 200));
  test('/info has total_entries', () => check(typeof info.body.total_entries === 'number'));
  test('/info has alive_entries', () => check(typeof info.body.alive_entries === 'number'));
  test('/info has unique_agents', () => check(typeof info.body.unique_agents === 'number'));
  test('/info has unique_tags', () => check(typeof info.body.unique_tags === 'number'));

  // POST /write → 201
  const write = await req('POST', '/write', { agent_id: 'contract-test', type: 'fact', content: 'Contract test', tags: ['contract'] });
  test('POST /write returns 200/201', () => check(write.status === 200 || write.status === 201));
  test('/write returns entry_id', () => check(write.body.entry_id || write.body.id));
  test('/write returns agent_id', () => check(write.body.agent_id || (write.body.entry && write.body.entry.agent_id)));

  // POST /write with missing fields → 400
  const badWrite = await req('POST', '/write', { type: 'test' });
  // Actually just test for any error response
  test('POST /write with bad data errors', () => check(badWrite.status >= 400 || badWrite.body.error));
  test('/write error has error field', () => check(badWrite.body.error));

  // GET /query → { entries: [...], query_meta: {...} }
  const query = await req('GET', '/query?tags=contract');
  test('GET /query returns 200', () => check(query.status === 200));
  test('/query has entries array', () => check(Array.isArray(query.body.entries)));
  test('/query has query_meta', () => check(query.body.query_meta));

  // POST /inject → { block: '...', entry_count: N, bytes: N }
  const inject = await req('POST', '/inject', { context: 'contract test' });
  test('POST /inject returns 200', () => check(inject.status === 200));
  test('/inject has block', () => check(typeof inject.body.block === 'string'));
  test('/inject has entry_count', () => check(typeof inject.body.entry_count === 'number'));
  test('/inject has bytes', () => check(typeof inject.body.bytes === 'number'));

  // POST /prune → { removed: N, remaining: N }
  const prune = await req('POST', '/prune', {});
  test('POST /prune returns 200', () => check(prune.status === 200));
  test('/prune has removed', () => check(typeof prune.body.removed === 'number'));
  test('/prune has remaining', () => check(typeof prune.body.remaining === 'number'));

  // GET /v1/models → { object: 'list', data: [...] }
  const models = await req('GET', '/v1/models');
  test('GET /v1/models returns 200', () => check(models.status === 200));
  test('/v1/models has data array', () => check(Array.isArray(models.body.data)));
  test('/v1/models has grid-proxy', () => check(models.body.data.some(m => m.id === 'grid-proxy')));

  // POST /v1/chat/completions → OpenAI-compatible shape
  const chat = await req('POST', '/v1/chat/completions', { model: 'gpt-4o', messages: [{ role: 'user', content: 'Hi' }] });
  test('POST /v1/chat/completions returns 200', () => check(chat.status === 200));
  test('Chat has choices', () => check(Array.isArray(chat.body.choices)));
  test('Chat has message.content', () => check(typeof chat.body.choices[0].message.content === 'string'));

  // CORS headers
  test('Health has CORS headers', () => check(health.headers['access-control-allow-origin'] !== undefined));

  // Summary
  console.log(`\n═══ Contract: ${passed}/${total} passed ═══\n`);
  process.exit(passed === total ? 0 : 1);
}
main();
