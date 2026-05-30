/**
 * test-dedup.js — Semantic Deduplication tests.
 */

const assert = require('node:assert');
const { describe, it, before } = require('node:test');

const { fingerprint, wordOverlapSimilarity, findDuplicate } = require('../deduplication.js');
const { Grid } = require('../reference/store.js');

describe('Semantic Deduplication', () => {
  it('fingerprint is deterministic', () => {
    const a = fingerprint('Database connection pool size is 25');
    const b = fingerprint('Database connection pool size is 25');
    assert.strictEqual(a, b);
  });

  it('fingerprint handles normalization', () => {
    const a = fingerprint('Pool size: 25');
    const b = fingerprint('Pool size: 25.');
    assert.strictEqual(a, b);
  });

  it('word overlap similar texts', () => {
    const sim = wordOverlapSimilarity('PostgreSQL pool size is 25 connections', 'PostgreSQL connection pool has 25 connections');
    assert.ok(sim >= 0.5, `Expected >0.5, got ${sim}`);
  });

  it('word overlap different texts', () => {
    const sim = wordOverlapSimilarity('Database pool size', 'Weather forecast for tomorrow');
    assert.ok(sim < 0.3, `Expected <0.3, got ${sim}`);
  });

  it('empty texts return 0', () => {
    assert.strictEqual(wordOverlapSimilarity('', ''), 0);
  });

  it('findDuplicate returns isDuplicate=false on empty grid', async () => {
    const grid = new Grid();
    const result = await findDuplicate(grid, 'Test content', ['test'], 'agent-1');
    assert.ok(!result.isDuplicate);
  });
});
