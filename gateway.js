/**
 * gateway.js — Enterprise Gateway Middleware
 *
 * Enforces the full security pipeline on every request:
 *   Authentication → Authorization → Workspace Validation
 *   → Rate Limiting → Operation → Audit → Response
 *
 * Uses JSON file storage (zero npm dependencies). In production,
 * swap with PostgreSQL-backed KeyManager + Audit from the Python SDK.
 */

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

// ─── Audit Key (always-on for hash chaining) ─────────────────────────

let _auditKey = null;

function getAuditKeyPath() {
  return path.join(
    process.env.HOME || '/tmp', '.openclaw', 'grid', 'audit_key.secret'
  );
}

function ensureAuditKey() {
  if (_auditKey) return _auditKey;
  
  // Prefer environment variable
  if (process.env.GRID_AUDIT_KEY) {
    _auditKey = process.env.GRID_AUDIT_KEY;
    return _auditKey;
  }
  
  // Try to read persisted key
  const keyPath = getAuditKeyPath();
  try {
    if (fs.existsSync(keyPath)) {
      _auditKey = fs.readFileSync(keyPath, 'utf-8').trim();
      if (_auditKey) return _auditKey;
    }
  } catch (e) { /* fall through */ }
  
  // Generate and persist a new key
  _auditKey = crypto.randomBytes(32).toString('hex');
  try {
    const dir = path.dirname(keyPath);
    if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(keyPath, _auditKey, 'utf-8');
  } catch (e) {
    console.warn('[Gateway] Could not persist audit key:', e.message);
  }
  
  return _auditKey;
}

// Initialize audit key at module load
getAuditKeyPath._initialized = ensureAuditKey();

// ─── Configuration ──────────────────────────────────────────────────────────

const CONFIG = {
  // Master key for gateway management (bypasses regular auth)
  MASTER_KEY: process.env.GRID_GATEWAY_MASTER_KEY || '',
  AUTH_DB: process.env.GRID_AUTH_DB || path.join(
    process.env.HOME || '/tmp', '.openclaw', 'auth', 'keys.json'
  ),
  AUDIT_DB: process.env.GRID_AUDIT_DB || path.join(
    process.env.HOME || '/tmp', '.openclaw', 'audit', 'audit.json'
  ),
  RATE_LIMIT_WINDOW_MS: 60000,
  RATE_LIMIT_MAX: 100,
  ALLOWED_ORIGINS: (process.env.GRID_ALLOWED_ORIGINS || '*').split(','),
  ENFORCE_AUTH: process.env.GRID_ENFORCE_AUTH === 'true',
  MAX_BODY_SIZE: parseInt(process.env.GRID_MAX_BODY_SIZE || '1048576', 10),
};

// ─── In-memory rate limiter ────────────────────────────────────────────────

// Stores key → [timestamp1, timestamp2, ...] within the window
const rateLimitStore = new Map();

function rateLimiter(key) {
  const now = Date.now();
  const windowStart = now - CONFIG.RATE_LIMIT_WINDOW_MS;
  
  let timestamps = rateLimitStore.get(key) || [];
  // Filter out timestamps outside the window
  timestamps = timestamps.filter(ts => ts >= windowStart);
  
  if (timestamps.length >= CONFIG.RATE_LIMIT_MAX) {
    rateLimitStore.set(key, timestamps);
    return false;
  }
  
  timestamps.push(now);
  rateLimitStore.set(key, timestamps);
  return true;
}

// ─── Endpoint-specific rate limits ───────────────────────────────────────────

