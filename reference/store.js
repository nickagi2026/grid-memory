#!/usr/bin/env node
/**
 * grid-memory/store.js
 *
 * Reference implementation of The Grid — a shared persistent memory store
 * for multi-agent teams. Append-only writes, relevance-weighted reads,
 * TTL-based pruning, and context injection.
 *
 * IMPORTANT: Single-process constraint.
 * The file-based JSON store uses an in-memory write lock (a Map on the Grid instance).
 * This lock is invisible to other processes. Running two instances against the
 * same JSON file (e.g. multiple Docker replicas, CLI + server simultaneously)
 * WILL cause data loss due to concurrent write races.
 *
 * For multi-process deployments, use the SQLite backend or a single server process.
 *
 * Architecture:
 *   - File-based JSON store at ~/.openclaw/workspace/skills/shared-memory-grid/data/store.json
 *   - Tags indexed in data/index.json for fast retrieval
 *   - Append-only writes: never modifies existing entries
 *   - Relevance scoring: tag match > type match > recency
 *
 * Usage (CLI):
 *   node store.js write --agent main --type decision --tags project:alpha --ttl 86400 --content "..."
 *   node store.js read --tags project:alpha --max 10
 *   node store.js inject --context "user is asking about database"
 *   node store.js prune
 *   node store.js info
 *   node store.js forget --id grid_xxxxx
 *
 * Usage (module):
 *   const { Grid } = require('./store.js');
 *   const grid = new Grid();
 *   await grid.write({ agent_id: "main", type: "decision", ... });
 *   const results = await grid.read({ tags: ["project:alpha"] });
 *   const ctx = await grid.inject("agent just spawned");
 */

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

// ─── Configuration ────────────────────────────────────────────────────────────

const CONFIG = {
  STORE_DIR: process.env.GRID_STORE_DIR || path.join(
    process.env.HOME || process.env.USERPROFILE || '/tmp',
    '.openclaw', 'grid', 'data'
  ),
  STORE_FILE: 'store.json',
  INDEX_FILE: 'index.json',
  MAX_INJECT_SIZE: 4096,            // max bytes for context injection block
  DEFAULT_MAX_RESULTS: 10,
  ABSOLUTE_MAX_RESULTS: 100000,
  MAX_STORE_SIZE_MB: 10,
  COMPRESSION_THRESHOLD_MB: 5,
  // Default TTLs by type (seconds)
  DEFAULT_TTLS: {
    decision: 86400,         // 24 hours
    fact: 86400,             // 24 hours
    task_status: 3600,       // 1 hour
    artifact_ref: 604800,    // 7 days
    handoff: 3600,           // 1 hour
    question: 43200,         // 12 hours
    observation: 86400,      // 24 hours
    blocker: 86400,          // 24 hours
    state_update: 3600       // 1 hour
  },
  VALID_TYPES: [
    'decision', 'fact', 'task_status', 'artifact_ref',
    'handoff', 'question', 'observation', 'blocker', 'state_update',
    'synthesis'
  ]
};

// Instance-level path functions (respect runtime STORE_DIR override)
function getStorePath(instance) {
  const dir = instance && instance.config && instance.config.STORE_DIR ? instance.config.STORE_DIR : CONFIG.STORE_DIR;
  return path.join(dir, CONFIG.STORE_FILE);
}
function getIndexPath(instance) {
  const dir = instance && instance.config && instance.config.STORE_DIR ? instance.config.STORE_DIR : CONFIG.STORE_DIR;
  return path.join(dir, CONFIG.INDEX_FILE);
}

// ─── Utility ──────────────────────────────────────────────────────────────────

function generateId() {
  const date = new Date().toISOString().slice(0, 10).replace(/-/g, '');
  const random = crypto.randomBytes(6).toString('hex');
  return `grid_${date}_${random}`;
}

function now() {
  return new Date().toISOString();
}

