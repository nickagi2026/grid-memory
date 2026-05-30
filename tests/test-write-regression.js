const assert = require('node:assert');
const { describe, it } = require('node:test');
const os = require('os');
const path = require('path');
const fs = require('fs');
const { Grid } = require('../reference/store.js');

function freshGrid() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'grid-test-'));
  const g = new Grid();
  // Override store path by setting env before construction
  // Since module is already loaded, set the config directly
  g.config.STORE_DIR = dir;
  return { grid: g, dir };
}

describe('Write Regression Suite', () => {
  it('normal write succeeds', async () => {
    const { grid: g, dir } = freshGrid();
    const r = await g.write({ agent_id: 'test', type: 'fact', content: 'Normal', tags: ['regression'] });
    assert.ok(r.entry_id);
    fs.rmSync(dir, { recursive: true, force: true });
  });

  it('write with memory_tier stored', async () => {
    const { grid: g, dir } = freshGrid();
    await g.write({ agent_id: 'test', type: 'decision', content: 'Tiered', tags: ['tier'], memory_tier: 'project' });
    const q = await g.read({ tags: ['tier'] });
    assert.strictEqual(q.entries[0].memory_tier, 'project');
    fs.rmSync(dir, { recursive: true, force: true });
  });

  it('write with workspace_id stored', async () => {
    const { grid: g, dir } = freshGrid();
    await g.write({ agent_id: 'test', type: 'fact', content: 'WS test', tags: ['ws'], workspace_id: 'ws-a' });
    const q = await g.read({ tags: ['ws'] });
    assert.strictEqual(q.entries[0].workspace_id, 'ws-a');
    fs.rmSync(dir, { recursive: true, force: true });
  });

  it('read_count increments', async () => {
    const { grid: g, dir } = freshGrid();
    await g.write({ agent_id: 'test', type: 'fact', content: 'RC test', tags: ['rc'] });
    await g.read({ tags: ['rc'] });
    const q2 = await g.read({ tags: ['rc'] });
    assert.ok(q2.entries[0].read_count >= 1);
    fs.rmSync(dir, { recursive: true, force: true });
  });

  it('parent_entry preserved', async () => {
    const { grid: g, dir } = freshGrid();
    const p = await g.write({ agent_id: 'a', type: 'fact', content: 'Parent', tags: ['pt'] });
    await g.write({ agent_id: 'b', type: 'fact', content: 'Child', tags: ['pt'], parent_entry: p.entry_id });
    const q = await g.read({ parent_entry: p.entry_id });
    assert.ok(q.entries.length >= 1);
    fs.rmSync(dir, { recursive: true, force: true });
  });
});