const ENDPOINT_LIMITS = {
  '/ask': parseInt(process.env.GRID_RATE_LIMIT_ASK || '30', 10),
  '/subscribe': parseInt(process.env.GRID_RATE_LIMIT_SUBSCRIBE || '20', 10),
  '/agents/reputation': parseInt(process.env.GRID_RATE_LIMIT_REPUTATION || '30', 10),
  '/contracts': parseInt(process.env.GRID_RATE_LIMIT_CONTRACTS || '30', 10),
  '/export': parseInt(process.env.GRID_RATE_LIMIT_EXPORT || '10', 10),
  '/federation': parseInt(process.env.GRID_RATE_LIMIT_FEDERATION || '20', 10),
  '/roi': parseInt(process.env.GRID_RATE_LIMIT_ROI || '30', 10),
  '/mike/dashboard': parseInt(process.env.GRID_RATE_LIMIT_DASHBOARD || '20', 10),
  '/executive/dashboard': parseInt(process.env.GRID_RATE_LIMIT_EXEC_DASHBOARD || '10', 10),
  '/decisions': parseInt(process.env.GRID_RATE_LIMIT_DECISIONS || '20', 10),
  '/qbr': parseInt(process.env.GRID_RATE_LIMIT_QBR || '15', 10),
  '/amnesia': parseInt(process.env.GRID_RATE_LIMIT_AMNESIA || '15', 10),
  // Core data routes
  '/write': parseInt(process.env.GRID_RATE_LIMIT_WRITE || '60', 10),
  '/query': parseInt(process.env.GRID_RATE_LIMIT_QUERY || '120', 10),
  '/inject': parseInt(process.env.GRID_RATE_LIMIT_INJECT || '60', 10),
  '/prune': parseInt(process.env.GRID_RATE_LIMIT_PRUNE || '10', 10),
  '/forget': parseInt(process.env.GRID_RATE_LIMIT_FORGET || '20', 10),
  '/health': parseInt(process.env.GRID_RATE_LIMIT_HEALTH || '300', 10),
  '/info': parseInt(process.env.GRID_RATE_LIMIT_INFO || '60', 10),
  '/drafts': parseInt(process.env.GRID_RATE_LIMIT_DRAFTS || '30', 10),
  '/dream': parseInt(process.env.GRID_RATE_LIMIT_DREAM || '10', 10),
  '/provenance': parseInt(process.env.GRID_RATE_LIMIT_PROVENANCE || '60', 10),
  '/quarantine': parseInt(process.env.GRID_RATE_LIMIT_QUARANTINE || '20', 10),
  '/cascade': parseInt(process.env.GRID_RATE_LIMIT_CASCADE || '30', 10),
  '/recall': parseInt(process.env.GRID_RATE_LIMIT_RECALL || '20', 10),
  '/constitution': parseInt(process.env.GRID_RATE_LIMIT_CONSTITUTION || '10', 10),
  '/explain': parseInt(process.env.GRID_RATE_LIMIT_EXPLAIN || '30', 10),
  '/gateway/key': parseInt(process.env.GRID_RATE_LIMIT_GATEWAY_KEY || '10', 10),
  '/auto-contracts': parseInt(process.env.GRID_RATE_LIMIT_AUTO_CONTRACTS || '20', 10),
};

function endpointLimiter(req) {
  try {
    const urlObj = new URL(req.url, 'http://localhost');
    const path = urlObj.pathname;
    for (const [prefix, limit] of Object.entries(ENDPOINT_LIMITS)) {
      if (path.startsWith(prefix)) {
        const ip = req.headers['x-forwarded-for'] || req.connection?.remoteAddress || 'unknown';
        const key = prefix + ':' + ip;
        const now = Date.now();
        const windowStart = now - CONFIG.RATE_LIMIT_WINDOW_MS;
        let timestamps = (rateLimitStore.get(key) || []).filter(ts => ts >= windowStart);
        if (timestamps.length >= limit) {
          rateLimitStore.set(key, timestamps);
          return false;
        }
        timestamps.push(now);
        rateLimitStore.set(key, timestamps);
        return true;
      }
    }
  } catch (e) { /* ignore URL parse errors */ }
  return true;
}

// ─── JSON File Store ────────────────────────────────────────────────────────

function ensureDir(fp) {
  const dir = path.dirname(fp);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
}

function readJSON(fp, def) {
  try {
    if (fs.existsSync(fp)) return JSON.parse(fs.readFileSync(fp, 'utf-8'));
  } catch (e) {
    console.error('[Gateway] Read error:', e.message);
  }
  return def;
}

function writeJSON(fp, data) {
  ensureDir(fp);
  fs.writeFileSync(fp, JSON.stringify(data, null, 2));
}

function getKeys() { return readJSON(CONFIG.AUTH_DB, []); }
function saveKeys(k) { writeJSON(CONFIG.AUTH_DB, k); }
function getAuditLog() { return readJSON(CONFIG.AUDIT_DB, []); }
function saveAuditLog(e) { writeJSON(CONFIG.AUDIT_DB, e); }

