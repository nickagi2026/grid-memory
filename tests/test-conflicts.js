const assert = require('node:assert');
const { describe, it } = require('node:test');
const { detectContradiction } = require('../conflicts.js');

describe('Conflict Resolution', () => {
  it('detect up/down contradiction', () => {
    const r = detectContradiction('The API is up and running', 'The API is down');
    assert.ok(r.contradiction);
  });

  it('detect success/failure contradiction', () => {
    const r = detectContradiction('Deployment passed all tests', 'Deployment failed');
    assert.ok(r.contradiction);
  });

  it('no contradiction for same position', () => {
    const r = detectContradiction('API is up', 'System is healthy');
    assert.ok(!r.contradiction);
  });

  it('detect enabled/disabled contradiction', () => {
    const r = detectContradiction('Feature is enabled on production', 'Feature is now disabled');
    assert.ok(r.contradiction);
  });

  it('no false positive on unrelated text', () => {
    const r = detectContradiction('Database pool size is 25', 'Weather forecast for tomorrow');
    assert.ok(!r.contradiction);
  });
});
