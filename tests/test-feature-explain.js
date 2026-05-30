#!/usr/bin/env node
/**
 * tests/test-feature-explain.js — Feature 9: Explainability Transcript
 *
 * Tests:
 * - generateTranscript traces parent_entry chain
 * - generateNarrative produces human-readable text
 * - Format options: narrative, json, markdown
 */

const { Grid } = require('../reference/store.js');
const { generateTranscript, generateNarrative } = require('../explain.js');
const path = require('path');
const fs = require('fs');

const TEST_STORE_DIR = path.join(process.env.HOME || '/tmp', '.openclaw', 'test_explain');
process.env.GRID_STORE_DIR = TEST_STORE_DIR;

async function setup() {
  if (fs.existsSync(TEST_STORE_DIR)) fs.rmSync(TEST_STORE_DIR, { recursive: true });
  fs.mkdirSync(TEST_STORE_DIR, { recursive: true });
}

async function cleanup() {
  if (fs.existsSync(TEST_STORE_DIR)) fs.rmSync(TEST_STORE_DIR, { recursive: true });
}

async function testTranscriptChain() {
  const grid = new Grid();

  // Create chain: source → child → grandchild
  const source = await grid.write({
    agent_id: 'agent-a', type: 'decision', tags: ['topic:explain'],
    content: 'We decided to use technology X',
  });

  const child = await grid.write({
    agent_id: 'agent-b', type: 'observation', tags: ['topic:explain'],
    content: 'Implementing tech X showed promise',
    parent_entry: source.entry_id,
  });

  const grandchild = await grid.write({
    agent_id: 'agent-c', type: 'fact', tags: ['topic:explain'],
    content: 'Tech X has 99.9% uptime',
    parent_entry: child.entry_id,
  });

  // Generate transcript
  const transcript = generateTranscript(grid, grandchild.entry_id);
  if (!transcript.chain || transcript.chain.length < 3) {
    throw new Error(`Chain too short: ${transcript.chain ? transcript.chain.length : 0}`);
  }
  if (!transcript.narrative) throw new Error('No narrative in transcript');
  if (transcript.narrative.length < 50) throw new Error('Narrative too short');

  // Verify chain contains all entries
  const chainIds = transcript.chain.map(e => e.id);
  if (!chainIds.includes(source.entry_id)) throw new Error('Source not in chain');
  if (!chainIds.includes(child.entry_id)) throw new Error('Child not in chain');
  if (!chainIds.includes(grandchild.entry_id)) throw new Error('Grandchild not in chain');

  // Verify chronological order (first entry is grandchild, last is source)
  // Actually chain is built from current → parent, so first should be grandchild
  if (transcript.chain[0].id !== grandchild.entry_id) throw new Error('First chain entry should be grandchild');

  console.log('✓ testTranscriptChain: transcript traces back through ancestry');
}

async function testJsonFormat() {
  const grid = new Grid();
  const entry = await grid.write({
    agent_id: 'agent-a', type: 'fact', tags: ['topic:json-test'],
    content: 'A simple fact',
  });

  const transcript = generateTranscript(grid, entry.entry_id, { format: 'json' });
  if (!transcript.chain) throw new Error('Chain missing in JSON format');
  if (transcript.narrative) throw new Error('Narrative should be absent in JSON format');

  console.log('✓ testJsonFormat: JSON format works');
}

async function testMarkdownFormat() {
  const grid = new Grid();
  const entry = await grid.write({
    agent_id: 'agent-a', type: 'fact', tags: ['topic:md-test'],
    content: 'A markdown-formatted fact',
  });

  const transcript = generateTranscript(grid, entry.entry_id, { format: 'markdown' });
  if (!transcript.narrative) throw new Error('Narrative missing in markdown format');
  if (!transcript.narrative.includes('#')) throw new Error('Narrative should contain markdown headers');

  console.log('✓ testMarkdownFormat: markdown format works');
}

async function testMissingEntry() {
  const grid = new Grid();
  const transcript = generateTranscript(grid, 'nonexistent_entry');
  if (transcript.chain.length !== 0) throw new Error('Chain should be empty for missing entry');
  if (!transcript.narrative.includes('not found')) throw new Error('Should report entry not found');

  console.log('✓ testMissingEntry: missing entry handled gracefully');
}

async function main() {
  await setup();
  let passed = 0;
  let failed = 0;
  const tests = [testTranscriptChain, testJsonFormat, testMarkdownFormat, testMissingEntry];
  for (const test of tests) {
    try {
      await test();
      passed++;
    } catch (e) {
      console.error(`✗ ${test.name}: ${e.message}`);
      failed++;
    }
    await cleanup();
    await setup();
  }
  await cleanup();
  console.log(`\n═══ Feature 9: Explainability Transcript — ${passed} passed, ${failed} failed ═══`);
  process.exit(failed > 0 ? 1 : 0);
}

main();
