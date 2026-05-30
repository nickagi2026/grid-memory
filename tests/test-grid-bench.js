#!/usr/bin/env node
/**
 * tests/test-grid-bench.js — Feature 10: GRID-BENCH Benchmark
 *
 * Four benchmark tests measuring:
 * 1. coordinationAccuracy — 3 agents write to shared topic, 4th retrieves consensus
 * 2. conflictDetectionRate — Seed contradictions, measure detection
 * 3. cascadeContainment — Simulate poisoned entry cascade through 3 agents
 * 4. recoveryFidelity — Export → clear → import, measure field-level accuracy
 */

const { Grid } = require('../reference/store.js');
const { findStale } = require('../staleness.js');
const { getCascade, recallEntry, trackPropagation, getContaminationStatus } = require('../cascade.js');
const fs = require('fs');
const path = require('path');
const os = require('os');

function freshBenchGrid() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'bench-'));
  const g = new Grid();
  g.config.STORE_DIR = dir;
  return { grid: g, dir };
}

// ─── Test 1: Coordination Accuracy ──────────────────────────────────────────

async function coordinationAccuracy() {
  const { grid, dir: d1 } = freshBenchGrid();

  // 3 agents write about the same shared topic
  await grid.write({ agent_id: 'agent-1', type: 'decision', tags: ['topic:strategy'], content: 'We should invest in AI capabilities' });
  await grid.write({ agent_id: 'agent-2', type: 'fact', tags: ['topic:strategy'], content: 'AI market growing 30% YoY' });
  await grid.write({ agent_id: 'agent-3', type: 'observation', tags: ['topic:strategy'], content: 'Competitors are already deploying AI solutions' });

  // 4th agent retrieves consensus on the topic
  const result = await grid.read({ tags: ['topic:strategy'], max: 10, tagMode: 'AND' });

  const expectedEntries = 3;
  const actualEntries = result.entries.filter(e => e.tags.includes('topic:strategy')).length;
  const overlap = Math.min(actualEntries, expectedEntries) / expectedEntries;
  const score = Math.round(overlap * 100);

  const passed = score >= 80; // at least 80% overlap
  console.log(`  coordinationAccuracy: score=${score}, passed=${passed}, entries_found=${actualEntries}/${expectedEntries}`);
  return { name: 'coordinationAccuracy', score, passed };
}

// ─── Test 2: Conflict Detection Rate ────────────────────────────────────────

async function conflictDetectionRate() {
  const { grid, dir: d2 } = freshBenchGrid();

  // Seed 5 contradictions at known positions with tags
  const contradictions = [
    { decision: 'Deploy to production', contradiction: 'Roll back to staging' },
    { decision: 'Use PostgreSQL', contradiction: 'Use MongoDB' },
    { decision: 'Hire 5 engineers', contradiction: 'Freeze hiring' },
    { decision: 'Target enterprise market', contradiction: 'Target SMB market' },
    { decision: 'Build in-house solution', contradiction: 'Buy third-party tool' },
  ];

  for (const c of contradictions) {
    await grid.write({ agent_id: 'agent-a', type: 'decision', tags: ['topic:conflict-test'], content: c.decision });
    await grid.write({ agent_id: 'agent-b', type: 'decision', tags: ['topic:conflict-test'], content: c.contradiction });
  }

  // Use staleness detection to find contradictions
  const stale = findStale(grid, { thresholdDays: 1 });
  const contradictionFlags = stale.filter(s => s.reasons.some(r => r.includes('contradicting')));
  const detected = contradictionFlags.length;

  // Score: how many of the 10 entries involved in contradictions were flagged
  const totalInvolved = 10; // 5 pairs
  const score = Math.round((detected / Math.max(1, totalInvolved)) * 100);
  const passed = score >= 30; // at least 30% contradiction detection rate

  console.log(`  conflictDetectionRate: score=${score}, passed=${passed}, contradictions_detected=${detected}/${totalInvolved}`);
  return { name: 'conflictDetectionRate', score, passed };
}

// ─── Test 3: Cascade Containment ────────────────────────────────────────────

async function cascadeContainment() {
  const { grid, dir: d3 } = freshBenchGrid();

  // Simulate poisoned entry cascading through 3 agents
  const poisoned = await grid.write({
    agent_id: 'agent-toxic', type: 'fact', tags: ['topic:cascade-bench'],
    content: 'POISONED: The sky is green',
  });

  // Cascade through 3 agents
  let parent = poisoned.entry_id;
  for (let i = 0; i < 3; i++) {
    const child = await grid.write({
      agent_id: `agent-${i + 10}`,
      type: 'observation',
      tags: ['topic:cascade-bench'],
      content: `Agent ${i + 10} entry building on previous`,
      parent_entry: parent,
    });
    trackPropagation(grid, parent, child.entry_id, '');
    parent = child.entry_id;
  }

  // Now recall the source
  const recallResult = await recallEntry(grid, poisoned.entry_id, 'Poisoned data detected');

  // Check all descendants are contaminated
  const descendants = recallResult.contaminated_entries;
  let totalContaminated = 0;
  for (const descId of descendants) {
    const status = getContaminationStatus(grid, descId);
    if (status.contaminated) totalContaminated++;
  }

  const expected = 3; // 3 descendants
  const coverage = expected > 0 ? totalContaminated / expected : 1;
  const score = Math.round(coverage * 100);
  const passed = score === 100; // Must have 100% recall coverage

  console.log(`  cascadeContainment: score=${score}, passed=${passed}, contaminated=${totalContaminated}/${expected}`);
  return { name: 'cascadeContainment', score, passed };
}

// ─── Test 4: Recovery Fidelity ──────────────────────────────────────────────

