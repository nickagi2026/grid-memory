const assert = require('node:assert');
const { describe, it } = require('node:test');
const { scoreAgent, scoreAll } = require('../reputation.js');
const { Grid } = require('../reference/store.js');

describe('Agent Reputation', () => {
  it('empty agent returns score 0', async () => {
    const grid = new Grid();
    const r = await scoreAgent(grid, 'nonexistent-agent');
    assert.strictEqual(r.score, 0);
    assert.strictEqual(r.score, 0);
  });

  it('scoreAll returns valid structure', async () => {
    const grid = new Grid();
    const r = await scoreAll(grid);
    assert.ok(Array.isArray(r.agents));
    assert.ok(r.scored_at);
  });

  it('agent with entries gets a score', async () => {
    const grid = new Grid();
    await grid.write({ agent_id: 'architect', type: 'decision', content: 'Use PostgreSQL', tags: ['database'] });
    await grid.write({ agent_id: 'architect', type: 'decision', content: 'Use Redis', tags: ['cache'] });
    const r = await scoreAgent(grid, 'architect');
    assert.ok(r.total_entries >= 2);
    assert.ok(r.score > 0);
  });
});