// ─── Helpers ────────────────────────────────────────────────────────────────

function hashKey(key) { return crypto.createHash('sha256').update(key).digest('hex'); }
function nowISO() { return new Date().toISOString(); }

function logAudit(action, result, method, urlPath, workspace, actor, keyId, ip, detail) {
  try {
    const entries = getAuditLog();
    const auditKey = ensureAuditKey();
    const prevHash = entries.length > 0 ? entries[entries.length - 1]._hash : '';

    const entry = {
      id: entries.length + 1, timestamp: nowISO(),
      action, result, method, path: urlPath,
      workspace, actor, key_id: keyId, ip, detail: detail || '',
      previous_hash: prevHash || undefined,
    };

    const hmac = crypto.createHmac('sha256', auditKey).update(JSON.stringify(entry)).digest('hex');
    entry._hash = hmac;

    entries.push(entry);
    saveAuditLog(entries);
  } catch (e) { console.error('[Gateway] Audit failed:', e.message); }
}

const PERMISSION_LEVELS = { viewer: 0, analyst: 1, architect: 2, executive: 3, admin: 4 };
function hasPermission(required, granted) {
  if (!(required in PERMISSION_LEVELS) || !(granted in PERMISSION_LEVELS)) return false;
  return PERMISSION_LEVELS[granted] >= PERMISSION_LEVELS[required];
}

function getRequiredPermission(method, p) {
  // GETs
  if (method === 'GET') {
    if (p === '/v1/chat/completions') return 'architect';
    if (p.startsWith('/v1/')) return 'viewer';
    if (p === '/health' || p === '/info') return 'viewer';
    if (p === '/query' || p === '/inject') return 'analyst';
    return 'viewer';
  }
  // DELETE/PUT/PATCH
  if (method === 'DELETE' || method === 'PUT' || method === 'PATCH') return 'admin';
  // POSTs
  if (p === '/write') return 'architect';
  if (p === '/prune') return 'admin';
  if (p.startsWith('/forget/')) return 'admin';
  if (p === '/gateway/key/create') return 'admin';
  if (p.startsWith('/gateway/')) return 'executive';
  return 'analyst';
}

// ─── Authentication ────────────────────────────────────────────────────────

function authenticate(authHeader) {
  if (!authHeader) return { valid: false, reason: 'No authorization header' };
  let token = '';
  if (authHeader.startsWith('Bearer ')) token = authHeader.slice(7).trim();
  else if (authHeader.startsWith('ApiKey ')) token = authHeader.slice(7).trim();
  else return { valid: false, reason: 'Use: Bearer <key>' };

  // Gateway Master Key: bypasses regular auth for admin operations
  if (CONFIG.MASTER_KEY && token === CONFIG.MASTER_KEY) {
    return { valid: true, keyId: 'master-key', workspace: '*', permission: 'admin', label: 'Gateway Master Key' };
  }

  const hashed = hashKey(token);
  const keys = getKeys();

  // Bootstrap: check for one-time bootstrap key file
  const bootstrapPath = path.join(CONFIG.AUTH_DB, '..', '..', 'bootstrap.key');
  if (keys.length === 0 && fs.existsSync(bootstrapPath)) {
    const bootstrapKey = fs.readFileSync(bootstrapPath, 'utf-8').trim();
    if (token === bootstrapKey) {
      console.log('[Gateway] Bootstrap key accepted. Creating first admin key...');
      // Delete bootstrap file immediately — one-time use only
      try { fs.unlinkSync(bootstrapPath); } catch (e) {}
      return { valid: true, keyId: 'bootstrap', workspace: '*', permission: 'admin', label: 'Bootstrap Admin' };
    }
  }

  const row = keys.find(k => k.key_hash === hashed && k.enabled);
  if (!row) return { valid: false, reason: 'Invalid API key' };
  if (row.expires_at && row.expires_at < nowISO()) return { valid: false, reason: 'API key expired' };

  row.last_used = nowISO();
  saveKeys(keys);

  return { valid: true, keyId: row.key_id, workspace: row.workspace, permission: row.permission, label: row.label };
}

// ─── Gateway Class ─────────────────────────────────────────────────────────

// ─── PII Detection (lightweight regex) ───────────────────────────────────

