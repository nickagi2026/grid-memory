/**
 * provenance.js — Memory Provenance Shield
 *
 * Calculates trust scores for entries and manages quarantine workflow.
 * Uses grid.write() for quarantine audit trail (survives export/import).
 * Security metadata uses schema fields (survives export/import).
 *
 * Endpoints:
 *   GET /provenance/:entry_id — trust score + flags
 *   POST /quarantine/:entry_id — mark entry as quarantined
 *   POST /quarantine/review/:entry_id — approve or reject
 */

function getStore(grid) {
  return grid._store || grid._loadStore();
}

function scoreProvenance(grid, entryId) {
  const store = getStore(grid);
  if (!store || !store.entries) return null;

  const entry = store.entries.find(e => e.id === entryId);
  if (!entry) return null;

  let trustScore = 50;
  const flags = [];

  // Factor 1: Confirmation count (up to +20)
  const confirmationCount =
    store.entries.filter(e => e.id !== entry.id && e.parent_entry === entry.id).length;
  trustScore += Math.min(20, confirmationCount * 5);
  if (confirmationCount > 0) flags.push(`confirmed by ${confirmationCount} downstream entries`);

  // Factor 2: Writer reputation (up to +10)
  const writerEntries = store.entries.filter(e => e.agent_id === entry.agent_id).length;
  trustScore += Math.min(10, writerEntries);
  if (writerEntries > 5) flags.push(`writer has ${writerEntries} entries`);

  // Factor 3: Recency (up to +10 recent, -10 old)
  const ageDays = (Date.now() - new Date(entry.created_at).getTime()) / (1000 * 60 * 60 * 24);
  if (ageDays < 1) trustScore += 10;
  else if (ageDays < 7) trustScore += 5;
  else if (ageDays > 90) trustScore -= 10;
  else if (ageDays > 30) trustScore -= 5;
  if (ageDays > 7) flags.push(`entry is ${Math.round(ageDays)} days old`);

  // Factor 4: Quarantine/Recall/Contamination status
  if (entry.quarantined) { trustScore -= 30; flags.push('entry is quarantined'); }
  if (entry.recalled) { trustScore -= 40; flags.push('entry is recalled'); }
  if (entry.contaminated) { trustScore -= 25; flags.push('entry is cascade-contaminated'); }

  // Factor 5: Read count (up to +5)
  const readCount = entry.read_count || 0;
  trustScore += Math.min(5, readCount);
  if (readCount > 0) flags.push(`read ${readCount} times`);

  return {
    entry_id: entryId,
    trust_score: Math.max(0, Math.min(100, Math.round(trustScore))),
    confirmation_count: confirmationCount,
    read_count: readCount,
    writer_entry_count: writerEntries,
    age_days: Math.round(ageDays),
    quarantined: !!entry.quarantined,
    recalled: !!entry.recalled,
    contaminated: !!entry.contaminated,
    flags,
  };
}

async function quarantineEntry(grid, entryId, reason) {
  // 1. Modify schema fields first (before any grid.write() which may reload store)
  let store = getStore(grid);
  if (!store || !store.entries) return { quarantined: false, message: 'No store' };

  let entry = store.entries.find(e => e.id === entryId);
  if (!entry) return { quarantined: false, message: `Entry ${entryId} not found` };

  entry.quarantined = true;
  entry.quarantine_reason = reason || 'No reason provided';
  entry.quarantined_at = new Date().toISOString();

  // 2. Save the quarantine state
  if (grid._saveStore) grid._saveStore();

  // 3. Create immutable audit trail entry (after save to avoid race)
  await grid.write({
    agent_id: '_system',
    type: 'observation',
    content: `QUARANTINE: Entry ${entryId} — ${reason || 'No reason provided'}`,
    tags: ['_quarantine_event', `quarantine:${entryId}`],
    parent_entry: entryId,
  });

  // 4. Re-fetch entry from current store (grid.write() may have reloaded)
  store = getStore(grid);
  entry = store.entries.find(e => e.id === entryId);
  const qReason = entry ? entry.quarantine_reason : (reason || 'No reason provided');
  const qAt = entry ? entry.quarantined_at : new Date().toISOString();

  if (grid._rebuildIndex) grid._rebuildIndex();

  return { quarantined: true, entry_id: entryId, reason: qReason, quarantined_at: qAt };
}

async function reviewEntry(grid, entryId, decision) {
  if (!['approve', 'reject'].includes(decision)) {
    return { reviewed: false, message: 'Decision must be "approve" or "reject"' };
  }

  // 1. Modify schema fields first
  let store = getStore(grid);
  if (!store || !store.entries) return { reviewed: false, message: 'No store' };

  let entry = store.entries.find(e => e.id === entryId);
  if (!entry) return { reviewed: false, message: `Entry ${entryId} not found` };

  if (decision === 'approve') {
    entry.quarantined = false;
    entry.quarantine_reason = null;
    entry.quarantined_at = null;
  } else {
    entry.quarantined = true;
    entry.quarantine_reason = `Rejected review: ${entry.quarantine_reason || 'No reason'}`;
  }

  // 2. Save the review state
  if (grid._saveStore) grid._saveStore();

  // 3. Create audit trail entry (after save)
  await grid.write({
    agent_id: '_system',
    type: 'observation',
    content: `QUARANTINE_REVIEW: Entry ${entryId} — ${decision}`,
    tags: ['_quarantine_event', `quarantine:${entryId}`, `review:${decision}`],
    parent_entry: entryId,
  });

  return { reviewed: true, entry_id: entryId, decision: decision === 'approve' ? 'approved' : 'rejected' };
}

module.exports = { scoreProvenance, quarantineEntry, reviewEntry };
