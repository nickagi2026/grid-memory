/**
 * Tests for the OpenAI-compatible proxy endpoint.
 * Requires Grid server running with proxy support.
 */

const { describe, it, before } = require('node:test');
const assert = require('node:assert');
const http = require('http');

const BASE_URL = process.env.GRID_URL || 'http://localhost:8080';

function post(path, body) {
  return new Promise((resolve, reject) => {
    const url = new URL(path, BASE_URL);
    const data = JSON.stringify(body);
    const options = {
      hostname: url.hostname,
      port: url.port,
      path: url.pathname,
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(data),
      },
    };
    const req = http.request(options, (res) => {
      let response = '';
      res.on('data', chunk => (response += chunk));
      res.on('end', () => {
        try {
          resolve({ status: res.statusCode, body: JSON.parse(response) });
        } catch (e) {
          resolve({ status: res.statusCode, body: response });
        }
      });
    });
    req.on('error', reject);
    req.write(data);
    req.end();
  });
}

function get(path) {
  return new Promise((resolve, reject) => {
    const url = new URL(path, BASE_URL);
    http.get(url, (res) => {
      let data = '';
      res.on('data', chunk => (data += chunk));
      res.on('end', () => {
        try {
          resolve({ status: res.statusCode, body: JSON.parse(data) });
        } catch (e) {
          resolve({ status: res.statusCode, body: data });
        }
      });
    }).on('error', reject);
  });
}

describe('OpenAI-Compatible Proxy', () => {
  it('GET /v1/models returns model list', async () => {
    const res = await get('/v1/models');
    assert.strictEqual(res.status, 200);
    assert.strictEqual(res.body.object, 'list');
    assert.ok(Array.isArray(res.body.data));
    assert.ok(res.body.data.length >= 1);
    assert.ok(res.body.data.some(m => m.id === 'grid-proxy'));
  });

  it('POST /v1/chat/completions returns debug response when no upstream', async () => {
    const res = await post('/v1/chat/completions', {
      model: 'gpt-4o',
      messages: [
        { role: 'system', content: 'You are helpful.' },
        { role: 'user', content: 'Hello' },
      ],
    });
    assert.strictEqual(res.status, 200);
    assert.ok(res.body.id);
    assert.strictEqual(res.body.object, 'chat.completion');
    assert.ok(res.body.choices);
    assert.ok(res.body.choices.length >= 1);
    const content = res.body.choices[0].message.content;
    assert.ok(content.includes('SHARED MEMORY GRID CONTEXT'));
    assert.ok(content.includes('Enriched messages'));
  });

  it('injects Grid context into system message', async () => {
    // First write something to the Grid
    const writeRes = await post('/write', {
      agent_id: 'test',
      type: 'fact',
      content: 'Database: PostgreSQL, pool: 25 connections',
      tags: ['database', 'test'],
    });
    assert.ok(writeRes.body.entry_id);

    // Now query through the proxy with a related question
    const res = await post('/v1/chat/completions', {
      model: 'gpt-4o',
      messages: [
        { role: 'user', content: 'What is the database pool size?' },
      ],
    });

    assert.strictEqual(res.status, 200);
    const content = res.body.choices[0].message.content;

    // Should have the database context in the enriched messages
    assert.ok(content.includes('SHARED MEMORY GRID CONTEXT'),
              'Response should include Grid context');
    assert.ok(res.body._grid_context_injected === true,
              '_grid_context_injected should be true');
  });

  it('returns 400 for empty messages', async () => {
    const res = await post('/v1/chat/completions', {
      model: 'gpt-4o',
      messages: [],
    });
    assert.strictEqual(res.status, 400);
    assert.ok(res.body.error);
  });

  it('returns 400 for missing messages', async () => {
    const res = await post('/v1/chat/completions', { model: 'gpt-4o' });
    assert.strictEqual(res.status, 400);
    assert.ok(res.body.error);
  });

  it('handles CORS preflight', async () => {
    const url = new URL('/v1/chat/completions', BASE_URL);
    const res = await new Promise((resolve) => {
      const options = {
        hostname: url.hostname,
        port: url.port,
        path: url.pathname,
        method: 'OPTIONS',
      };
      const req = http.request(options, (res) => {
        resolve({
          status: res.statusCode,
          headers: res.headers,
        });
      });
      req.end();
    });
    assert.strictEqual(res.status, 204);
    assert.strictEqual(res.headers['access-control-allow-origin'], '*');
  });

  it('handles streaming hint gracefully', async () => {
    const res = await post('/v1/chat/completions', {
      model: 'gpt-4o',
      messages: [{ role: 'user', content: 'Hi' }],
      stream: true,
    });
    // Without upstream, we still respond with the debug response (not streaming)
    assert.strictEqual(res.status, 200);
  });
});