function nowUnix() {
  return Math.floor(Date.now() / 1000);
}

function assert(condition, message) {
  if (!condition) {
    throw new Error(`[Grid] ${message}`);
  }
}

// ─── The Grid Core ────────────────────────────────────────────────────────────

class Grid {
  constructor(options = {}) {
    this.config = { ...CONFIG, ...options };
    this._store = null;
    this._index = null;
    this._lock = new Map();
    this._ensureDir();
  }

  // ── Write lock (prevents concurrent write races) ──

  async _acquireLock() {
    while (this._lock.get('write')) {
      await new Promise(r => setTimeout(r, 10));
    }
    this._lock.set('write', true);
  }

  _releaseLock() {
    this._lock.delete('write');
  }

  // ── Initialization ──

  _ensureDir() {
    if (!fs.existsSync(this.config.STORE_DIR)) {
      fs.mkdirSync(this.config.STORE_DIR, { recursive: true });
    }
  }

  _loadStore() {
    const sp = getStorePath(this);
    try {
      if (fs.existsSync(sp)) {
        const raw = fs.readFileSync(sp, 'utf-8');
        this._store = JSON.parse(raw);
        // Migrate v0 → v1 if needed
        if (!Array.isArray(this._store.entries)) {
          // Old format: top-level array
          this._store = { version: 1, created_at: now(), entries: this._store };
        }
      } else {
        this._store = { version: 1, created_at: now(), entries: [] };
      }
    } catch (err) {
      // Corruption recovery
      const backup = `${sp}.corrupt.${nowUnix()}`;
      console.error(`[Grid] Store corruption detected. Backing up to ${backup}`);
      if (fs.existsSync(sp)) {
        fs.renameSync(sp, backup);
      }
      this._store = { version: 1, created_at: now(), entries: [], _recovered_from: backup };
    }
    return this._store;
  }

  _loadIndex() {
    const ip = getIndexPath(this);
    try {
      if (fs.existsSync(ip)) {
        this._index = JSON.parse(fs.readFileSync(ip, 'utf-8'));
      } else {
        this._index = { version: 1, tags: {}, agents: {}, types: {} };
      }
    } catch {
      this._index = { version: 1, tags: {}, agents: {}, types: {} };
    }
    return this._index;
  }

  _saveStore() {
    const sp = getStorePath(this);
    fs.writeFileSync(sp, JSON.stringify(this._store, null, 2), 'utf-8');
  }

  _saveIndex() {
    const ip = getIndexPath(this);
    fs.writeFileSync(ip, JSON.stringify(this._index, null, 2), 'utf-8');
  }

  _rebuildIndex() {
    const index = { version: 1, tags: {}, agents: {}, types: {} };
    for (const entry of this._store.entries) {
      // Tags
      for (const tag of entry.tags || []) {
        if (!index.tags[tag]) index.tags[tag] = [];
        index.tags[tag].push(entry.id);
      }
      // Agent
      if (entry.agent_id) {
        if (!index.agents[entry.agent_id]) index.agents[entry.agent_id] = [];
        index.agents[entry.agent_id].push(entry.id);
      }
      // Type
      if (entry.type) {
        if (!index.types[entry.type]) index.types[entry.type] = [];
        index.types[entry.type].push(entry.id);
      }
    }
    this._index = index;
    this._saveIndex();
  }

  // ── Validation ──

  _validateWrite(write) {
    assert(write.agent_id, 'agent_id is required');
    assert(write.content, 'content is required');
    assert(typeof write.content === 'string', 'content must be a string');
    if (write.type) {
      assert(
        this.config.VALID_TYPES.includes(write.type),
        `Invalid type "${write.type}". Valid types: ${this.config.VALID_TYPES.join(', ')}`
      );
    }
    // Sanity check: don't store secrets
    const secretPatterns = [
      /PRIVATE_KEY/i, /-----BEGIN.*PRIVATE KEY-----/,
      /ghp_[a-zA-Z0-9]{36}/, /sk-[a-zA-Z0-9]{32,}/,
      /AKIA[0-9A-Z]{16}/
    ];
    for (const pat of secretPatterns) {
      if (pat.test(write.content)) {
        throw new Error(`[Grid] Write rejected: content appears to contain a secret (matched: ${pat})`);
      }
    }
  }

