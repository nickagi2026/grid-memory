const assert = require('node:assert');
const { describe, it } = require('node:test');
const os = require('os'), path = require('path'), fs = require('fs');

function freshEnv() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'rep-'));
  delete require.cache[require.resolve('../reputation.js')];
  delete require.cache[require.resolve('../reference/store.js')];
  process.env.GRID_STORE_DIR = dir;
  const { Grid } = require('../reference/store.js');
  const { scoreAgent, scoreAll } = require('../reputation.js');
  return { Grid, scoreAgent, scoreAll, dir };
}

describe('Reputation Consistency', () => {
  it('scoreAll excludes _system agents', async () => {
    const env = freshEnv();
    const g = new env.Grid();
    await g.write({ agent_id: '_system', type: 'fact', content: 'System note', tags: [] });
    await g.write({ agent_id: 'real-agent', type: 'fact', content: 'Real work', tags: ['work'] });
    const r = await env.scoreAll(g);
    const system = r.agents.find(a => a.agent.startsWith('_'));
    assert.strictEqual(system, undefined, '_system agent should be excluded');
    assert.ok(r.agents.length >= 1);
    fs.rmSync(env.dir, { recursive: true, force: true });
  });

  it('scoreAll counts times_referenced', async () => {
    const env = freshEnv();
    const g = new env.Grid();
    await g.write({ agent_id: 'architect', type: 'decision', content: 'Use PostgreSQL', tags: ['db'] });
    await g.write({ agent_id: 'dev', type: 'fact', content: 'architect recommended PostgreSQL', tags: ['db'] });
    const r = await env.scoreAll(g);
    const arch = r.agents.find(a => a.agent === 'architect');
    assert.ok(arch.times_referenced >= 1, `Expected architect referenced >=1, got ${arch?.times_referenced}`);
    fs.rmSync(env.dir, { recursive: true, force: true });
  });

  it('scoreAgent and scoreAll agree on single agent', async () => {
    const env = freshEnv();
    const g = new env.Grid();
    await g.write({ agent_id: 'engineer', type: 'fact', content: 'Work done', tags: ['work'] });
    const all = await env.scoreAll(g);
    const single = await env.scoreAgent(g, 'engineer');
    const allEntry = all.agents.find(a => a.agent === 'engineer');
    assert.ok(allEntry);
    assert.strictEqual(single.score, allEntry.score);
    assert.strictEqual(single.total_entries, allEntry.total_entries);
    fs.rmSync(env.dir, { recursive: true, force: true });
  });
});
