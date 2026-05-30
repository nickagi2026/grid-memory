const assert = require('node:assert');
const { describe, it } = require('node:test');
const os = require('os'), path = require('path'), fs = require('fs');

describe('Contract Persistence', () => {
  it('contracts survive module reload', async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cp-'));
    // Set store dir for contracts file
    process.env.GRID_STORE_DIR = dir;

    // Load contracts, register one, save
    delete require.cache[require.resolve('../contracts.js')];
    const c1 = require('../contracts.js');
    c1.registerContract('test:*', { name: 'string' });
    const list1 = c1.listContracts();
    assert.strictEqual(list1.length, 1);

    // Reload module (simulates restart)
    delete require.cache[require.resolve('../contracts.js')];
    const c2 = require('../contracts.js');
    const list2 = c2.listContracts();
    assert.strictEqual(list2.length, 1, `Expected 1 contract after reload, got ${list2.length}`);
    assert.strictEqual(list2[0].scope, 'test:*');

    fs.rmSync(dir, { recursive: true, force: true });
  });
});