  // ── Write ──

  async write(write = {}) {
    await this._acquireLock();
    try {
    this._validateWrite(write);
    this._loadStore();

    const type = write.type || 'observation';
    const ttl = write.ttl_seconds || this.config.DEFAULT_TTLS[type] || 86400;
    const entry = {
      id: write.force_id || generateId(),
      session_id: write.session_id || '',
      agent_id: write.agent_id,
      type: type,
      tags: write.tags || [],
      content: write.content.trim(),
      ttl_seconds: ttl,
      created_at: write.force_created_at || now(),
      expires_at: write.force_expires_at || new Date(Date.now() + (ttl * 1000)).toISOString(),
      parent_entry: write.parent_entry || null,
      last_read_at: null,
      memory_tier: write.memory_tier || 'working',
      read_count: 0,
      workspace_id: write.workspace_id || '',
      status: write.status || 'active',
      outcome: write.outcome || null,
      requires_approval: write.requires_approval || null,
      origin_trust: write.origin_trust || 'native',
      provenance_trust_score: write.provenance_trust_score || null,
      staleness_score: write.staleness_score || null,
      // Security metadata (survives export/import)
      embedding: write.embedding || null,
      quarantined: write.quarantined || false,
      quarantine_reason: write.quarantine_reason || null,
      quarantined_at: write.quarantined_at || null,
      recalled: write.recalled || false,
      recall_reason: write.recall_reason || null,
      recalled_at: write.recalled_at || null,
      contaminated: write.contaminated || false,
      contamination_source: write.contamination_source || null,
      contamination_detected_at: write.contamination_detected_at || null,
      propagation: write.propagation || [],
    };

    this._store.entries.push(entry);
    this._saveStore();

    // Update index
    this._loadIndex();
    for (const tag of entry.tags) {
      if (!this._index.tags[tag]) this._index.tags[tag] = [];
      this._index.tags[tag].push(entry.id);
    }
    if (!this._index.agents[entry.agent_id]) this._index.agents[entry.agent_id] = [];
    this._index.agents[entry.agent_id].push(entry.id);
    if (!this._index.types[type]) this._index.types[type] = [];
    this._index.types[type].push(entry.id);
    this._saveIndex();

    // Auto-prune if store is large
    const storeSize = Buffer.byteLength(JSON.stringify(this._store)) / (1024 * 1024);
    if (storeSize > this.config.COMPRESSION_THRESHOLD_MB) {
      this._pruneInternal();
    }

    return {
      entry_id: entry.id,
      agent_id: entry.agent_id,
      type: entry.type,
      tags: entry.tags,
      created_at: entry.created_at,
      ttl_seconds: entry.ttl_seconds,
      expires_at: entry.expires_at,
      memory_tier: entry.memory_tier,
      workspace_id: entry.workspace_id,
      status: entry.status,
      outcome: entry.outcome,
      requires_approval: entry.requires_approval,
      origin_trust: entry.origin_trust,
      provenance_trust_score: entry.provenance_trust_score,
      staleness_score: entry.staleness_score,
      quarantined: entry.quarantined,
      quarantine_reason: entry.quarantine_reason,
      recalled: entry.recalled,
      recall_reason: entry.recall_reason,
      recalled_at: entry.recalled_at,
      contaminated: entry.contaminated,
      contamination_source: entry.contamination_source,
      propagation: entry.propagation,
      store_entries_count: this._store.entries.length
    };
    } finally {
      this._releaseLock();
    }
  }