const PII_PATTERNS = [
  { pattern: /\b\d{3}-\d{2}-\d{4}\b/, type: 'SSN', severity: 'critical' },
  { pattern: /\b(?:\d{4}[-\s]?){3}\d{4}\b/, type: 'Credit Card', severity: 'critical' },
  { pattern: /\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b/, type: 'Email', severity: 'high' },
  { pattern: /\b\d{3}[-.]?\d{3}[-.]?\d{4}\b/, type: 'Phone', severity: 'high' },
  { pattern: /\bMRN[-:]?\d{4,10}\b/i, type: 'Medical ID', severity: 'critical' },
];

function scanPII(content) {
  const findings = [];
  if (!content || typeof content !== 'string') return { hasPII: false, findings: [], redacted: content };
  let redacted = content;
  for (const p of PII_PATTERNS) {
    let match;
    while ((match = p.pattern.exec(redacted)) !== null) {
      findings.push({ type: p.type, severity: p.severity, match: match[0], index: match.index });
      redacted = redacted.replace(match[0], `[REDACTED ${p.type}]`);
    }
  }
  return { hasPII: findings.length > 0, findings, redacted };
}

// ─── Encrypted Secrets Storage ───────────────────────────────────────────

function encrypt(text) {
  const key = ensureAuditKey();
  try {
    const iv = crypto.randomBytes(16);
    const cipher = crypto.createCipheriv('aes-256-cbc', crypto.createHash('sha256').update(key).digest(), iv);
    let encrypted = cipher.update(text, 'utf8', 'hex');
    encrypted += cipher.final('hex');
    return iv.toString('hex') + ':' + encrypted;
  } catch { return text; }
}

function decrypt(text) {
  const key = ensureAuditKey();
  if (!text || !text.includes(':')) return text;
  try {
    const parts = text.split(':');
    const iv = Buffer.from(parts[0], 'hex');
    const encrypted = parts.slice(1).join(':');
    const decipher = crypto.createDecipheriv('aes-256-cbc', crypto.createHash('sha256').update(key).digest(), iv);
    let decrypted = decipher.update(encrypted, 'hex', 'utf8');
    decrypted += decipher.final('utf8');
    return decrypted;
  } catch { return text; }
}

// ─── Tamper-Resistant Audit (HMAC chains) ───────────────────────────────

function verifyAuditChain(entries) {
  if (entries.length === 0) return { valid: true };
  const auditKey = ensureAuditKey();
  for (let i = 0; i < entries.length; i++) {
    const entry = { ...entries[i] };
    const storedHash = entry._hash;
    const prevHash = entry.previous_hash;

    // Verify chain: entry i's previous_hash must match entry i-1's _hash
    if (i > 0) {
      const expectedPrev = entries[i - 1]._hash;
      if (prevHash && prevHash !== expectedPrev) {
        return { valid: false, brokenAtIndex: i, reason: `chain break: prev hash mismatch at ${i}` };
      }
    }

    // Verify this entry's own integrity
    if (storedHash) {
      const forHash = { ...entry };
      delete forHash._hash;
      const expected = crypto.createHmac('sha256', auditKey).update(JSON.stringify(forHash)).digest('hex');
      if (storedHash !== expected) {
        return { valid: false, brokenAtIndex: i, reason: `hash mismatch at ${i}` };
      }
    }
  }
  return { valid: true };
}

// ─── Bootstrap Key Generation ───────────────────────────────────────────

function generateBootstrapKey() {
  const crypto = require('crypto');
  const fs = require('fs');
  const path = require('path');
  const key = `grid_bootstrap_${crypto.randomBytes(32).toString('hex')}`;
  const bootstrapPath = path.join(CONFIG.AUTH_DB, '..', '..', 'bootstrap.key');
  const dir = path.dirname(bootstrapPath);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(bootstrapPath, key);
  console.log('');
  console.log('╔══════════════════════════════════════════════════════╗');
  console.log('║        BOOTSTRAP KEY — FIRST-TIME SETUP            ║');
  console.log('╠══════════════════════════════════════════════════════╣');
  console.log('║  Use this key ONCE to create your first admin:     ║');
  console.log('╠══════════════════════════════════════════════════════╣');
  console.log(`║  ${key}  ║`);
  console.log('╠══════════════════════════════════════════════════════╣');
  console.log('║  curl -X POST http://localhost:8080/gateway/key/    ║');
  console.log('║       create \
  ║');
  console.log('║    -H "Authorization: Bearer <key>" \
  ║');
  console.log('║    -H "Content-Type: application/json" \
  ║');
  console.log('║    -d \'{"label":"admin","permission":"admin"}\'   ║');
  console.log('╚══════════════════════════════════════════════════════╝');
  console.log('');
  return bootstrapPath;
}

