/**
 * governance-db.js — SQLite Governance Store (Lazy Init)
 *
 * Replaces JSON file persistence for contracts, constitutions, and federation peers.
 * Uses better-sqlite3 with lazy initialization — no module-load side effects.
 *
 * Graceful fallback to JSON files when better-sqlite3 is not available.
 */

const fs = require('fs');
const path = require('path');

let db = null;
let _available = null; // null = unchecked, true/false = checked

function getDbDir() {
  return process.env.GRID_STORE_DIR || path.join(
    process.env.HOME || '/tmp', '.openclaw', 'grid'
  );
}

function getDbPath() {
  return path.join(getDbDir(), 'governance.db');
}

function getDb() {
  if (_available === false) return null; // already tried, failed
  if (db) return db; // already initialized

  try {
    const BetterSqlite3 = require('better-sqlite3');
    const dbPath = getDbPath();
    const dbDir = getDbDir();
    if (!fs.existsSync(dbDir)) fs.mkdirSync(dbDir, { recursive: true });
    db = new BetterSqlite3(dbPath);
    db.pragma('journal_mode = WAL');
    
    db.exec(`
      CREATE TABLE IF NOT EXISTS contracts (
        scope TEXT PRIMARY KEY,
        schema_json TEXT NOT NULL,
        enforce TEXT DEFAULT 'validate',
        created_at TEXT,
        created_by TEXT DEFAULT 'unknown',
        version INTEGER DEFAULT 1,
        history_json TEXT DEFAULT '[]'
      );
      CREATE TABLE IF NOT EXISTS constitutions (
        workspace TEXT PRIMARY KEY,
        rules_json TEXT NOT NULL,
        enforce_mode TEXT DEFAULT 'validate',
        created_at TEXT,
        updated_at TEXT
      );
      CREATE TABLE IF NOT EXISTS federation_peers (
        url TEXT PRIMARY KEY,
        trust_level TEXT DEFAULT 'unverified',
        trust_score INTEGER DEFAULT 40,
        shared_secret TEXT,
        registered_at TEXT,
        updated_at TEXT,
        last_synced_at TEXT
      );
    `);
    _available = true;
    return db;
  } catch (e) {
    _available = false;
    return null;
  }
}

module.exports = {
  isAvailable: () => { getDb(); return _available === true; },
  close: () => { if (db) { db.close(); db = null; _available = null; } },

  // ── Contracts ──

  getContracts: () => {
    const d = getDb();
    if (!d) return null;
    const rows = d.prepare('SELECT * FROM contracts').all();
    return rows.map(r => ({ ...r, schema: JSON.parse(r.schema_json), history: JSON.parse(r.history_json) }));
  },

  saveContract: (scope, data) => {
    const d = getDb();
    if (!d) return false;
    d.prepare(`INSERT OR REPLACE INTO contracts (scope, schema_json, enforce, created_at, created_by, version, history_json)
      VALUES (?, ?, ?, ?, ?, ?, ?)`).run(scope, JSON.stringify(data.schema), data.enforce, data.created_at, data.created_by, data.version, JSON.stringify(data.history));
    return true;
  },

  deleteContract: (scope) => {
    const d = getDb();
    if (!d) return false;
    d.prepare('DELETE FROM contracts WHERE scope = ?').run(scope);
    return true;
  },

  // ── Constitutions ──

  getConstitutions: () => {
    const d = getDb();
    if (!d) return null;
    return d.prepare('SELECT * FROM constitutions').all();
  },

  saveConstitution: (workspace, data) => {
    const d = getDb();
    if (!d) return false;
    d.prepare(`INSERT OR REPLACE INTO constitutions (workspace, rules_json, enforce_mode, created_at, updated_at)
      VALUES (?, ?, ?, ?, ?)`).run(workspace, JSON.stringify(data.rules), data.enforceMode, data.created_at, data.updated_at);
    return true;
  },

  deleteConstitution: (workspace) => {
    const d = getDb();
    if (!d) return false;
    d.prepare('DELETE FROM constitutions WHERE workspace = ?').run(workspace);
    return true;
  },

  // ── Federation Peers ──

  getPeers: () => {
    const d = getDb();
    if (!d) return null;
    return d.prepare('SELECT * FROM federation_peers').all();
  },

  savePeer: (url, data) => {
    const d = getDb();
    if (!d) return false;
    d.prepare(`INSERT OR REPLACE INTO federation_peers (url, trust_level, trust_score, shared_secret, registered_at, updated_at, last_synced_at)
      VALUES (?, ?, ?, ?, ?, ?, ?)`).run(url, data.trustLevel, data.trustScore, data.sharedSecret || null, data.registered_at, data.updated_at, data.last_synced_at);
    return true;
  },

  deletePeer: (url) => {
    const d = getDb();
    if (!d) return false;
    d.prepare('DELETE FROM federation_peers WHERE url = ?').run(url);
    return true;
  },
};