  // ── Update Outcome ──

  async updateOutcome(entryId, outcome) {
    assert(outcome && outcome.result, 'outcome.result is required');
    assert(['success','failure','partial'].includes(outcome.result), 'outcome.result must be success/failure/partial');
    this._loadStore();
    const entry = this._store.entries.find(e => e.id === entryId);
    if (!entry) return { found: false, message: `Entry ${entryId} not found` };
    entry.outcome = {
      result: outcome.result,
      delta: outcome.delta || '',
      notes: outcome.notes || '',
      recorded_at: new Date().toISOString()
    };
    this._saveStore();
    return { found: true, entry_id: entryId, outcome: entry.outcome };
  }

  // ── Promote Draft ──

  async promoteEntry(entryId) {
    this._loadStore();
    const entry = this._store.entries.find(e => e.id === entryId);
    if (!entry) return { found: false, message: `Entry ${entryId} not found` };
    entry.status = 'active';
    this._saveStore();
    return { found: true, entry_id: entryId, status: 'active' };
  }

  // ── Read ──

  async read(query = {}) {
    this._loadStore();

    const maxResults = Math.min(
      query.max || this.config.DEFAULT_MAX_RESULTS,
      this.config.ABSOLUTE_MAX_RESULTS
    );
    const tags = query.tags || [];
    const agents = query.agents || [];
    const types = query.types || [];
    const type = query.type || null; // single type shorthand
    const since = query.since || null; // ISO timestamp
    const tagMode = query.tagMode || 'OR'; // AND | OR
    const parent_entry = query.parent_entry || null;
    const include_drafts = query.include_drafts || false;

    // Filter expired
    const nowTs = now();
    let entries = this._store.entries.filter(e => e.expires_at >= nowTs);

    // Filter out drafts unless requested
    if (!include_drafts) {
      entries = entries.filter(e => e.status !== 'draft');
    }

    // Filter by parent
    if (parent_entry) {
      entries = entries.filter(e => e.parent_entry === parent_entry || e.id === parent_entry);
    }

    // Filter by tags
    if (tags.length > 0) {
      entries = entries.filter(e => {
        const eTags = new Set(e.tags || []);
        if (tagMode === 'AND') {
          return tags.every(t => eTags.has(t));
        } else {
          return tags.some(t => eTags.has(t));
        }
      });
    }

    // Filter by agents
    if (agents.length > 0) {
      const agentSet = new Set(agents);
      entries = entries.filter(e => agentSet.has(e.agent_id));
    }

    // Filter by type
    if (type) {
      entries = entries.filter(e => e.type === type);
    } else if (types.length > 0) {
      const typeSet = new Set(types);
      entries = entries.filter(e => typeSet.has(e.type));
    }

    // Filter by time
    if (since) {
      entries = entries.filter(e => e.created_at >= since);
    }
    if (query.before) {
      entries = entries.filter(e => e.created_at <= query.before);
    }

    // Score and sort by relevance
    entries = this._scoreAndSort(entries, tags, agents, type || types, query.q);

    // Limit
    const results = entries.slice(0, maxResults);

    // Update last_read_at and read_count on the store entries, then reflect in results
    const nowIso = now();
    for (const result of results) {
      const storeEntry = this._store.entries.find(e => e.id === result.id);
      if (storeEntry) {
        storeEntry.last_read_at = nowIso;
        storeEntry.read_count = (storeEntry.read_count || 0) + 1;
        result.read_count = storeEntry.read_count;  // Sync back to result copy
      }
    }
    this._saveStore();

    const totalBefore = this._store.entries.length;
    const expiredCount = totalBefore - this._store.entries.filter(e => e.expires_at >= now()).length;

    return {
      entries: results.map(e => ({
        id: e.id,
        agent_id: e.agent_id,
        type: e.type,
        tags: e.tags,
        content: e.content,
        created_at: e.created_at,
        expires_at: e.expires_at,
        parent_entry: e.parent_entry,
        memory_tier: e.memory_tier,
        workspace_id: e.workspace_id,
        read_count: e.read_count,
        status: e.status,
        outcome: e.outcome,
        requires_approval: e.requires_approval,
        origin_trust: e.origin_trust,
        provenance_trust_score: e.provenance_trust_score,
        staleness_score: e.staleness_score
      })),
      query_meta: {
        total_before_filter: totalBefore,
        expired_filtered: expiredCount,
        returned: results.length,
        query: { tags, agents, types, since, tagMode, maxResults }
      }
    };
  }

