/**
 * deduplication.js — Semantic Deduplication Engine
 *
 * When multiple agents write about the same fact, instead of creating N entries,
 * increment a confirmation_count on the existing entry and update last_confirmed_at.
 *
 * This is lossless, semantically meaningful compression. The more agents agree,
 * the stronger the signal.
 */

const crypto = require('crypto');

// ─── Configuration ──────────────────────────────────────────────────────────

// Configurable via env vars: GRID_DEDUP_SCAN_LIMIT, GRID_DEDUP_THRESHOLD
const SCAN_LIMIT = parseInt(process.env.GRID_DEDUP_SCAN_LIMIT || '50', 10);
const SIMILARITY_THRESHOLD = parseFloat(process.env.GRID_DEDUP_THRESHOLD || '0.85');
const FINGERPRINT_LENGTH = 64;

// Min word length for overlap comparison (short words like "API" are significant)
const MIN_WORD_LENGTH = 2;

// ─── Content Fingerprinting ────────────────────────────────────────────────

function fingerprint(content) {
  // Normalize: lowercase, collapse whitespace, remove punctuation
  const normalized = content
    .toLowerCase()
    .replace(/[^\w\s]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
  // Create a hash-based fingerprint
  return crypto.createHash('sha256').update(normalized).digest('hex').slice(0, FINGERPRINT_LENGTH);
}

// ─── Simple Word Overlap Similarity ─────────────────────────────────────────

function wordOverlapSimilarity(a, b) {
  const wordsA = new Set(a.toLowerCase().split(/\s+/).filter(w => w.length >= MIN_WORD_LENGTH));
  const wordsB = new Set(b.toLowerCase().split(/\s+/).filter(w => w.length >= MIN_WORD_LENGTH));
  if (wordsA.size === 0 || wordsB.size === 0) return 0;
  const intersection = new Set([...wordsA].filter(w => wordsB.has(w)));
  const union = new Set([...wordsA, ...wordsB]);
  return intersection.size / union.size;
}

// ─── Find Potential Duplicates ─────────────────────────────────────────────

async function findDuplicate(grid, content, tags, agentId, workspace) {
  // Get recent entries that share at least one tag (scoped to workspace)
  const queryTags = workspace ? [...tags, `ws:${workspace}`] : (tags.length > 0 ? tags : []);
  const result = await grid.read({ tags: queryTags, max: SCAN_LIMIT, tagMode: 'AND' });
  const entries = result.entries || [];

  const contentFP = fingerprint(content);
  let bestMatch = null;
  let bestScore = 0;

  for (const entry of entries) {
    // Skip entries from the same agent (intentional duplicates allowed)
    if (entry.agent_id === agentId) continue;

    const existingContent = entry.content || '';
    const existingFP = fingerprint(existingContent);

    // Quick check: identical fingerprints are likely duplicates
    if (contentFP === existingFP) {
      bestMatch = entry;
      bestScore = 1.0;
      break;
    }

    // Word overlap similarity for semantic comparison
    const similarity = wordOverlapSimilarity(content, existingContent);
    if (similarity > bestScore) {
      bestScore = similarity;
      bestMatch = entry;
    }
  }

  if (bestMatch && bestScore >= SIMILARITY_THRESHOLD) {
    return {
      isDuplicate: true,
      existingEntry: bestMatch,
      similarity: bestScore,
    };
  }

  return { isDuplicate: false, similarity: bestScore };
}

// ─── Confirm an Existing Entry ─────────────────────────────────────────────

async function confirmEntry(grid, entryId, agentId, workspace) {
  // Write a confirmation metadata entry (immutable, tracks provenance)
  const tags = ['_dedup', `confirms:${entryId}`];
  if (workspace) tags.push(`ws:${workspace}`);
  await grid.write({
    agent_id: agentId || '_system',
    type: 'observation',
    content: `Confirmed entry ${entryId} (duplicate suppression, workspace: ${workspace || 'global'})`,
    tags,
    parent_entry: entryId,
  });

  return { confirmed: true, entry_id: entryId };
}

// ─── Module Exports ────────────────────────────────────────────────────────

module.exports = {
  findDuplicate,
  confirmEntry,
  fingerprint,
  wordOverlapSimilarity,
};
