#!/usr/bin/env node
/**
 * sqlite-store.js — SQLite storage backend for Grid Memory.
 *
 * Drop-in replacement for store.js (JSON file store) using better-sqlite3.
 * Supports WAL mode for concurrent readers and uses a file-level lock
 * from sqlite3's internal locking for multi-process safety.
 *
 * Usage:
 *   const { Grid } = require('./reference/sqlite-store.js');
 *   const grid = new Grid({ dbPath: '/data/grid.db' });
 *
 * Environment:
 *   GRID_DB_PATH   — Path to SQLite database file (default: ./data/grid.db)
 *   GRID_SQLITE_WAL — Set to '1' to enable WAL mode (default: enabled)
 */

const path = require('path');
const fs = require('fs');
const crypto = require('crypto');
let Database;

try {
  Database = require('better-sqlite3');
} catch (e) {
  console.error('[SQLite] better-sqlite3 not available. Install: npm install better-sqlite3');
  process.exit(1);
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function now() { return new Date().toISOString(); }

function generateId() {
  return 'grid_' + now().slice(0, 10).replace(/-/g, '') + '_' + crypto.randomBytes(6).toString('hex');
}

const VALID_TYPES = new Set([
  'decision', 'fact', 'task_status', 'artifact_ref', 'handoff',
  'question', 'observation', 'blocker', 'state_update'
]);

const DEFAULT_TTLS = {
  decision: 86400 * 30,       // 30 days
  fact: 86400 * 90,           // 90 days
  task_status: 86400 * 7,     // 7 days
  artifact_ref: 86400 * 30,   // 30 days
  handoff: 3600,              // 1 hour
  question: 86400 * 7,        // 7 days
  observation: 86400,         // 1 day
  blocker: 86400,             // 1 day
  state_update: 86400 * 3,    // 3 days
};

// ─── Schema ───────────────────────────────────────────────────────────────────

const SCHEMA_SQL = `
  CREATE TABLE IF NOT EXISTS entries (
    id            TEXT PRIMARY KEY,
    session_id    TEXT DEFAULT '',
    agent_id      TEXT NOT NULL,
    type          TEXT NOT NULL DEFAULT 'observation',
    tags          TEXT DEFAULT '[]',
    content       TEXT NOT NULL,
    ttl_seconds   INTEGER DEFAULT 86400,
    created_at    TEXT NOT NULL,
    expires_at    TEXT NOT NULL,
    parent_entry  TEXT,
    last_read_at  TEXT,
    memory_tier   TEXT DEFAULT 'working',
    read_count    INTEGER DEFAULT 0,
    workspace_id  TEXT DEFAULT '',
    status        TEXT DEFAULT 'active',
    outcome       TEXT,
    requires_approval TEXT,
    origin_trust  TEXT DEFAULT 'native',
    provenance_trust_score REAL,
    staleness_score REAL,
    embedding     TEXT,
    quarantined   INTEGER DEFAULT 0,
    quarantine_reason TEXT,
    quarantined_at TEXT,
    recalled      INTEGER DEFAULT 0,
    recall_reason TEXT,
    recalled_at   TEXT,
    contaminated  INTEGER DEFAULT 0,
    contamination_source TEXT,
    contamination_detected_at TEXT,
    propagation   TEXT DEFAULT '[]',
    draft_id      TEXT
  );

  CREATE INDEX IF NOT EXISTS idx_entries_agent ON entries(agent_id);
  CREATE INDEX IF NOT EXISTS idx_entries_type ON entries(type);
  CREATE INDEX IF NOT EXISTS idx_entries_expires ON entries(expires_at);
  CREATE INDEX IF NOT EXISTS idx_entries_created ON entries(created_at);
  CREATE INDEX IF NOT EXISTS idx_entries_workspace ON entries(workspace_id);
  CREATE INDEX IF NOT EXISTS idx_entries_status ON entries(status);
  CREATE INDEX IF NOT EXISTS idx_entries_parent ON entries(parent_entry);
  CREATE INDEX IF NOT EXISTS idx_entries_memory_tier ON entries(memory_tier);
`;

// ─── Grid Class (SQLite Backend) ──────────────────────────────────────────────

class Grid {
  constructor(opts = {}) {
    this.dbPath = opts.dbPath || process.env.GRID_DB_PATH || './data/grid.db';
    this.walMode = opts.walMode !== false && process.env.GRID_SQLITE_WAL !== '0';

    // Ensure directory exists
    const dir = path.dirname(this.dbPath);
    if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });

    // Open database
    this.db = new Database(this.dbPath);
    
    // Enable WAL mode for concurrent read access
    if (this.walMode) {
      this.db.pragma('journal_mode = WAL');
    }
    this.db.pragma('busy_timeout = 5000');
    this.db.pragma('foreign_keys = ON');

    // Create schema
    this.db.exec(SCHEMA_SQL);

    // Prepared statements
    this._stmtInsert = this.db.prepare(`
      INSERT INTO entries (
        id, session_id, agent_id, type, tags, content,
        ttl_seconds, created_at, expires_at, parent_entry,
        last_read_at, memory_tier, read_count, workspace_id,
        status, outcome, requires_approval, origin_trust,
        provenance_trust_score, staleness_score, embedding,
        quarantined, quarantine_reason, quarantined_at,
        recalled, recall_reason, recalled_at,
        contaminated, contamination_source, contamination_detected_at,
        propagation, draft_id
      ) VALUES (
        @id, @session_id, @agent_id, @type, @tags, @content,
        @ttl_seconds, @created_at, @expires_at, @parent_entry,
        null, @memory_tier, 0, @workspace_id,
        @status, @outcome, @requires_approval, @origin_trust,
        @provenance_trust_score, @staleness_score, @embedding,
        @quarantined, @quarantine_reason, @quarantined_at,
        @recalled, @recall_reason, @recalled_at,
        @contaminated, @contamination_source, @contamination_detected_at,
        @propagation, @draft_id
      )
    `);

    this._stmtUpdateOutcome = this.db.prepare(`
      UPDATE entries SET outcome = @outcome WHERE id = @id
    `);

    this._stmtPromote = this.db.prepare(`
      UPDATE entries SET memory_tier = @tier WHERE id = @id
    `);

    this._stmtForget = this.db.prepare(`
      DELETE FROM entries WHERE id = @id
    `);

    this._stmtGetById = this.db.prepare(`
      SELECT * FROM entries WHERE id = @id
    `);

    this._stmtCount = this.db.prepare(`SELECT COUNT(*) as count FROM entries`);

    this._stmtPrune = this.db.prepare(`
      DELETE FROM entries WHERE expires_at < @now
    `);

    this._stmtIncrementRead = this.db.prepare(`
      UPDATE entries SET last_read_at = @now, read_count = read_count + 1 WHERE id = @id
    `);
  }

  // ── Write ──

  async write(write = {}) {
    if (!write.agent_id) throw new Error('agent_id is required');
    if (!write.content) throw new Error('content is required');
    if (write.content.trim) write.content = write.content.trim();

    const type = write.type || 'observation';
    if (!VALID_TYPES.has(type)) {
      throw new Error(`Invalid type "${type}". Valid types: ${[...VALID_TYPES].join(', ')}`);
    }

    const ttl = write.ttl_seconds || DEFAULT_TTLS[type] || 86400;
    const id = write.force_id || generateId();

    const entry = {
      id,
      session_id: write.session_id || '',
      agent_id: write.agent_id,
      type,
      tags: JSON.stringify(write.tags || []),
      content: write.content,
      ttl_seconds: ttl,
      created_at: write.force_created_at || now(),
      expires_at: write.force_expires_at || new Date(Date.now() + ttl * 1000).toISOString(),
      parent_entry: write.parent_entry || null,
      memory_tier: write.memory_tier || 'working',
      workspace_id: write.workspace_id || '',
      status: write.status || 'active',
      outcome: write.outcome || null,
      requires_approval: write.requires_approval || null,
      origin_trust: write.origin_trust || 'native',
      provenance_trust_score: write.provenance_trust_score || null,
      staleness_score: write.staleness_score || null,
      embedding: write.embedding || null,
      quarantined: write.quarantined ? 1 : 0,
      quarantine_reason: write.quarantine_reason || null,
      quarantined_at: write.quarantined_at || null,
      recalled: write.recalled ? 1 : 0,
      recall_reason: write.recall_reason || null,
      recalled_at: write.recalled_at || null,
      contaminated: write.contaminated ? 1 : 0,
      contamination_source: write.contamination_source || null,
      contamination_detected_at: write.contamination_detected_at || null,
      propagation: JSON.stringify(write.propagation || []),
      draft_id: write.draft_id || null,
    };

    this._stmtInsert.run(entry);

    return this._entryToResult(entry);
  }

  // ── Update Outcome ──

  async updateOutcome(entryId, outcome) {
    if (!outcome || !outcome.result) throw new Error('outcome.result is required');
    if (!['success', 'failure', 'partial'].includes(outcome.result)) {
      throw new Error('outcome.result must be success/failure/partial');
    }
    const result = this._stmtUpdateOutcome.run({ id: entryId, outcome: JSON.stringify(outcome) });
    return { updated: result.changes > 0 };
  }

  // ── Promote Entry ──

  async promoteEntry(entryId) {
    const row = this._stmtGetById.get({ id: entryId });
    if (!row) return { promoted: false, reason: 'Entry not found' };

    const currentTier = row.memory_tier || 'working';
    const TIERS = ['working', 'project', 'organization'];
    const idx = TIERS.indexOf(currentTier);
    if (idx === -1 || idx >= TIERS.length - 1) return { promoted: false, reason: 'Already at highest tier' };
    const newTier = TIERS[idx + 1];
    this._stmtPromote.run({ id: entryId, tier: newTier });
    return { promoted: true, new_tier: newTier };
  }

  // ── Read / Query ──

  async read(query = {}) {
    const maxResults = Math.min(query.max || 50, 500);
    const tags = query.tags || [];
    const agents = query.agents || [];
    const types = query.types || [];
    const type = query.type || null;
    const since = query.since || null;
    const before = query.before || null;
    const tagMode = query.tagMode || 'OR';
    const parent_entry = query.parent_entry || null;
    const include_drafts = query.include_drafts || false;
    const workspace_id = query.workspace_id || null;

    let sql = 'SELECT * FROM entries WHERE expires_at > @now';
    const params = { now: now() };

    if (!include_drafts) {
      sql += ' AND status != \'draft\'';
    }

    if (parent_entry) {
      sql += ' AND (parent_entry = @parent OR id = @parent)';
      params.parent = parent_entry;
    }

    if (type) {
      sql += ' AND type = @type';
      params.type = type;
    } else if (types.length > 0) {
      sql += ' AND type IN (' + types.map((_, i) => '@t' + i).join(',') + ')';
      types.forEach((t, i) => params['t' + i] = t);
    }

    if (agents.length > 0) {
      sql += ' AND agent_id IN (' + agents.map((_, i) => '@a' + i).join(',') + ')';
      agents.forEach((a, i) => params['a' + i] = a);
    }

    if (since) {
      sql += ' AND created_at >= @since';
      params.since = since;
    }

    if (before) {
      sql += ' AND created_at <= @before';
      params.before = before;
    }

    if (workspace_id) {
      sql += ' AND workspace_id = @ws';
      params.ws = workspace_id;
    }

    // Tag filtering via JSON_EACH
    if (tags.length > 0) {
      const tagConditions = tags.map((_, i) => {
        const param = '@tag' + i;
        params[param.slice(1)] = tags[i];
        if (tagMode === 'AND') {
          return `EXISTS (SELECT 1 FROM json_each(entries.tags) WHERE value = ${param})`;
        }
        return `EXISTS (SELECT 1 FROM json_each(entries.tags) WHERE value = ${param})`;
      });
      const joiner = tagMode === 'AND' ? ' AND ' : ' OR ';
      sql += ' AND (' + tagConditions.join(joiner) + ')';
    }

    sql += ' ORDER BY created_at DESC';

    // Count total
    const countSql = sql.replace('SELECT *', 'SELECT COUNT(*) as total');
    const totalBeforeFilter = this.db.prepare(countSql).get(params).total;

    // Fetch with limit
    sql += ' LIMIT @limit';
    params.limit = maxResults;

    const rows = this.db.prepare(sql).all(params);

    // Update read counts
    const updateStmt = this.db.prepare('UPDATE entries SET last_read_at = @now, read_count = read_count + 1 WHERE id = @id');
    const touch = this.db.transaction((ids) => {
      const n = now();
      for (const id of ids) {
        updateStmt.run({ id, now: n });
      }
    });
    touch(rows.map(r => r.id));

    const results = rows.map(r => this._entryToResult(r));

    return {
      entries: results,
      count: results.length,
      total_before_filter: totalBeforeFilter,
      query_meta: { returned: results.length, total_before_filter: totalBeforeFilter }
    };
  }

  // ── Inject (Context Injection) ──

  async inject(contextHint = '') {
    const hintTags = this._extractTags(contextHint);
    let result;
    if (hintTags.length > 0) {
      result = await this.read({ tags: hintTags, max: 10, tagMode: 'OR' });
    }
    if (!result || result.entries.length === 0) {
      // Fall back to most recent entries
      const rows = this.db.prepare(
        'SELECT * FROM entries WHERE expires_at > @now ORDER BY created_at DESC LIMIT 5'
      ).all({ now: now() });
      result = { entries: rows.map(r => this._entryToResult(r)) };
    }

    const MAX_INJECT_SIZE = 4096;
    let block = '─── SHARED MEMORY GRID ───\n\n';
    block += `Recent entries (filtered: ${result.entries.length} total):\n\n`;

    for (const entry of result.entries) {
      const time = (entry.created_at || '').slice(11, 16);
      const tags = (entry.tags || []).join(', ');
      const snippet = (entry.content || '').length > 200
        ? entry.content.slice(0, 200) + '…'
        : entry.content;
      block += `[${entry.type}] ${time} — agent:${entry.agent_id}`;
      if (tags) block += ` — ${tags}`;
      block += `\n${snippet}\n\n`;
      if (Buffer.byteLength(block, 'utf-8') > MAX_INJECT_SIZE) break;
    }

    block += '─── END GRID ───';

    const blockBytes = Buffer.byteLength(block, 'utf-8');
    if (blockBytes > MAX_INJECT_SIZE) {
      block = block.slice(0, MAX_INJECT_SIZE - 50) + '\n… [truncated]\n─── END GRID ───';
    }

    return { block, entry_count: result.entries.length, bytes: Buffer.byteLength(block, 'utf-8') };
  }

  _extractTags(text) {
    if (!text) return [];
    const existingTags = this.db.prepare(
      `SELECT DISTINCT json_each.value AS tag FROM entries, json_each(entries.tags)`
    ).all().map(r => r.tag);
    if (existingTags.length === 0) return [];

    const words = text.toLowerCase().split(/\s+/);
    return existingTags.filter(tag =>
      words.some(w => tag.toLowerCase().includes(w) || w.includes(tag.toLowerCase()))
    ).slice(0, 5);
  }

  // ── Prune (Remove expired entries) ──

  async prune() {
    const result = this._stmtPrune.run({ now: now() });
    const info = this.db.prepare('SELECT COUNT(*) as count FROM entries').get();
    return { removed: result.changes, remaining: info.count };
  }

  // ── Forget (Delete single entry) ──

  async forget(entryId) {
    const result = this._stmtForget.run({ id: entryId });
    return { deleted: result.changes > 0 };
  }

  // ── Info ──

  async info() {
    const total = this._stmtCount.get().count;
    const agents = this.db.prepare('SELECT DISTINCT agent_id FROM entries').all().length;
    const workspaces = this.db.prepare('SELECT DISTINCT workspace_id FROM entries WHERE workspace_id != \'\'').all().length;
    const oldest = this.db.prepare('SELECT created_at FROM entries ORDER BY created_at ASC LIMIT 1').get();
    const newest = this.db.prepare('SELECT created_at FROM entries ORDER BY created_at DESC LIMIT 1').get();
    const types = this.db.prepare('SELECT type, COUNT(*) as count FROM entries GROUP BY type').all();

    const dbSize = fs.existsSync(this.dbPath) ? fs.statSync(this.dbPath).size : 0;

    return {
      total_entries: total,
      unique_agents: agents,
      unique_workspaces: workspaces,
      oldest_entry: oldest ? oldest.created_at : null,
      newest_entry: newest ? newest.created_at : null,
      types: types.reduce((acc, t) => { acc[t.type] = t.count; return acc; }, {}),
      store_size_kb: Math.round(dbSize / 1024),
      database: 'sqlite',
      db_path: this.dbPath,
    };
  }

  // ── Export All ──

  async exportAll() {
    const rows = this.db.prepare('SELECT * FROM entries ORDER BY created_at ASC').all();
    return {
      version: 1,
      exported_at: now(),
      entry_count: rows.length,
      entries: rows.map(r => this._entryToResult(r)),
    };
  }

  // ── Wipe ──

  async wipe(confirm = false) {
    if (!confirm) return { wiped: false, reason: 'Must pass confirm=true' };
    this.db.exec('DELETE FROM entries');
    this.db.exec('VACUUM');
    return { wiped: true };
  }

  // ── Close ──

  close() {
    this.db.close();
  }

  // ── Internal Helpers ──

  _entryToResult(row) {
    if (!row) return null;
    // Parse JSON string columns
    let tags = [];
    let propagation = [];
    let outcome = null;
    try { tags = JSON.parse(row.tags || '[]'); } catch (e) {}
    try { propagation = JSON.parse(row.propagation || '[]'); } catch (e) {}
    try { outcome = JSON.parse(row.outcome || 'null'); } catch (e) {}

    return {
      entry_id: row.id,
      id: row.id,
      session_id: row.session_id || '',
      agent_id: row.agent_id,
      type: row.type,
      tags,
      content: row.content,
      ttl_seconds: row.ttl_seconds,
      created_at: row.created_at,
      expires_at: row.expires_at,
      parent_entry: row.parent_entry || null,
      last_read_at: row.last_read_at || null,
      memory_tier: row.memory_tier || 'working',
      read_count: row.read_count || 0,
      workspace_id: row.workspace_id || '',
      status: row.status,
      outcome,
      requires_approval: row.requires_approval || null,
      origin_trust: row.origin_trust || 'native',
      provenance_trust_score: row.provenance_trust_score || null,
      staleness_score: row.staleness_score || null,
      embedding: row.embedding || null,
      quarantined: !!row.quarantined,
      quarantine_reason: row.quarantine_reason || null,
      quarantined_at: row.quarantined_at || null,
      recalled: !!row.recalled,
      recall_reason: row.recall_reason || null,
      recalled_at: row.recalled_at || null,
      contaminated: !!row.contaminated,
      contamination_source: row.contamination_source || null,
      contamination_detected_at: row.contamination_detected_at || null,
      propagation,
      draft_id: row.draft_id || null,
    };
  }
}

// ─── CLI ──────────────────────────────────────────────────────────────────────

async function main() {
  const args = process.argv.slice(2);
  const cmd = args[0];
  const grid = new Grid();

  switch (cmd) {
    case 'write':
      const content = args[1] || 'test';
      const result = await grid.write({ agent_id: 'cli', type: 'observation', content, tags: ['cli'] });
      console.log(JSON.stringify(result, null, 2));
      break;
    case 'info':
      console.log(JSON.stringify(await grid.info(), null, 2));
      break;
    case 'prune':
      console.log(JSON.stringify(await grid.prune(), null, 2));
      break;
    default:
      console.log(`
SQLite Grid Store - drop-in replacement for store.js

Usage:
  GRID_DB_PATH=./data/grid.db node reference/sqlite-store.js write "content"
  GRID_DB_PATH=./data/grid.db node reference/sqlite-store.js info
  GRID_DB_PATH=./data/grid.db node reference/sqlite-store.js prune
      `);
  }

  grid.close();
}

if (require.main === module) main();

module.exports = { Grid };