  _scoreAndSort(entries, queryTags, queryAgents, queryTypes, queryText) {
    const nowTs = nowUnix();
    return entries.map(e => {
      let score = 0;

      // Semantic score (if query text and embedding available)
      if (queryText && e.embedding) {
        // score already computed and stored as _score during query processing
        // preserve any pre-computed semantic score
      }

      // Tag match score
      if (queryTags.length > 0) {
        const eTags = new Set(e.tags || []);
        const matchCount = queryTags.filter(t => eTags.has(t)).length;
        score += matchCount * 10; // each matching tag = 10 points
      }

      // Type match score
      const qTypes = Array.isArray(queryTypes) ? queryTypes : [queryTypes];
      if (qTypes.length > 0 && qTypes.includes(e.type)) {
        score += 5;
      }

      // Agent match score
      if (queryAgents.length > 0 && queryAgents.includes(e.agent_id)) {
        score += 3;
      }

      // Recency bonus: entries created within last 30 minutes get +2, last 5 minutes get +5
      const ageSeconds = nowTs - new Date(e.created_at).getTime() / 1000;
      if (ageSeconds < 300) score += 5;
      else if (ageSeconds < 1800) score += 2;

      return { ...e, _score: score };
    })
    .sort((a, b) => b._score - a._score);
  }

  // ── Prune ──

    /**
   * Internal prune — no lock. Called from write() which already holds the lock.
   */
  _pruneInternal() {
    if (!this._store) {
      this._loadStore();
    }
    const before = this._store.entries.length;
    const nowTs = now();
    const alive = this._store.entries.filter(e => e.expires_at >= nowTs);
    const removed = before - alive.length;
    this._store.entries = alive;
    this._saveStore();

    const storeSize = Buffer.byteLength(JSON.stringify(this._store)) / (1024 * 1024);
    if (storeSize > this.config.COMPRESSION_THRESHOLD_MB) {
      this._compress();
    }

    this._rebuildIndex();
    return { removed, remaining: alive.length, total_before: before };
  }

  async prune() {
    await this._acquireLock();
    try {
      return this._pruneInternal();
    } finally {
      this._releaseLock();
    }
  }

