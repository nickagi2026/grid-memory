/**
 * contracts.js — Memory Contracts: Typed Schemas with Lifecycle
 *
 * Defines typed JSON schemas per tag namespace. Supports versioning,
 * ownership, rollback, and full change history.
 */

const fs = require('fs');
const path = require('path');
const govDb = require('./governance-db.js');

const contracts = new Map();
const CONTRACTS_FILE = process.env.GRID_CONTRACTS_FILE || path.join(
  process.env.GRID_STORE_DIR || path.join(process.env.HOME || '/tmp', '.openclaw', 'grid'),
  'contracts.json'
);

// ─── Persistence ───────────────────────────────────────────────────────────

function loadContracts() {
  try {
    // Try SQLite first
    const dbRows = govDb.getContracts();
    if (dbRows && dbRows.length > 0) {
      for (const item of dbRows) {
        contracts.set(item.scope, {
          schema: item.schema,
          enforce: item.enforce,
          created_at: item.created_at,
          created_by: item.created_by || 'unknown',
          version: item.version || 1,
          history: item.history || [],
        });
      }
      return; // SQLite loaded successfully
    }
  } catch (e) { /* fall through to JSON */ }

  try {
    if (fs.existsSync(CONTRACTS_FILE)) {
      const data = JSON.parse(fs.readFileSync(CONTRACTS_FILE, 'utf-8'));
      for (const item of data) {
        contracts.set(item.scope, {
          schema: item.schema,
          enforce: item.enforce,
          created_at: item.created_at,
          created_by: item.created_by || 'unknown',
          version: item.version || 1,
          history: item.history || [],
        });
      }
    }
  } catch (e) { console.error('[Contracts] Load failed:', e.message); }
}

function saveContracts() {
  // PRIMARY: governance-db (SQLite). LEGACY FALLBACK: JSON file.

  // Try SQLite first
  if (govDb.isAvailable()) {
    try {
      for (const [scope, c] of contracts) {
        govDb.saveContract(scope, c);
      }
      return;
    } catch (e) { /* fall through to JSON */ }
  }

  try {
    const dir = path.dirname(CONTRACTS_FILE);
    if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
    const data = [];
    for (const [scope, c] of contracts) {
      data.push({
        scope, schema: c.schema, enforce: c.enforce,
        created_at: c.created_at, created_by: c.created_by,
        version: c.version, history: c.history,
      });
    }
    fs.writeFileSync(CONTRACTS_FILE, JSON.stringify(data, null, 2));
  } catch (e) { console.error('[Contracts] Save failed:', e.message); }
}

loadContracts();

// ─── Schema Validation ─────────────────────────────────────────────────────

const VALID_TYPES = ['string', 'number', 'boolean', 'object', 'array', 'semver', 'enum'];

function validateValue(value, expectedType) {
  if (!expectedType) return { valid: true };
  if (expectedType.startsWith('enum:')) {
    const allowed = expectedType.split(':')[1].split('|');
    return { valid: allowed.includes(String(value)), error: `Expected one of: ${allowed.join(', ')}` };
  }
  if (expectedType === 'semver') {
    return { valid: /^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?(\+[a-zA-Z0-9.]+)?$/.test(String(value)), error: 'Invalid semver' };
  }
  switch (expectedType) {
    case 'string': return { valid: typeof value === 'string', error: 'Expected string' };
    case 'number': return { valid: typeof value === 'number' && !isNaN(value), error: 'Expected number' };
    case 'boolean': return { valid: typeof value === 'boolean', error: 'Expected boolean' };
    case 'object': return { valid: typeof value === 'object' && value !== null && !Array.isArray(value), error: 'Expected object' };
    case 'array': return { valid: Array.isArray(value), error: 'Expected array' };
    default: return { valid: true };
  }
}

function validateContent(content, schema) {
  let parsed;
  try { parsed = JSON.parse(content); } catch { return { valid: false, errors: [{ field: '_root', error: 'Not valid JSON' }] }; }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return { valid: false, errors: [{ field: '_root', error: 'Expected JSON object' }] };
  const errors = [];
  for (const [field, expectedType] of Object.entries(schema)) {
    if (field === 'required') continue;
    const value = parsed[field];
    const isRequired = Array.isArray(schema.required) && schema.required.includes(field);
    if (value === undefined || value === null) {
      if (isRequired) errors.push({ field, error: `Required field '${field}' is missing` });
      continue;
    }
    const result = validateValue(value, expectedType);
    if (!result.valid) errors.push({ field, error: `Field '${field}': ${result.error}` });
  }
  return { valid: errors.length === 0, errors };
}

function matchesScope(entryTags, contractScope) {
  if (contractScope === '*') return true;
  if (contractScope.endsWith(':*')) {
    const prefix = contractScope.slice(0, -2);
    return entryTags.some(t => t.startsWith(prefix + ':') || t === prefix);
  }
  return entryTags.includes(contractScope);
}

