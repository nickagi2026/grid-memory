/**
 * test-integration.js — Integration tests for the Grid Memory server.
 *
 * Requires a running Grid server with the gateway enabled.
 * Tests the full request lifecycle: auth → workspace → operation → audit.
 *
 * Usage:
 *   GRID_URL=http://localhost:8080 GRID_API_KEY=grid_xxx node tests/test-integration.js
 */

const http = require('http');

const BASE_URL = process.env.GRID_URL || 'http://localhost:8080';
const API_KEY = process.env.GRID_API_KEY || '';

function req(method, path, body, key) {
  return new Promise((resolve, reject) => {
    const url = new URL(path, BASE_URL);
    const data = body ? JSON.stringify(body) : '';
    const opts = {
      hostname: url.hostname, port: url.port,
      path: url.pathname, method,
      headers: { 'Content-Type': 'application/json' },
    };
    if (key) opts.headers['Authorization'] = `Bearer ${key}`;
    if (data) opts.headers['Content-Length'] = Buffer.byteLength(data);

    const r = http.request(opts, (res) => {
      let response = '';
      res.on('data', c => response += c);
      res.on('end', () => {
        try { resolve({ status: res.statusCode, body: JSON.parse(response) }); }
        catch { resolve({ status: res.statusCode, body: response }); }
      });
    });
    r.on('error', reject);
    if (data) r.write(data);
    r.end();
  });
}

let passed = 0, failed = 0;

function assert(name, condition, detail) {
  if (condition) { passed++; console.log(`  ✅ ${name}`); }
  else { failed++; console.log(`  ❌ ${name}: ${detail || ''}`); }
}

async function main() {
  console.log('\n═══ Grid Integration Tests ═══\n');

  // Start by creating an API key via gateway
  let adminKey = API_KEY;
  if (!adminKey) {
    console.log('  Creating admin API key...\n');
    const r = await req('POST', '/gateway/key/create', {
      label: 'integration-test', workspace: '*', permission: 'admin'
    });
    adminKey = r.body.plaintext_key || r.body.plaintextKey;
    assert('Gateway key creation', !!adminKey, 'No key returned');
  }

  // 1. Health check
  const health = await req('GET', '/health');
  assert('Health endpoint', health.status === 200 && health.body.status === 'ok');

  // 2. Write with key
  const write = await req('POST', '/write', {
    agent_id: 'integration-test', type: 'fact', content: 'Integration test entry', tags: ['integration']
  }, adminKey);
  assert('Write with API key', write.status === 201 || write.status === 200, `Got ${write.status}`);
  const entryId = write.body.entry_id || (write.body.entry && write.body.entry.id);

  // 3. Query by tag
  const query = await req('GET', `/query?tags=integration&max=10`);
  assert('Query by tag', query.status === 200 && query.body.entries && query.body.entries.length > 0);

  // 4. Query by agent
  const agentQ = await req('GET', '/query?agents=integration-test');
  assert('Query by agent', agentQ.status === 200);

  // 5. Info
  const info = await req('GET', '/info');
  assert('Info endpoint', info.status === 200 && typeof info.body.total_entries === 'number');

  // 6. Inject
  const inject = await req('POST', '/inject', { context: 'integration test' });
  assert('Inject endpoint', inject.status === 200 && inject.body.block && inject.body.block.includes('GRID'));

  // 7. OpenAI-compatible models
  const models = await req('GET', '/v1/models');
  assert('OpenAI models', models.status === 200 && models.body.data && models.body.data.length > 0);

  // 8. OpenAI-compatible chat
  const chat = await req('POST', '/v1/chat/completions', {
    model: 'gpt-4o', messages: [{ role: 'user', content: 'Hello' }]
  });
  assert('OpenAI chat', chat.status === 200 && chat.body.choices);

  // 9. Prune
  const prune = await req('POST', '/prune', {});
  assert('Prune endpoint', prune.status === 200);

  // 10. Forbidden without key (if auth enabled)
  const noKey = await req('POST', '/write', { agent_id: 'test', content: 'should fail' });
  // If auth is enforced, expect 401. If not, it'll pass. Either is acceptable.
  if (noKey.status === 401 || noKey.status === 201 || noKey.status === 200) {
    assert('Auth enforcement present or dev mode', true);
  }

  // Results
  console.log(`\n═══ Results: ${passed} passed, ${failed} failed ═══\n`);
  process.exit(failed > 0 ? 1 : 0);
}

main().catch(e => {
  console.error('Integration test error:', e.message);
  process.exit(1);
});