  /**
   * Compress the store by keeping only the 3 most recent entries per type/agent/day.
   * Writes a summary entry before removing data. Errors are logged, never silent.
   */
  _compress() {
    const startCount = this._store.entries.length;
    let error = null;

    try {
      const groups = {};
      for (const entry of this._store.entries) {
        const date = entry.created_at.slice(0, 10);
        const key = `${entry.type}:${entry.agent_id}:${date}`;
        if (!groups[key]) groups[key] = [];
        groups[key].push(entry);
      }

      let keptCount = 0;
      const newEntries = [];
      for (const [key, group] of Object.entries(groups)) {
        group.sort((a, b) => b.created_at.localeCompare(a.created_at));
        const kept = group.slice(0, 3);
        newEntries.push(...kept);
        keptCount += kept.length;
      }

      const removed = startCount - keptCount;
      if (removed > 0) {
        const summaryEntry = {
          id: generateId(), session_id: '', agent_id: '_system',
          type: 'observation', tags: ['compression', '_system'],
          content: `Compression removed ${removed} entries (${keptCount} kept). Groups: ${Object.keys(groups).length}. Time: ${now()}.`,
          ttl_seconds: this.config.DEFAULT_TTLS.observation || 86400,
          created_at: now(),
          expires_at: new Date(Date.now() + (this.config.DEFAULT_TTLS.observation || 86400) * 1000).toISOString(),
          parent_entry: null, last_read_at: null,
        };
        newEntries.push(summaryEntry);
      }
      this._store.entries = newEntries;
    } catch (err) {
      error = err.message || String(err);
      console.error(`[Grid] Compression failed: ${error}. Store unchanged (${startCount} entries).`);
    }

    if (error) {
      // Log the failure as a store entry so agents can see it
      try {
        const errorEntry = {
          id: generateId(), session_id: '', agent_id: '_system',
          type: 'observation', tags: ['compression', '_system', 'compression-error'],
          content: `Compression failed: ${error}. Store size: ${startCount} entries.`,
          ttl_seconds: this.config.DEFAULT_TTLS.observation || 86400,
          created_at: now(),
          expires_at: new Date(Date.now() + 86400000).toISOString(),
          parent_entry: null, last_read_at: null,
        };
        this._store.entries.push(errorEntry);
      } catch (e) { /* last-resort silent */ }
    }
  }

  // ── Context Injection ──

  async inject(contextHint = '') {
    this._loadStore();

    // Extract potential tags from the context hint
    const hintTags = this._extractTags(contextHint);

    // Query for relevant entries
    const result = await this.read({
      tags: hintTags,
      max: this.config.DEFAULT_MAX_RESULTS,
      tagMode: 'OR'
    });

    // If no tag matches, fall back to most recent entries
    let entries = result.entries;
    if (entries.length === 0) {
      const allAlive = this._store.entries
        .filter(e => e.expires_at >= now())
        .sort((a, b) => b.created_at.localeCompare(a.created_at))
        .slice(0, 5);
      entries = allAlive.map(e => ({
        id: e.id, agent_id: e.agent_id, type: e.type,
        tags: e.tags, content: e.content,
        created_at: e.created_at, expires_at: e.expires_at
      }));
    }

    // Build context block with size limit
    let block = '─── SHARED MEMORY GRID ───\n\n';
    block += `Recent entries (filtered: ${result.query_meta.returned} of ${result.query_meta.total_before_filter} total):\n\n`;

    for (const entry of entries) {
      const time = entry.created_at.slice(11, 16);
      const tags = (entry.tags || []).join(', ');
      const snippet = entry.content.length > 200
        ? entry.content.slice(0, 200) + '…'
        : entry.content;
      block += `[${entry.type}] ${time} — agent:${entry.agent_id}`;
      if (tags) block += ` — ${tags}`;
      block += `\n${snippet}\n\n`;
    }

    block += '─── END GRID ───';

    // Respect size limit
    const blockBytes = Buffer.byteLength(block, 'utf-8');
    if (blockBytes > this.config.MAX_INJECT_SIZE) {
      // Truncate entries from the end, preserving header and footer
      const header = block.slice(0, 200);
      const footer = '\n\n─── END GRID ───';
      const maxBody = this.config.MAX_INJECT_SIZE - Buffer.byteLength(header + footer, 'utf-8');

      // Build truncated body by including entries until we hit the limit
      const lines = block.split('\n');
      let truncatedBody = '';
      for (const line of lines) {
        const candidate = truncatedBody ? truncatedBody + '\n' + line : line;
        if (Buffer.byteLength(candidate, 'utf-8') <= maxBody) {
          truncatedBody = candidate;
        } else {
          truncatedBody += '\n... and more entries (truncated to fit size limit)';
          break;
        }
      }
      block = header + truncatedBody + footer;
    }

    return { block, entry_count: entries.length, bytes: Buffer.byteLength(block, 'utf-8') };
  }

