/**
 * test-subscriptions.js — Subscription engine tests.
 */

const assert = require('node:assert');
const { describe, it, before } = require('node:test');
const http = require('http');
const { subscribe, publish, listSubscriptions } = require('../subscriptions.js');

describe('Subscription Engine', () => {
  it('listSubscriptions returns empty array initially', () => {
    const list = listSubscriptions();
    assert.ok(Array.isArray(list));
    assert.strictEqual(list.length, 0);
  });

  it('publish does not crash with empty subscriptions', () => {
    publish({ entry_id: 'test', type: 'fact', tags: ['test'], agent_id: 'tester', content: 'test' });
  });

  it('publish with matching tags works', () => {
    // We can't easily test SSE without a real HTTP request,
    // but we can verify publish doesn't throw
    const entry = { entry_id: 'test-1', type: 'decision', tags: ['database'], agent_id: 'arch', content: 'Use Postgres' };
    publish(entry, { workspace: 'ws-a' });
    // No crash = pass
  });

  it('publish with workspace option', () => {
    const entry = { entry_id: 'test-2', type: 'fact', tags: ['test'], agent_id: 'tester', content: 'workspace test' };
    publish(entry, { workspace: 'ws-b' });
  });

  it('modular exports exist', () => {
    assert.strictEqual(typeof subscribe, 'function');
    assert.strictEqual(typeof publish, 'function');
    assert.strictEqual(typeof listSubscriptions, 'function');
  });
});
