#!/usr/bin/env node
/**
 * grid-memory/reference/injector.js
 *
 * Context injection middleware — designed to be called at agent activation.
 * Reads the shared memory grid and prepends a structured context block
 * to the agent's system prompt.
 *
 * This module is the bridge between The Grid and the agent's runtime.
 * It auto-extracts relevant context from the incoming message and
 * surfaces what the agent needs to know.
 *
 * Usage:
 *   const { Injector } = require('./injector.js');
 *   const injector = new Injector();
 *   const ctx = await injector.prepare("user says: finish the auth module");
 *   // ctx.block → system context block
 *   // ctx.meta → injection metadata
 */

const path = require('path');
const { Grid } = require('./store.js');

class Injector {
  constructor(options = {}) {
    this.grid = new Grid(options);
    this.maxInjectBytes = options.maxInjectBytes || 4096;
    this.maxEntries = options.maxEntries || 8;
    // Tags that automatically activate (always included when present)
    this.alwaysTags = options.alwaysTags || [];
  }

  /**
   * Prepare a context injection block for an agent activation.
   *
   * @param {string} incomingMessage - The message that triggered the agent
   * @param {object} options - Optional overrides
   * @param {string} options.agentId - The receiving agent's ID
   * @param {string[]} options.forceTags - Tags to always include
   * @param {number} options.maxBytes - Max block size
   * @returns {Promise<{block: string, meta: object}>}
   */
  async prepare(incomingMessage = '', options = {}) {
    const maxBytes = options.maxBytes || this.maxInjectBytes;
    const agentId = options.agentId || this._detectAgentId();

    // Extract relevant tags from the message
    const messageTags = this._extractTags(incomingMessage);
    const forceTags = [...new Set([...this.alwaysTags, ...(options.forceTags || [])])];

    // First pass: query with message-derived tags
    let readResult = await this.grid.read({
      tags: [...messageTags, ...forceTags],
      max: this.maxEntries,
      tagMode: 'OR'
    });

    // Second pass: if no results, get most recent entries
    if (readResult.entries.length === 0) {
      readResult = await this.grid.read({
        max: 5,
        tagMode: 'OR'
      });
    }

    // Build the block
    const entries = readResult.entries;
    let block = '';
    let entryCount = 0;

    // Only build block if there's something to say
    if (entries.length > 0) {
      block += '─── SHARED MEMORY GRID ───\n\n';
      block += `Recent shared context for "${agentId}"`;
      if (messageTags.length > 0) {
        block += ` (filtered: ${messageTags.join(', ')})`;
      }
      block += `:\n\n`;

      for (const entry of entries) {
        const time = entry.created_at.slice(11, 16);
        const date = entry.created_at.slice(0, 10);
        const tags = (entry.tags || []).join(', ');
        const snippet = entry.content.length > 250
          ? entry.content.slice(0, 250) + '…'
          : entry.content;

        block += `[${entry.type}] ${date} ${time} · ${entry.agent_id}`;
        if (tags) block += ` · ${tags}`;
        block += `\n  ${snippet}\n\n`;
        entryCount++;
      }

      block += '─── END GRID ───';
    }

    // Enforce size limit
    if (Buffer.byteLength(block, 'utf-8') > maxBytes) {
      block = this._truncateBlock(block, maxBytes, entryCount);
    }

    return {
      block,
      meta: {
        entry_count: entryCount,
        bytes: Buffer.byteLength(block, 'utf-8'),
        max_bytes: maxBytes,
        truncated: Buffer.byteLength(block, 'utf-8') > maxBytes,
        query_tags: messageTags,
        force_tags: forceTags,
        total_store_entries: readResult.query_meta?.total_before_filter || 0
      }
    };
  }

  /**
   * Inject context into an agent's message array.
   * Returns a new messages array with the context block injected.
   *
   * @param {Array} messages - The agent's messages array
   * @param {string} incomingMessage - The user's message
   * @param {object} options - Options for prepare()
   * @returns {Promise<Array>} Modified messages array
   */
  async injectIntoMessages(messages, incomingMessage = '', options = {}) {
    const ctx = await this.prepare(incomingMessage, options);
    if (!ctx.block) return messages; // No context to inject

    // Find the system message index
    const sysIdx = messages.findIndex(m => m.role === 'system');
    if (sysIdx !== -1) {
      // Append context to existing system message
      const existing = messages[sysIdx].content;
      messages[sysIdx] = {
        ...messages[sysIdx],
        content: existing + '\n\n' + ctx.block
      };
    } else {
      // Insert as a new system message at the beginning
      messages.unshift({ role: 'system', content: ctx.block });
    }

    return messages;
  }

  // ── Private helpers ──

  _detectAgentId() {
    // Try to detect from env or process
    return process.env.GRID_AGENT_ID || process.env.OPENCLAW_AGENT_ID || 'unknown';
  }

  _extractTags(text) {
    if (!text || typeof text !== 'string') return [];
    const lower = text.toLowerCase();

    // Common domain-specific tag patterns
    const patterns = [
      // Direct tag references
      ...(lower.match(/(?:project|tag|scope)[:\s]+(\S+)/gi) || []).map(m => m.toLowerCase()),
      // Architecture keywords
      ...(lower.match(/(?:architecture|design|stack|database|api|auth)/gi) || []).map(m => m.toLowerCase()),
      // Task types
      ...(lower.match(/(?:decision|review|handoff|blocker|deploy|bug)/gi) || []).map(m => m.toLowerCase()),
    ];

    return [...new Set(patterns)].filter(Boolean).slice(0, 8);
  }

  _truncateBlock(block, maxBytes, entryCount) {
    // Keep header, drop entries from the end until under limit
    const lines = block.split('\n');
    const headerEnd = lines.findIndex(l => l.startsWith('[decision]') || l.startsWith('[fact]'));
    if (headerEnd === -1) return block.slice(0, maxBytes);

    const header = lines.slice(0, headerEnd).join('\n') + '\n';
    const footer = '\n─── END GRID ───';
    let body = lines.slice(headerEnd).join('\n');

    // Remove entries from the end until under limit or we've removed half
    let kept = entryCount;
    while (Buffer.byteLength(header + body + footer, 'utf-8') > maxBytes && kept > 1) {
      // Find the last [type] block and remove it
      const lastEntryIdx = body.lastIndexOf('\n\n[');
      if (lastEntryIdx === -1) break;
      body = body.slice(0, lastEntryIdx);
      kept--;
    }

    // If still over limit, hard truncate
    const result = header + body + footer;
    if (Buffer.byteLength(result, 'utf-8') > maxBytes) {
      return header + `\n[Showing ${kept} of ${entryCount} entries — truncated to fit]\n` + footer;
    }

    return result;
  }
}

module.exports = { Injector };