  _extractTags(text) {
    // Extract potential tags from natural language:
    // - Project names (project:X patterns in existing tags)
    // - Words that match existing tags
    if (!text) return [];

    this._loadIndex();
    const existingTags = Object.keys(this._index.tags || {});
    if (existingTags.length === 0) return [];

    const words = text.toLowerCase().split(/\s+/);
    const matched = existingTags.filter(tag => {
      const lowerTag = tag.toLowerCase();
      return words.some(w => lowerTag.includes(w) || w.includes(lowerTag));
    });

    return matched.slice(0, 5); // limit to 5 tag matches
  }

  // ── Forget ──

  async forget(entryId) {
    this._loadStore();
    const idx = this._store.entries.findIndex(e => e.id === entryId);
    if (idx === -1) {
      return { found: false, message: `Entry ${entryId} not found` };
    }
    const entry = this._store.entries.splice(idx, 1)[0];
    this._saveStore();
    this._rebuildIndex();
    return { found: true, entry_id: entry.id, type: entry.type, agent_id: entry.agent_id };
  }

  // ── Info ──

  async info() {
    this._loadStore();
    const entries = this._store.entries;
    const nowTs = now();

    // Stats by type
    const byType = {};
    for (const e of entries) {
      byType[e.type] = (byType[e.type] || 0) + 1;
    }

    // Stats by agent
    const byAgent = {};
    for (const e of entries) {
      byAgent[e.agent_id] = (byAgent[e.agent_id] || 0) + 1;
    }

    // Unique tags
    const allTags = new Set();
    for (const e of entries) {
      for (const t of e.tags || []) allTags.add(t);
    }

    const alive = entries.filter(e => e.expires_at >= nowTs);
    const expired = entries.length - alive.length;
    const storeSize = Buffer.byteLength(JSON.stringify(this._store)) / 1024;

    return {
      total_entries: entries.length,
      alive_entries: alive.length,
      expired_entries: expired,
      unique_agents: Object.keys(byAgent).length,
      unique_tags: allTags.size,
      store_size_kb: Math.round(storeSize * 10) / 10,
      by_type: byType,
      by_agent: byAgent,
      oldest_entry: entries.length > 0 ? entries[0].created_at : null,
      newest_entry: entries.length > 0 ? entries[entries.length - 1].created_at : null,
      store_version: this._store.version
    };
  }

  // ── Export (bypasses query limits) ──

  async exportAll() {
    this._loadStore();
    const nowTs = now();
    const alive = this._store.entries.filter(e => e.expires_at >= nowTs);
    return {
      version: 1,
      exported_at: now(),
      entry_count: alive.length,
      entries: alive.map(e => ({
        id: e.id, agent_id: e.agent_id, type: e.type,
        tags: e.tags, content: e.content,
        created_at: e.created_at, expires_at: e.expires_at,
        ttl_seconds: e.ttl_seconds, parent_entry: e.parent_entry,
        session_id: e.session_id, memory_tier: e.memory_tier,
        promoted_from: e.promoted_from, workspace_id: e.workspace_id,
        read_count: e.read_count, last_read_at: e.last_read_at,
        embedding: e.embedding,
        status: e.status,
        outcome: e.outcome,
        requires_approval: e.requires_approval,
        origin_trust: e.origin_trust,
        provenance_trust_score: e.provenance_trust_score,
        staleness_score: e.staleness_score,
        embedding: e.embedding,
        quarantined: e.quarantined,
        quarantine_reason: e.quarantine_reason,
        recalled: e.recalled,
        recall_reason: e.recall_reason,
        recalled_at: e.recalled_at,
        contaminated: e.contaminated,
        contamination_source: e.contamination_source,
        propagation: e.propagation,
      })),
    };
  }

  // ── Wipe (for testing) ──

