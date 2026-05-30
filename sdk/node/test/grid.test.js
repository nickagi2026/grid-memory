/**
 * Tests for grid-memory Node.js SDK.
 * Requires a running Grid server at http://localhost:8080.
 * Run with: node --test test/*.test.js
 */

const { describe, it, before, after } = require('node:test');
const assert = require('node:assert');
const { Grid, GridError } = require('../src/index.js');

const TEST_URL = process.env.GRID_URL || 'http://localhost:8080';
let grid;

describe('Grid Memory Node.js SDK', () => {
  before(async () => {
    grid = new Grid(TEST_URL, { defaultAgentId: 'node-test' });
    // Verify server is running
    try {
      await grid.health();
    } catch (e) {
      console.error(`Grid server not available at ${TEST_URL}: ${e.message}`);
      process.exit(1);
    }
  });

  it('fact() writes with default agent', async () => {
    const result = await grid.fact('Default agent test', { tags: ['test'] });
    assert.strictEqual(result.agent_id, 'node-test');
    await grid.forget(result.entry_id);
  });

  it('fact() accepts per-call agentId', async () => {
    const result = await grid.fact('Custom agent test', {
      tags: ['test'],
      agentId: 'custom-architect',
    });
    assert.strictEqual(result.agent_id, 'custom-architect');
    await grid.forget(result.entry_id);
  });

  it('decide() stores decisions correctly', async () => {
    const result = await grid.decide('Use PostgreSQL', {
      rationale: 'Better ecosystem',
      tags: ['database'],
      agentId: 'architect',
    });
    assert.strictEqual(result.type, 'decision');
    // Verify by reading it back
    const q = await grid.query({ tags: ['database'], type: 'decision' });
    const entry = q.entries.find(e => e.id === result.entry_id);
    assert.ok(entry, 'Written decision not found in query');
    assert.ok(entry.content.includes('Rationale: Better ecosystem'));
    await grid.forget(result.entry_id);
  });

  it('handoff() stores cross-agent handoffs', async () => {
    const result = await grid.handoff({
      from: 'researcher',
      to: 'builder',
      content: 'API design complete',
      status: 'ready',
    });
    assert.strictEqual(result.type, 'handoff');
    // Verify by reading it back
    const q = await grid.query({ agents: ['researcher'], type: 'handoff' });
    const entry = q.entries.find(e => e.id === result.entry_id);
    assert.ok(entry, 'Written handoff not found in query');
    assert.ok(entry.content.includes('builder'));
    await grid.forget(result.entry_id);
  });

  it('query() filters by tags', async () => {
    const e1 = await grid.fact('Entry Alpha', { tags: ['project:alpha', 'test'] });
    const e2 = await grid.fact('Entry Beta', { tags: ['project:beta', 'test'] });
    const e3 = await grid.fact('Entry Alpha-2', { tags: ['project:alpha', 'test'] });

    const result = await grid.query({ tags: ['project:alpha'] });
    assert.ok(result.entries.length >= 2);
    for (const e of result.entries) {
      assert.ok(e.tags.includes('project:alpha'));
    }

    await grid.forget(e1.entry_id);
    await grid.forget(e2.entry_id);
    await grid.forget(e3.entry_id);
  });

  it('query() respects max limit', async () => {
    const entries = [];
    for (let i = 0; i < 5; i++) {
      entries.push(await grid.fact(`Max test ${i}`, { tags: ['test-max'] }));
    }

    const result = await grid.query({ tags: ['test-max'], max: 2 });
    assert.ok(result.entries.length <= 2);

    for (const e of entries) {
      await grid.forget(e.entry_id);
    }
  });

  it('query() by agent_id', async () => {
    const e = await grid.fact('Agent-specific', {
      tags: ['test'],
      agentId: 'query-test-agent-node',
    });

    const result = await grid.query({ agents: ['query-test-agent-node'] });
    assert.ok(result.entries.length >= 1);
    for (const entry of result.entries) {
      assert.strictEqual(entry.agent_id, 'query-test-agent-node');
    }

    await grid.forget(e.entry_id);
  });

  it('inject() returns formatted context block', async () => {
    await grid.fact('API uses Fastify', { tags: ['architecture'], agentId: 'arch' });
    await grid.fact('PostgreSQL pool: 25', { tags: ['database'], agentId: 'arch' });

    const block = await grid.inject('building the API layer');
    assert.ok(block.includes('SHARED MEMORY GRID'));
    assert.ok(block.includes('END GRID'));
    assert.ok(block.length > 50);
  });

  it('info() returns store stats', async () => {
    const info = await grid.info();
    assert.ok(typeof info.total_entries === 'number');
    assert.ok(typeof info.alive_entries === 'number');
    assert.ok(typeof info.store_size_kb === 'number');
  });

  it('forget() removes a specific entry', async () => {
    const e = await grid.fact('To forget', { tags: ['test-forget'] });
    const result = await grid.forget(e.entry_id);
    assert.strictEqual(result.found, true);
  });

  it('write() accepts all parameters', async () => {
    const result = await grid.write('test-agent', 'observation', 'Generic entry', {
      tags: ['test'],
      sessionId: 'sess-123',
    });
    assert.strictEqual(result.agent_id, 'test-agent');
    assert.strictEqual(result.type, 'observation');
    await grid.forget(result.entry_id);
  });

  it('health() returns ok', async () => {
    const result = await grid.health();
    assert.strictEqual(result.status, 'ok');
  });

  it('full roundtrip: write then query', async () => {
    const e = await grid.fact('Roundtrip test', { tags: ['roundtrip-test'], agentId: 'tester' });

    const result = await grid.query({ tags: ['roundtrip-test'] });
    assert.ok(result.entries.length >= 1);
    const found = result.entries.some(en => en.content === 'Roundtrip test');
    assert.strictEqual(found, true);

    // Verify query metadata
    assert.ok(result.query_meta);
    assert.ok(typeof result.query_meta.total_before_filter === 'number');
    assert.ok(typeof result.query_meta.returned === 'number');

    await grid.forget(e.entry_id);
  });
});