// Check if we need to generate a bootstrap key
const _keyStoreExists = () => { try { return fs.existsSync(CONFIG.AUTH_DB); } catch { return false; } };

class Gateway {
  constructor(options) {
    this.config = { ...CONFIG, ...options };

    // Generate bootstrap key on first startup with auth enabled but no keys
    if (this.config.ENFORCE_AUTH) {
      try {
        const keys = getKeys();
        if (keys.length === 0) {
          generateBootstrapKey();
        }
      } catch (e) {
        // Store might not exist yet — that's fine
      }
    }
  }

  async enforce(req, requiredPermission, workspace) {
    const method = req.method;
    const urlPath = req.url.split('?')[0];
    const ip = req.headers['x-forwarded-for'] || req.connection?.remoteAddress || 'unknown';
    const authHeader = req.headers['authorization'] || '';
    // Derive workspace from request OR API key (when key is scoped, use that)
    let reqWs = workspace || req.headers['x-grid-workspace'] || '';

    // First authenticate to get key info, then derive workspace
    const auth = this.config.ENFORCE_AUTH ? authenticate(authHeader) : { valid: true, keyId: 'dev', workspace: '*', permission: 'admin' };

    // If key is scoped to a specific workspace and no header provided, use key's workspace
    if (!reqWs && auth.valid && auth.workspace !== '*') {
      reqWs = auth.workspace;
    }

    // Block requests that should have a workspace but don't
    const writeMethods = ['POST', 'PUT', 'PATCH', 'DELETE'];
    if (!reqWs && writeMethods.includes(method) && !urlPath.startsWith('/gateway/') && urlPath !== '/health') {
      if (this.config.ENFORCE_AUTH) {
        logAudit('workspace_missing', 'blocked', method, urlPath, '', auth.keyId || '', auth.keyId || '', ip, 'Workspace required');
        return { allowed: false, status: 400, error: { message: 'X-Grid-Workspace header required for write operations', code: 'WORKSPACE_REQUIRED' } };
      }
    }

    const rateKey = `${ip}:${method}:${urlPath}`;

    if (!rateLimiter(rateKey)) {
      logAudit('rate_limit', 'blocked', method, urlPath, reqWs, '', '', ip, 'Rate limit');
      return { allowed: false, status: 429, error: { message: 'Rate limit exceeded', code: 'RATE_LIMITED' } };
    }

    if (!auth.valid) {
      logAudit('auth', 'blocked', method, urlPath, reqWs, '', '', ip, auth.reason);
      return { allowed: false, status: 401, error: { message: auth.reason, code: 'AUTH_FAILED' } };
    }

    const needed = requiredPermission || getRequiredPermission(method, urlPath);
    if (!hasPermission(needed, auth.permission)) {
      logAudit('permission', 'blocked', method, urlPath, reqWs, auth.keyId, auth.keyId, ip, `Need ${needed}, have ${auth.permission}`);
      return { allowed: false, status: 403, error: { message: `Needs ${needed}`, code: 'FORBIDDEN' } };
    }

    if (reqWs && auth.workspace !== '*' && auth.workspace !== reqWs) {
      logAudit('workspace', 'blocked', method, urlPath, reqWs, auth.keyId, auth.keyId, ip, `Not scoped: ${reqWs}`);
      return { allowed: false, status: 403, error: { message: `Not scoped to ${reqWs}`, code: 'WORKSPACE_FORBIDDEN' } };
    }

    // Enforce workspace requirement for non-GET, non-health requests
    if (this.config.ENFORCE_AUTH && method !== 'GET' && !urlPath.startsWith('/gateway/') && !urlPath.startsWith('/v1/models') && urlPath !== '/health') {
      if (!reqWs && auth.workspace === '*') {
        logAudit('workspace_missing', 'blocked', method, urlPath, '', auth.keyId, auth.keyId, ip, 'Workspace required');
        return { allowed: false, status: 400, error: { message: 'X-Grid-Workspace header required', code: 'WORKSPACE_REQUIRED' } };
      }
    }

    logAudit(method, 'allowed', method, urlPath, reqWs, auth.keyId, auth.keyId, ip, auth.permission);
    return {
      allowed: true,
      auth: { keyId: auth.keyId, permission: auth.permission, workspace: auth.workspace },
    };
  }

