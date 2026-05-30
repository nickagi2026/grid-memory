const assert = require('node:assert');
const { describe, it } = require('node:test');
const { Grid } = require('../reference/store.js');
const contracts = require('../contracts.js');

describe('TDZ Regression — tags before features', () => {
  it('write with contracts validation does not crash', async () => {
    // Register a contract
    contracts.registerContract('deploy:*', { env: 'string', version: 'string', required: ['env'] });
    const g = new Grid();
    const r = await g.write({ agent_id: 'test', type: 'fact', content: JSON.stringify({ env: 'prod', version: '1.0' }), tags: ['deploy:prod'] });
    assert.ok(r.entry_id);
  });

  it('write with tags but no contracts succeeds', async () => {
    const g = new Grid();
    const r = await g.write({ agent_id: 'test', type: 'fact', content: 'Just a test', tags: ['simple'] });
    assert.ok(r.entry_id);
  });

  it('write with workspace tags succeeds', async () => {
    const g = new Grid();
    const r = await g.write({ agent_id: 'test', type: 'fact', content: 'WS test', tags: ['ws-test'], workspace_id: 'ws-a' });
    assert.ok(r.entry_id);
  });
});
