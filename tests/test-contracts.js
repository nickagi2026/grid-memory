const assert = require('node:assert');
const { describe, it, before } = require('node:test');
const fs = require('fs');
const os = require('os');
const path = require('path');

// Clear contracts file before running
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ct-'));
process.env.GRID_STORE_DIR = dir;
delete require.cache[require.resolve('../contracts.js')];
const contracts = require('../contracts.js');

describe('Memory Contracts', () => {
  it('list returns empty initially', () => {
    assert.strictEqual(contracts.listContracts().length, 0);
  });

  it('register a contract with required fields', () => {
    const r = contracts.registerContract('deploy:*', {
      env: 'string', version: 'string', status: 'enum:success|failure|pending', required: ['env', 'version', 'status']
    });
    assert.ok(r.registered);
  });

  it('validate valid entry', () => {
    const r = contracts.validate(['deploy:prod'], JSON.stringify({ env: 'prod', version: '1.0.0', status: 'success' }));
    assert.ok(r.valid);
  });

  it('reject invalid enum value', () => {
    const r = contracts.validate(['deploy:prod'], JSON.stringify({ env: 'prod', version: '1.0.0', status: 'invalid_value' }));
    assert.ok(!r.valid);
    assert.ok(r.errors.length > 0);
  });

  it('reject missing required field', () => {
    const r = contracts.validate(['deploy:prod'], JSON.stringify({ env: 'prod' }));
    assert.ok(!r.valid);
  });

  it('non-matching scope passes through', () => {
    const r = contracts.validate(['database'], JSON.stringify({ whatever: true }));
    assert.ok(r.valid);
  });

  it('reject on invalid JSON', () => {
    const r = contracts.validate(['deploy:prod'], 'not json');
    assert.ok(!r.valid);
  });

  it('remove a contract', () => {
    contracts.registerContract('test:*', { name: 'string' });
    assert.ok(contracts.removeContract('test:*').removed);
    const list = contracts.listContracts();
    assert.strictEqual(list.length, 1); // Only :deploy remains
  });
});