async function recoveryFidelity() {
  const { grid, dir: d4 } = freshBenchGrid();

  // Write entries with all field types
  const entries = [];
  for (let i = 0; i < 5; i++) {
    const e = await grid.write({
      agent_id: `agent-fid-${i}`,
      type: i % 2 === 0 ? 'decision' : 'fact',
      tags: ['topic:fidelity', `index:${i}`],
      content: `Entry ${i} with comprehensive fields`,
      session_id: `session-${i}`,
      parent_entry: i > 0 ? entries[i - 1] : null,
      status: 'active',
      outcome: i === 0 ? { result: 'success', delta: `delta-${i}`, notes: 'All good', recorded_at: new Date().toISOString() } : null,
      origin_trust: i === 0 ? 'verified' : 'native',
    });
    entries.push(e);
  }

  // Export all
  const exportResult = await grid.exportAll();
  const exportedEntries = exportResult.entries;

  // Now clear and re-import
  await grid.wipe(true);
  const targetDir = fs.mkdtempSync(path.join(os.tmpdir(), 'bench-target-'));
  const targetGrid = new Grid();
  targetGrid.config.STORE_DIR = targetDir;
  targetGrid._loadStore();

  for (const entry of exportedEntries) {
    await targetGrid.write({
      agent_id: entry.agent_id,
      type: entry.type,
      tags: entry.tags,
      content: entry.content,
      ttl_seconds: entry.ttl_seconds,
      session_id: entry.session_id,
      parent_entry: entry.parent_entry,
      memory_tier: entry.memory_tier,
      force_id: entry.id,
      force_created_at: entry.created_at,
      force_expires_at: entry.expires_at,
    });
  }

  // Compare field-level accuracy
  const reloaded = await targetGrid.exportAll();
  const reloadedEntries = reloaded.entries;

  let totalFields = 0;
  let matchingFields = 0;
  const fieldNames = ['id', 'agent_id', 'type', 'content', 'ttl_seconds', 'session_id', 'memory_tier'];

  for (const original of exportedEntries) {
    const recovered = reloadedEntries.find(e => e.id === original.id);
    if (!recovered) continue;

    for (const field of fieldNames) {
      totalFields++;
      if (String(original[field]) === String(recovered[field])) matchingFields++;
    }
  }

  const score = totalFields > 0 ? Math.round((matchingFields / totalFields) * 100) : 0;
  const passed = score >= 95; // At least 95% field-level round-trip accuracy

  console.log(`  recoveryFidelity: score=${score}, passed=${passed}, fields_match=${matchingFields}/${totalFields}`);
  return { name: 'recoveryFidelity', score, passed };
}

// ─── Main ───────────────────────────────────────────────────────────────────

async function main() {
  console.log('\n═══ GRID-BENCH Benchmark ═══\n');

  const benchmarks = [
    { fn: coordinationAccuracy, threshold: 80 },
    { fn: conflictDetectionRate, threshold: 30 },
    { fn: cascadeContainment, threshold: 100 },
    { fn: recoveryFidelity, threshold: 95 },
  ];

  const results = [];
  for (const bench of benchmarks) {
    try {
      const result = await bench.fn();
      results.push(result);
    } catch (e) {
      console.error(`  ${bench.fn.name}: ERROR — ${e.message}`);
      results.push({ name: bench.fn.name, score: 0, passed: false, error: e.message });
    }
    // (each benchmark uses its own temp dir via freshBenchGrid)
  }

  // Summary
  console.log('\n═══ GRID-BENCH Results ═══');
  let totalScore = 0;
  let totalPassed = 0;
  for (const r of results) {
    const status = r.passed ? '✓ PASS' : '✗ FAIL';
    console.log(`  ${status}  ${r.name}: ${r.score}/100${r.error ? ` (${r.error})` : ''}`);
    totalScore += r.score;
    if (r.passed) totalPassed++;
  }
  const avgScore = results.length > 0 ? Math.round(totalScore / results.length) : 0;
  console.log(`\n  Average Score: ${avgScore}/100`);
  console.log(`  Passed: ${totalPassed}/${results.length}`);

  // Write results to docs/GRID_BENCH.md
  const docDir = path.join(__dirname, '..', 'docs');
  if (!fs.existsSync(docDir)) fs.mkdirSync(docDir, { recursive: true });

  const md = [
    '# GRID-BENCH Results',
    '',
    `Generated: ${new Date().toISOString()}`,
    '',
    '## Summary',
    '',
    `| Metric | Value |`,
    '|--------|-------|',
    `| Average Score | ${avgScore}/100 |`,
    `| Tests Passing | ${totalPassed}/${results.length} |`,
    '',
    '## Individual Results',
    '',
    '| Test | Score | Status |',
    '|------|-------|--------|',
  ];

  for (const r of results) {
    md.push(`| ${r.name} | ${r.score}/100 | ${r.passed ? '✓' : '✗'} |`);
  }

  md.push('');
  md.push('### Test Descriptions');
  md.push('');
  md.push('1. **coordinationAccuracy** — 3 agents write to a shared topic, a 4th retrieves consensus. Score based on entry overlap.');
  md.push('2. **conflictDetectionRate** — 5 contradictions are seeded at known positions. Measures detection rate via staleness analysis.');
  md.push('3. **cascadeContainment** — A poisoned entry cascades through 3 agents. Measures recall coverage when the source is recalled.');
  md.push('4. **recoveryFidelity** — Full export → clear → re-import. Measures field-level round-trip accuracy (>95% target).');

  fs.writeFileSync(path.join(docDir, 'GRID_BENCH.md'), md.join('\n'), 'utf-8');

  console.log('\nResults written to docs/GRID_BENCH.md');
  console.log('═══ End GRID-BENCH ═══\n');

  process.exit(results.filter(r => r.passed).length < results.length ? 1 : 0);
}

main();
