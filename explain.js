/**
 * explain.js — Explainability Transcript
 *
 * Traces entry ancestry via parent_entry chain and builds
 * a readable narrative of how an entry came to be.
 *
 * Endpoints:
 *   GET /explain/:entry_id — generate transcript
 */

function generateTranscript(grid, entryId, options = {}) {
  const store = grid._store || grid._loadStore();
  if (!store || !store.entries) return { entry_id: entryId, chain: [], narrative: 'Store unavailable' };

  const format = options.format || 'narrative';
  const entry = store.entries.find(e => e.id === entryId);
  if (!entry) return { entry_id: entryId, chain: [], narrative: 'Entry not found' };

  // Build the chain by following parent_entry backwards
  const chain = [];
  let currentId = entryId;

  while (currentId) {
    const current = store.entries.find(e => e.id === currentId);
    if (!current) {
      chain.push({
        id: currentId,
        missing: true,
        note: 'Referenced entry not found in store',
      });
      break;
    }

    chain.push({
      id: current.id,
      agent_id: current.agent_id,
      type: current.type,
      tags: current.tags || [],
      content: current.content,
      created_at: current.created_at,
      parent_entry: current.parent_entry || null,
      memory_tier: current.memory_tier,
      outcome: current.outcome || null,
      status: current.status || 'active',
      provenance_trust_score: current.provenance_trust_score || null,
    });

    currentId = current.parent_entry || null;
  }

  // Generate narrative from chain
  const narrative = generateNarrative(chain, format);

  if (format === 'json') {
    return { entry_id: entryId, chain };
  }

  if (format === 'markdown') {
    return { entry_id: entryId, chain, narrative: narrative.markdown };
  }

  return { entry_id: entryId, chain, narrative: narrative.text };
}

function generateNarrative(chain, format = 'narrative') {
  if (!chain || chain.length === 0) {
    return { text: 'No ancestry chain available.', markdown: '# No ancestry chain available.' };
  }

  const textParts = [];
  const mdParts = ['# Memory Provenance Transcript', '', `**Chain length:** ${chain.length} entries`];

  // Root (first in chain = original source, last in chain = current)
  // Chain is built from current → parent, so reverse for chronological
  const chronological = [...chain].reverse();

  let textNarrative = `This entry has ${chain.length} entries in its ancestry chain, spanning from `;
  textNarrative += `${chronological[0].created_at.slice(0, 10)} to ${chronological[chronological.length - 1].created_at.slice(0, 10)}.\n\n`;

  for (let i = 0; i < chronological.length; i++) {
    const e = chronological[i];
    const indent = '  '.repeat(i);
    const time = e.created_at.slice(0, 19).replace('T', ' ');
    const label = i === 0 ? 'SOURCE' : i === chronological.length - 1 ? 'CURRENT' : `STEP ${i}`;
    const outcomeText = e.outcome ? ` [Outcome: ${e.outcome.result}]` : '';

    textNarrative += `${indent}${label} [${e.type}] ${time} (${e.agent_id})${outcomeText}\n`;
    textNarrative += `${indent}Tags: ${(e.tags || []).join(', ') || 'none'}\n`;
    textNarrative += `${indent}Content: ${(e.content || '').slice(0, 300)}\n\n`;

    const mdLabel = i === 0 ? '📦 Source' : i === chronological.length - 1 ? '📍 Current Entry' : `🔗 Step ${i}`;
    const mdOutcome = e.outcome ? ` | **${e.outcome.result}**` : '';
    mdParts.push(`## ${mdLabel}${mdOutcome}`);
    mdParts.push('');
    mdParts.push(`- **Type:** ${e.type}`);
    mdParts.push(`- **Agent:** ${e.agent_id}`);
    mdParts.push(`- **Created:** ${time}`);
    mdParts.push(`- **Tags:** ${(e.tags || []).join(', ') || '*none*'}`);
    mdParts.push(`- **Tier:** ${e.memory_tier || 'working'}`);
    if (e.outcome) {
      mdParts.push(`- **Outcome:** ${e.outcome.result}`);
      mdParts.push(`- **Delta:** ${e.outcome.delta || '*none*'}`);
    }
    mdParts.push('');
    mdParts.push('```');
    mdParts.push((e.content || '').slice(0, 300));
    mdParts.push('```');
    mdParts.push('');
  }

  return {
    text: textNarrative.trim(),
    markdown: mdParts.join('\n'),
  };
}

module.exports = { generateTranscript, generateNarrative };
