#!/usr/bin/env node
/**
 * auto-contract.js — Auto-Generated Contracts from Existing Entries
 *
 * Scans existing entries by tag scope, identifies common field patterns,
 * and suggests contract schemas. User approves or edits before activation.
 *
 * Approval/Rejection state tracked in a simple JSON file.
 */

const fs = require('fs');
const path = require('path');
const contracts = require('./contracts.js');

function getStoreDir() {
  return process.env.GRID_STORE_DIR || path.join(
    process.env.HOME || process.env.USERPROFILE || '/tmp',
    '.openclaw', 'grid'
  );
}

function approvalsPath() {
  return path.join(getStoreDir(), 'auto-contract-approvals.json');
}

function _ensureDir() {
  const dir = getStoreDir();
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
}

function _loadApprovals() {
  _ensureDir();
  try {
    if (fs.existsSync(approvalsPath())) {
      const raw = fs.readFileSync(approvalsPath(), 'utf-8');
      return JSON.parse(raw);
    }
  } catch (e) { /* ignore */ }
  return { approved: [], rejected: [], pending: [] };
}

function _saveApprovals(data) {
  _ensureDir();
  fs.writeFileSync(approvalsPath(), JSON.stringify(data, null, 2), 'utf-8');
}

// ── Suggestion Generation ──

async function suggestContracts(grid) {
  const result = await grid.read({ max: 200 });
  const entries = result.entries || [];

  // Load previous approvals/rejections to avoid re-suggesting
  const approvals = _loadApprovals();

  // Group entries by tag scope (first non-system tag = scope)
  const scopes = {};
  for (const e of entries) {
    const primaryTag = (e.tags || []).find(t => !t.startsWith('_') && !t.startsWith('ws:'));
    if (!primaryTag) continue;
    if (!scopes[primaryTag]) scopes[primaryTag] = [];
    scopes[primaryTag].push(e.content || '');
  }

  const suggestions = [];
  for (const [scope, contents] of Object.entries(scopes)) {
    // Skip if previously rejected
    if (approvals.rejected.includes(scope)) continue;
    // Skip if already approved and registered
    if (approvals.approved.includes(scope) && contracts.listContracts().some(c => c.scope === scope)) continue;

    if (contents.length < 3) continue; // Need 3+ entries to detect pattern

    // Try to parse as JSON
    const jsonEntries = contents.map(c => {
      try { return typeof c === 'string' ? JSON.parse(c) : c; }
      catch { return null; }
    }).filter(Boolean);

    if (jsonEntries.length >= 3) {
      // Detect fields and their types
      const fields = {};
      for (const entry of jsonEntries) {
        for (const [key, value] of Object.entries(entry)) {
          if (!fields[key]) fields[key] = { types: new Set(), required: true };
          if (value !== undefined && value !== null) {
            fields[key].types.add(typeof value === 'object' && !Array.isArray(value) ? 'object' : typeof value);
          }
          fields[key].required = fields[key].required && entry[key] !== undefined && entry[key] !== null;
        }
      }

      // Build schema suggestion
      const schema = {};
      const required = [];
      for (const [field, info] of Object.entries(fields)) {
        if (info.types.size === 1) {
          const t = info.types.values().next().value;
          schema[field] = t;
          if (info.required) required.push(field);
        }
      }
      if (required.length > 0) schema.required = required;

      if (Object.keys(schema).length > 0 && Object.keys(schema).filter(k => k !== 'required').length > 0) {
        suggestions.push({
          scope,
          suggested_schema: schema,
          observed_entries: jsonEntries.length,
          confidence: Math.min(100, Math.round((jsonEntries.length / contents.length) * 100)),
          status: 'pending',
        });
      }
    }
  }

  // Merge with any existing pending suggestions
  for (const s of suggestions) {
    const existing = approvals.pending.find(p => p.scope === s.scope);
    if (existing) {
      s.status = 'pending';
      s.pending_since = existing.pending_since;
    } else {
      approvals.pending.push({ scope: s.scope, pending_since: new Date().toISOString() });
    }
  }
  _saveApprovals(approvals);

  return { suggestions, total: suggestions.length, pending_count: approvals.pending.length };
}

// ── Approval / Rejection Functions ──

/**
 * Approve a contract suggestion and register it as a real contract.
 * @param {Object} suggestion — { scope, suggested_schema, ... }
 * @returns {Object} result with registration details
 */
function approveContract(suggestion) {
  if (!suggestion || !suggestion.scope || !suggestion.suggested_schema) {
    throw new Error('suggestion with scope and suggested_schema is required');
  }

  const approvals = _loadApprovals();

  // Register as a real contract
  const contractResult = contracts.registerContract(
    suggestion.scope,
    suggestion.suggested_schema,
    'validate'
  );

  // Update approval state
  if (!approvals.approved.includes(suggestion.scope)) {
    approvals.approved.push(suggestion.scope);
  }
  // Remove from pending
  approvals.pending = approvals.pending.filter(p => p.scope !== suggestion.scope);
  _saveApprovals(approvals);

  return {
    approved: true,
    scope: suggestion.scope,
    registered: contractResult,
    timestamp: new Date().toISOString(),
  };
}

/**
 * Reject a contract suggestion — won't be suggested again.
 * @param {string} scope — the tag scope to reject
 * @returns {Object} result
 */
function rejectContract(scope) {
  if (!scope) throw new Error('scope is required');

  const approvals = _loadApprovals();

  if (!approvals.rejected.includes(scope)) {
    approvals.rejected.push(scope);
  }
  // Remove from pending
  approvals.pending = approvals.pending.filter(p => p.scope !== scope);
  _saveApprovals(approvals);

  return {
    rejected: true,
    scope,
    timestamp: new Date().toISOString(),
    message: `Contract for scope "${scope}" rejected and will not be suggested again.`,
  };
}

/**
 * Get the full approval state (approved, rejected, pending).
 */
function getApprovalState() {
  const approvals = _loadApprovals();
  return {
    approved_scopes: approvals.approved,
    rejected_scopes: approvals.rejected,
    pending_scopes: approvals.pending.map(p => p.scope),
  };
}

module.exports = { suggestContracts, approveContract, rejectContract, getApprovalState };
