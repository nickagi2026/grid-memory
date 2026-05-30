/**
 * cascade.js — Cascade Firewall
 *
 * Tracks propagation chains through parent_entry + schema fields.
 * Uses grid.write() for immutable audit trail on recall events.
 * All security metadata uses schema fields (survives export/import).
 *
 * Endpoints:
 *   GET /cascade/:entry_id — propagation tree
 *   POST /recall/:entry_id — recall an entry + descendants
 */

function getStore(grid) {
  return grid._store || grid._loadStore();
}

function trackPropagation(grid, sourceEntryId, writingEntryId, workspace) {
  const store = getStore(grid);
  if (!store || !store.entries) return { tracked: false };

  const entry = store.entries.find(e => e.id === writingEntryId);
  if (!entry) return { tracked: false };

  // Use schema propagation field (survives export/import)
  if (!Array.isArray(entry.propagation)) entry.propagation = [];
  if (!entry.propagation.some(p => p.source === sourceEntryId)) {
    entry.propagation.push({
      source: sourceEntryId,
      propagated_at: new Date().toISOString(),
      workspace: workspace || '',
    });
  }

  if (grid._saveStore) grid._saveStore();
  return { tracked: true, writing_entry: writingEntryId, source_entry: sourceEntryId };
}

function getCascade(grid, sourceEntryId) {
  const store = getStore(grid);
  if (!store || !store.entries) return { entry_id: sourceEntryId, tree: [] };

  const sourceEntry = store.entries.find(e => e.id === sourceEntryId);
  if (!sourceEntry) return { entry_id: sourceEntryId, tree: [] };

  // Build propagation tree recursively (with cycle guard + depth limit)
  const MAX_DEPTH = 100;
  const visited = new Set();
  function buildTree(entryId, depth = 0) {
    if (depth > MAX_DEPTH) return { entry_id: entryId, truncated: true, children: [] }; // depth limit
    if (visited.has(entryId)) return null; // cycle detected
    visited.add(entryId);
    const entry = store.entries.find(e => e.id === entryId);
    if (!entry) return null;

    const children = store.entries
      .filter(e => e.parent_entry === entryId || 
        (Array.isArray(e.propagation) && e.propagation.some(p => p.source === entryId)))
      .map(e => buildTree(e.id, depth + 1))
      .filter(Boolean);

    return {
      entry_id: entryId,
      agent_id: entry.agent_id,
      type: entry.type,
      content: (entry.content || '').slice(0, 200),
      created_at: entry.created_at,
      depth,
      recalled: !!entry.recalled,
      contaminated: !!entry.contaminated,
      quarantined: !!entry.quarantined,
      children,
    };
  }

  const tree = buildTree(sourceEntryId);
  return {
    entry_id: sourceEntryId,
    source_agent: sourceEntry.agent_id,
    source_type: sourceEntry.type,
    tree,
    node_count: countNodes(tree),
  };
}

function countNodes(node) {
  if (!node) return 0;
  let count = 1;
  for (const child of node.children || []) {
    count += countNodes(child);
  }
  return count;
}

async function recallEntry(grid, entryId, reason) {
  const store = getStore(grid);
  if (!store || !store.entries) return { recalled: false, message: 'No store' };

  const entry = store.entries.find(e => e.id === entryId);
  if (!entry) return { recalled: false, message: `Entry ${entryId} not found` };

  const now = new Date().toISOString();
  const recalled = [];
  const contaminated = [];

  // 1. Mark source entry using schema fields FIRST (before grid.write)
  entry.recalled = true;
  entry.recall_reason = reason || 'No reason provided';
  entry.recalled_at = now;
  recalled.push(entryId);

  // 2. Mark all descendants (before grid.write, so store ref is still valid)
  const MAX_RECALL_DEPTH = 100;
  function markDescendants(parentId, depth = 0) {
    if (depth > MAX_RECALL_DEPTH) return;
    const children = store.entries.filter(e =>
      e.parent_entry === parentId || 
      (Array.isArray(e.propagation) && e.propagation.some(p => p.source === parentId))
    );
    for (const child of children) {
      child.contaminated = true;
      child.contamination_source = parentId;
      child.contamination_detected_at = now;
      child.recall_reason = reason || 'Propagated from recalled source';
      contaminated.push(child.id);
      markDescendants(child.id, depth + 1);
    }
  }
  markDescendants(entryId);

  // 3. Save recall state to store
  if (grid._saveStore) grid._saveStore();

  // 4. Create immutable audit trail entry (after save)
  await grid.write({
    agent_id: '_system',
    type: 'observation',
    content: `RECALL: Entry ${entryId} — ${reason || 'No reason provided'}`,
    tags: ['_recall_event', `recall:${entryId}`],
    parent_entry: entryId,
  });

  if (grid._rebuildIndex) grid._rebuildIndex();

  return {
    recalled: true,
    source_entry: entryId,
    reason: entry.recall_reason,
    recalled_at: now,
    recalled_entries: recalled,
    contaminated_entries: contaminated,
    total_affected: recalled.length + contaminated.length,
  };
}

function getContaminationStatus(grid, entryId) {
  const store = getStore(grid);
  if (!store || !store.entries) return { entry_id: entryId, contaminated: false };

  const entry = store.entries.find(e => e.id === entryId);
  if (!entry) return { entry_id: entryId, contaminated: false, found: false };

  // Check self using schema fields
  if (entry.recalled || entry.contaminated) {
    return {
      entry_id: entryId,
      contaminated: true,
      direct_recall: !!entry.recalled,
      reason: entry.recall_reason || 'Marked as contaminated',
      source: entry.contamination_source || null,
      contaminated_at: entry.contamination_detected_at || entry.recalled_at,
    };
  }

  // Check ancestors
  let currentId = entry.parent_entry;
  while (currentId) {
    const ancestor = store.entries.find(e => e.id === currentId);
    if (!ancestor) break;
    if (ancestor.recalled) {
      return {
        entry_id: entryId,
        contaminated: true,
        direct_recall: false,
        reason: `Ancestor ${currentId} was recalled`,
        source: currentId,
        contaminated_at: ancestor.recalled_at,
      };
    }
    currentId = ancestor.parent_entry;
  }

  return { entry_id: entryId, contaminated: false };
}

module.exports = {
  trackPropagation,
  getCascade,
  recallEntry,
  getContaminationStatus,
};