  corsHeaders(req) {
    const origin = req.headers['origin'] || '*';
    return {
      'Access-Control-Allow-Origin': this.config.ALLOWED_ORIGINS.includes('*') ? '*' : (this.config.ALLOWED_ORIGINS.includes(origin) ? origin : (this.config.ALLOWED_ORIGINS[0] || '*')),
      'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Grid-Workspace',
      'Access-Control-Max-Age': '86400',
    };
  }

  createKey(label, workspace, permission, expiresInDays) {
    const keyId = `key_${crypto.randomBytes(8).toString('hex')}`;
    const plaintext = `grid_${crypto.randomBytes(32).toString('hex')}`;
    const hashed = hashKey(plaintext);
    const keys = getKeys();
    keys.push({
      key_id: keyId, key_hash: hashed, label: label || 'Key',
      workspace: workspace || '*', permission: permission || 'viewer',
      created_at: nowISO(),
      expires_at: expiresInDays ? new Date(Date.now() + expiresInDays * 86400000).toISOString() : null,
      last_used: null, enabled: 1,
    });
    saveKeys(keys);
    return { keyId, plaintextKey: plaintext, label, workspace, permission };
  }

  async listKeys() {
    return getKeys().map(k => ({
      key_id: k.key_id, label: k.label, workspace: k.workspace,
      permission: k.permission, created_at: k.created_at,
      expires_at: k.expires_at, last_used: k.last_used, enabled: k.enabled,
    }));
  }

  revokeKey(keyId) {
    const keys = getKeys();
    const k = keys.find(x => x.key_id === keyId);
    if (k) k.enabled = 0;
    saveKeys(keys);
    return { revoked: true, keyId };
  }

  /**
   * Rotate an API key (generate new key, keep same permissions, revoke old).
   */
  rotateKey(keyId) {
    const keys = getKeys();
    const existing = keys.find(k => k.key_id === keyId);
    if (!existing) return { rotated: false, reason: 'Key not found' };

    // Create new key with same permissions
    const newKey = this.createKey(
      existing.label + ' (rotated)',
      existing.workspace,
      existing.permission,
      null
    );

    // Revoke old key
    existing.enabled = 0;
    saveKeys(keys);

    logAudit('key_rotated', 'allowed', 'POST', '/gateway/key/rotate', existing.workspace, 'system', keyId, 'local', `Rotated to ${newKey.keyId}`);

    return { rotated: true, oldKeyId: keyId, newKey: newKey };
  }

  async getAuditLog(filter = {}) {
    let entries = getAuditLog();

    // Verify HMAC chain integrity
    const integrity = verifyAuditChain(entries);
    if (!integrity.valid) {
      console.error('[Gateway] Audit chain integrity BROKEN at index', integrity.brokenAtIndex);
    }

    if (filter.action) entries = entries.filter(e => e.action === filter.action);
    if (filter.workspace) entries = entries.filter(e => e.workspace === filter.workspace);
    entries.sort((a, b) => b.id - a.id);
    return entries.slice(0, parseInt(filter.limit || '100'));
  }

  async verifyAuditIntegrity() {
    const entries = getAuditLog();
    return verifyAuditChain(entries);
  }

  async validateKey(plaintextKey, requiredPermission, workspace) {
    const hashed = hashKey(plaintextKey);
    const keys = getKeys();
    const row = keys.find(k => k.key_hash === hashed && k.enabled);
    if (!row) return { valid: false, reason: 'Invalid key' };
    if (!hasPermission(requiredPermission, row.permission)) return { valid: false, reason: `Need ${requiredPermission}` };
    if (workspace && row.workspace !== '*' && row.workspace !== workspace) return { valid: false, reason: `Not scoped: ${workspace}` };
    return { valid: true, keyId: row.key_id, permission: row.permission, workspace: row.workspace };
  }
}

module.exports = { Gateway, CONFIG, scanPII, encrypt, decrypt, logAudit, getKeys, getAuditLog, endpointLimiter };