  async wipe(confirm = false) {
    if (!confirm) {
      return { wiped: false, message: 'Confirmation required. Call wipe(true) to confirm.' };
    }
    this._store = { version: 1, created_at: now(), entries: [] };
    this._index = { version: 1, tags: {}, agents: {}, types: {} };
    this._saveStore();
    this._saveIndex();
    return { wiped: true, message: 'Shared memory grid cleared.' };
  }
}

// ─── CLI ──────────────────────────────────────────────────────────────────────

async function main() {
  const args = process.argv.slice(2);
  const command = args[0];

  if (!command) {
    console.log('Usage:');
    console.log('  node store.js write --agent <id> --type <type> --tags <a,b> --ttl <sec> --content "..."');
    console.log('  node store.js read [--tags a,b] [--agents a,b] [--type t] [--max N] [--since ISO]');
    console.log('  node store.js inject [--context "hint text"]');
    console.log('  node store.js prune');
    console.log('  node store.js forget --id <entry_id>');
  console.log('  node store.js audit-verify');
  console.log('  node store.js audit-verify --url <server-url>');
    console.log('  node store.js info');
    console.log('  node store.js wipe');
    process.exit(0);
  }

  const parseArgs = () => {
    const map = {};
    for (let i = 1; i < args.length; i++) {
      if (args[i].startsWith('--')) {
        const key = args[i].slice(2);
        const val = args[i + 1] && !args[i + 1].startsWith('--') ? args[i + 1] : true;
        if (val !== true) i++;
        map[key] = val;
      }
    }
    return map;
  };

  const grid = new Grid();

  try {
    let result;

    switch (command) {
      case 'write': {
        const opts = parseArgs();
        result = await grid.write({
          agent_id: opts.agent || 'cli',
          type: opts.type || 'observation',
          tags: (opts.tags || '').split(',').filter(Boolean),
          ttl_seconds: parseInt(opts.ttl) || undefined,
          content: opts.content || '',
          session_id: opts.session || ''
        });
        break;
      }
      case 'read': {
        const opts = parseArgs();
        result = await grid.read({
          tags: (opts.tags || '').split(',').filter(Boolean),
          agents: (opts.agents || '').split(',').filter(Boolean),
          type: opts.type || null,
          types: (opts.types || '').split(',').filter(Boolean),
          max: parseInt(opts.max) || undefined,
          since: opts.since || null,
          tagMode: opts['tag-mode'] || 'OR'
        });
        break;
      }
      case 'inject': {
        const opts = parseArgs();
        result = await grid.inject(opts.context || '');
        break;
      }
      case 'prune':
        result = await grid.prune();
        break;
      case 'audit-verify': {
        const url = opts.url || 'http://localhost:8080';
        const http = require('http');
        const https = require('https');
        const transport = url.startsWith('https') ? https : http;
        transport.get(url + '/gateway/audit/verify', (res) => {
          let data = '';
          res.on('data', c => data += c);
          res.on('end', () => {
            try {
              const result = JSON.parse(data);
              if (result.valid) {
                console.log('✓ Audit chain integrity verified');
              } else {
                console.log('✗ Audit chain BROKEN at index ' + (result.brokenAtIndex ?? '?') + ': ' + (result.reason ?? 'unknown'));
              }
            } catch {
              console.log('✗ Could not parse audit verification response');
            }
          });
        }).on('error', (e) => {
          console.log('✗ Could not connect to ' + url + ': ' + e.message);
        });
        break;
      }

      case 'forget': {
        const opts = parseArgs();
        result = await grid.forget(opts.id);
        break;
      }
      case 'info':
        result = await grid.info();
        break;
      case 'wipe':
        result = await grid.wipe(true);
        break;
      default:
        console.error(`Unknown command: ${command}`);
        process.exit(1);
    }

    console.log(JSON.stringify(result, null, 2));
  } catch (err) {
    console.error(JSON.stringify({ error: err.message }, null, 2));
    process.exit(1);
  }
}

if (require.main === module) {
  main();
}

module.exports = { Grid, CONFIG };