// ─── Register with Ownership ───────────────────────────────────────────────

function registerContract(scope, schema, enforce = 'validate', createdBy) {
  if (!scope) return { registered: false, error: 'Scope is required' };
  if (!schema || typeof schema !== 'object') return { registered: false, error: 'Schema is required' };
  if (!['validate', 'reject', 'warn'].includes(enforce)) return { registered: false, error: 'Enforce must be validate, reject, or warn' };

  const existing = contracts.get(scope);
  const now = new Date().toISOString();
  const version = existing ? existing.version + 1 : 1;

  // Build history entry
  const historyEntry = {
    version,
    schema,
    enforce,
    changed_by: createdBy || 'unknown',
    changed_at: now,
    change_type: existing ? 'update' : 'create',
  };

  // Store previous schema in history for rollback
  const history = existing ? [...(existing.history || []), historyEntry] : [historyEntry];

  contracts.set(scope, {
    schema,
    enforce,
    created_at: existing ? existing.created_at : now,
    created_by: existing ? existing.created_by : (createdBy || 'unknown'),
    version,
    history,
  });

  saveContracts();
  return { registered: true, scope, enforce, version, change_type: historyEntry.change_type };
}

// ─── Rollback Contract ─────────────────────────────────────────────────────

function rollbackContract(scope, targetVersion) {
  const contract = contracts.get(scope);
  if (!contract) return { rolled_back: false, error: `Contract '${scope}' not found` };
  const history = contract.history || [];
  if (targetVersion < 1 || targetVersion >= contract.version) return { rolled_back: false, error: `Version ${targetVersion} is not in history (current: ${contract.version})` };

  const targetEntry = history.find(h => h.version === targetVersion);
  if (!targetEntry) return { rolled_back: false, error: `Version ${targetVersion} not found in history` };

  const now = new Date().toISOString();
  contracts.set(scope, {
    schema: targetEntry.schema,
    enforce: targetEntry.enforce,
    created_at: contract.created_at,
    created_by: contract.created_by,
    version: contract.version + 1,
    history: [...history, {
      version: contract.version + 1,
      schema: targetEntry.schema,
      enforce: targetEntry.enforce,
      changed_by: 'rollback',
      changed_at: now,
      change_type: `rollback_to_v${targetVersion}`,
    }],
  });

  saveContracts();
  return { rolled_back: true, scope, version: contract.version + 1, restored_to: targetVersion };
}

// ─── Get Contract History ──────────────────────────────────────────────────

function getContractHistory(scope) {
  const contract = contracts.get(scope);
  if (!contract) return { found: false, error: `Contract '${scope}' not found` };
  return { found: true, scope, version: contract.version, history: contract.history || [] };
}

// ─── Validate ──────────────────────────────────────────────────────────────

function validate(entryTags, content) {
  if (contracts.size === 0) return { valid: true, errors: [], contracts_matched: 0 };
  const allErrors = [];
  let matchedAny = false;
  for (const [scope, contract] of contracts) {
    if (!matchesScope(entryTags, scope)) continue;
    matchedAny = true;
    const result = validateContent(content, contract.schema);
    if (!result.valid) {
      allErrors.push(...result.errors.map(e => ({ ...e, contract_scope: scope })));
      if (contract.enforce === 'reject') return { valid: false, errors: result.errors, contract_scope: scope, enforce: 'reject', blocked: true };
    }
  }
  if (allErrors.length > 0) return { valid: false, errors: allErrors, contracts_matched: 1, blocked: false };
  return { valid: true, errors: [], contracts_matched: matchedAny ? 1 : 0 };
}

// ─── List ──────────────────────────────────────────────────────────────────

function listContracts() {
  const result = [];
  for (const [scope, contract] of contracts) {
    result.push({
      scope, schema: contract.schema, enforce: contract.enforce,
      created_at: contract.created_at, created_by: contract.created_by,
      version: contract.version,
    });
  }
  return result;
}

// ─── Remove ────────────────────────────────────────────────────────────────

function removeContract(scope) {
  if (!contracts.has(scope)) return { removed: false, error: 'Contract not found' };
  // Archive to history before deletion
  const contract = contracts.get(scope);
  const deleteEntry = {
    version: contract.version + 1,
    schema: null,
    enforce: null,
    changed_by: 'system',
    changed_at: new Date().toISOString(),
    change_type: 'delete',
  };
  contract.history.push(deleteEntry);
  contracts.delete(scope);
  saveContracts();
  // Also remove from SQLite
  try { govDb.deleteContract(scope); } catch (e) { /* ignore */ }
  return { removed: true, scope, archived: true };
}

module.exports = { registerContract, validate, listContracts, removeContract, matchesScope, rollbackContract, getContractHistory };
