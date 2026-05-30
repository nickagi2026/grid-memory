/**
 * constitution.js — Constitutional Memory
 *
 * Per-workspace constitution rules that enforce constraints on Grid entries.
 * Rules use regex/pattern matching to validate content.
 *
 * Supports two rule formats:
 *   String: "All decisions must include rationale" → extracted required words
 *   Object: { name, entryTypes, requiredWords, blockedPatterns }
 *
 * Endpoints:
 *   POST /constitution — register constitution rules
 *   GET /constitution — list constitutions
 *   DELETE /constitution — remove constitution
 */

const fs = require('fs');
const path = require('path');
const govDb = require('./governance-db.js');

function getConstDir() {
  return process.env.GRID_STORE_DIR || path.join(
    process.env.HOME || process.env.USERPROFILE || '/tmp',
    '.openclaw', 'grid'
  );
}

function constPath() {
  return path.join(getConstDir(), 'constitution.json');
}

function _ensureDir() {
  const dir = getConstDir();
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
}

function _load() {
  // PRIMARY: governance-db (SQLite). LEGACY FALLBACK: JSON file.

  // Try SQLite first
  try {
    const rows = govDb.getConstitutions();
    if (rows && rows.length > 0) {
      const result = { constitutions: {} };
      for (const row of rows) {
        result.constitutions[row.workspace] = {
          rules: JSON.parse(row.rules_json),
          enforceMode: row.enforce_mode,
          created_at: row.created_at,
          updated_at: row.updated_at,
        };
      }
      return result;
    }
  } catch (e) { /* fall through */ }

  _ensureDir();
  try {
    const fp = constPath();
    if (fs.existsSync(fp)) {
      return JSON.parse(fs.readFileSync(fp, 'utf-8'));
    }
  } catch (e) { /* ignore */ }
  return { constitutions: {} };
}

function _save(data) {
  // Try SQLite first
  if (govDb.isAvailable()) {
    try {
      for (const [workspace, c] of Object.entries(data.constitutions)) {
        govDb.saveConstitution(workspace, c);
      }
      return;
    } catch (e) { /* fall through */ }
  }

  _ensureDir();
  fs.writeFileSync(constPath(), JSON.stringify(data, null, 2), 'utf-8');
}

/**
 * Parse a plain string rule into a structured rule object.
 * "All decisions must include rationale" → { requiredWords: ['rationale'] }
 * "No API keys in content" → { blockedPatterns: ['api.?key'] }
 */
function parseStringRule(str) {
  const lower = str.toLowerCase();
  const rule = { name: str, description: str, patterns: [], entryTypes: [], requiredWords: [], blockedPatterns: [] };

  // Extract potential required words after "must include", "requires", "needs"
  const requiredMatch = lower.match(/(?:must\s+include|requires?|needs?|should\s+contain|must\s+have)\s+(\w+(?:\s*(?:\band\b|,)\s*\w+)*)/);
  if (requiredMatch) {
    rule.requiredWords = requiredMatch[1].split(/\s+(?:\band\b|,)\s+|\s+/).filter(Boolean);
  }

  // Extract blocked patterns after "No", "Don't", "Never"
  const blockedMatch = lower.match(/(?:no|don'?t|never|avoid|ban)\s+([\w\s]+?)(?:\s+in|\s*$)/);
  if (blockedMatch) {
    const blocked = blockedMatch[1].trim();
    // Convert to regex pattern
    const pattern = blocked.replace(/[-\/\\^$*+?.()|[\]{}]/g, '\\$&').replace(/\s+/g, '.{0,5}');
    rule.blockedPatterns.push(pattern);
  }

  // Extract entry type constraints
  if (lower.includes('decision')) rule.entryTypes.push('decision');
  if (lower.includes('fact')) rule.entryTypes.push('fact');

  // If we have a rule about decisions without rationale, add required word
  if (lower.includes('rationale') || lower.includes('because') || lower.includes('reason')) {
    if (!rule.requiredWords.includes('rationale')) rule.requiredWords.push('rationale');
    if (!rule.requiredWords.includes('because')) rule.requiredWords.push('because');
  }

  return rule;
}

/**
 * Normalize a rule: strings get parsed, objects get validated
 */
function normalizeRule(r) {
  if (typeof r === 'string') return parseStringRule(r);
  if (typeof r === 'object' && r !== null) {
    return {
      name: r.name || 'Unnamed rule',
      description: r.description || '',
      patterns: r.patterns || [],
      entryTypes: r.entryTypes || [],
      requiredWords: r.requiredWords || [],
      blockedPatterns: r.blockedPatterns || [],
    };
  }
  return null;
}

/**
 * Register a constitution for a workspace.
 * @param {string} workspace - Workspace identifier
 * @param {Array} rules - Array of rule strings or objects
 * @param {string} enforceMode - "validate" (default) or "block"
 */
function registerConstitution(workspace, rules, enforceMode = 'validate') {
  if (!workspace) throw new Error('workspace is required');
  if (!Array.isArray(rules)) throw new Error('rules must be an array');

  const normalized = rules.map(normalizeRule).filter(Boolean);
  const data = _load();
  data.constitutions[workspace] = {
    rules: normalized,
    enforceMode: enforceMode || 'validate',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
  _save(data);

  return { registered: true, workspace, rule_count: normalized.length, enforceMode };
}

function listConstitutions(workspace) {
  const data = _load();
  if (workspace) {
    return data.constitutions[workspace] || { rules: [], enforceMode: 'validate' };
  }
  return data.constitutions;
}

function removeConstitution(workspace) {
  const data = _load();
  if (!data.constitutions[workspace]) return { removed: false, message: `No constitution for workspace '${workspace}'` };
  delete data.constitutions[workspace];
  _save(data);
  // Also delete from governance DB
  try { govDb.deleteConstitution(workspace); } catch (e) { /* ignore govDb errors */ }
  return { removed: true, workspace };
}

/**
 * Validate an entry against workspace constitution rules.
 * Returns { valid, blocked, errors, warnings }
 */
function validateEntry(entry, workspace) {
  const data = _load();
  const constitution = data.constitutions[workspace];
  if (!constitution || constitution.rules.length === 0) {
    return { valid: true, blocked: false, errors: [], warnings: [] };
  }

  const errors = [];
  const warnings = [];
  const content = (entry.content || '').toLowerCase();
  const entryType = entry.type || 'observation';

  for (const rule of constitution.rules) {
    // Check if rule applies to this entry type
    if (rule.entryTypes.length > 0 && !rule.entryTypes.includes(entryType)) continue;

    // Check required words
    for (const word of rule.requiredWords) {
      if (!content.includes(word.toLowerCase())) {
        const msg = `Rule "${rule.name}": entry must contain "${word}"`;
        if (constitution.enforceMode === 'block') errors.push({ rule: rule.name, error: msg });
        else warnings.push({ rule: rule.name, warning: msg });
      }
    }

    // Check blocked patterns
    for (const pattern of rule.blockedPatterns) {
      try {
        const re = new RegExp(pattern, 'i');
        if (re.test(content)) {
          const msg = `Rule "${rule.name}": entry matches blocked pattern "${pattern}"`;
          if (constitution.enforceMode === 'block') errors.push({ rule: rule.name, error: msg });
          else warnings.push({ rule: rule.name, warning: msg });
        }
      } catch (e) {
        // Invalid regex — skip
      }
    }

    // Check content patterns
    for (const pattern of rule.patterns) {
      try {
        const re = new RegExp(pattern, 'i');
        if (!re.test(content)) {
          const msg = `Rule "${rule.name}": entry does not match pattern "${pattern}"`;
          if (constitution.enforceMode === 'block') errors.push({ rule: rule.name, error: msg });
          else warnings.push({ rule: rule.name, warning: msg });
        }
      } catch (e) {
        // Invalid regex — skip
      }
    }
  }

  return {
    valid: errors.length === 0,
    blocked: constitution.enforceMode === 'block' && errors.length > 0,
    errors,
    warnings,
  };
}

/**
 * Known pattern templates for natural language to constitution rules.
 * Each template has keywords to match and the resulting rule config.
 */
const NL_PATTERNS = [
  // PII / sensitive data blocking
  {
    patterns: [/pii/i, /personally identifiable/i, /private data/i, /personal info/i, /sensitive data/i],
    rule: { name: 'PII block', blockedPatterns: ['ssn', 'credit.?card', 'email', 'phone.?number', 'address', 'dob'] },
  },
  {
    patterns: [/phi/i, /protected health/i, /health info/i, /medical data/i, /hipaa/i],
    rule: { name: 'PHI block', blockedPatterns: ['ssn', 'medical.?record', 'diagnosis', 'treatment', 'patient'] },
  },
  {
    patterns: [/api.?key/i, /credential/i, /password/i, /secret.?key/i, /token/i, /auth.?key/i],
    rule: { name: 'No credentials in content', blockedPatterns: ['api.?key', 'sk[-_]', 'ghp_', 'gho_', 'ghu_', 'xox[baprs]-'] },
  },

  // Decision / rationale requirements
  {
    patterns: [/decision/i, /adr/i, /architecture.?decision/i],
    rule: { name: 'All decisions include rationale', entryTypes: ['decision'], requiredWords: ['rationale', 'because'] },
  },
  {
    patterns: [/rationale/i, /reason/i, /justification/i, /explain why/i],
    rule: { name: 'All entries include reasoning', requiredWords: ['because', 'rationale'] },
  },
  {
    patterns: [/alternatives/i, /other options/i, /trade.?offs?/i, /considered/i],
    rule: { name: 'All decisions include alternatives', entryTypes: ['decision'], requiredWords: ['alternative', 'option'] },
  },

  // Content requirements
  {
    patterns: [/source/i, /attribution/i, /cite/i, /reference/i],
    rule: { name: 'Include source attribution', requiredWords: ['source', 'via', 'reference'] },
  },
  {
    patterns: [/tag/i, /topic.?tag/i, /categor/i],
    rule: { name: 'Include topic tags', requiredWords: ['tag', 'topic'] },
  },

  // Compliance / audit
  {
    patterns: [/compliance/i, /audit/i, /regulat/i, /gdpr/i, /sox/i, /soc2/i, /soc.?2/i],
    rule: { name: 'Compliance tags required', requiredWords: ['compliance', 'audit'] },
  },
  {
    patterns: [/consent/i, /opt.?in/i, /gdpr/i, /privacy/i],
    rule: { name: 'Consent tracking required', requiredWords: ['consent', 'opt'] },
  },

  // Handoff / coordination
  {
    patterns: [/handoff/i, /hand.?off/i, /transfer/i, /pass.?to/i, /assign/i],
    rule: { name: 'Handoffs include context', entryTypes: ['handoff'], requiredWords: ['context', 'status', 'next'] },
  },
  {
    patterns: [/blocker/i, /blocked/i, /impediment/i, /blocking/i, /stuck/i],
    rule: { name: 'Blockers include resolution path', entryTypes: ['blocker'], requiredWords: ['resolution', 'blocker', 'blocked'] },
  },

  // Never / Don't rules
  {
    patterns: [/never store/i, /don.?t store/i, /never include/i, /never log/i],
    rule: { name: 'Prohibited content enforcement', blockedPatterns: [] },
  },
];

/**
 * Extract specific blocked patterns or required words from a natural language rule.
 * Handles phrases like:
 *   "Never store API keys" → blockedPatterns: ['api.?key']
 *   "All decisions must include rationale" → requiredWords: ['rationale'], entryTypes: ['decision']
 *   "Don't include PII in content" → blockedPatterns: ['ssn', 'credit.?card', 'email']
 */
function extractFromText(text) {
  const result = { requiredWords: [], blockedPatterns: [], entryTypes: [], name: text };
  const lower = text.toLowerCase();

  // ── Blocked pattern extraction ──

  // API keys / credentials
  if (/api.?key|api.?secret|credential/i.test(lower)) {
    result.blockedPatterns.push('api.?key', 'sk[-_]', 'ghp_', 'xox[baprs]-');
  }

  // PII patterns
  if (/pii|personally.?identif|ssn|social.?security|private.?info/i.test(lower)) {
    result.blockedPatterns.push('ssn', 'credit.?card', 'email', 'phone.?number');
  }

  // PHI patterns
  if (/phi|protected.?health|medical|health.?info|hipaa/i.test(lower)) {
    result.blockedPatterns.push('ssn', 'medical.?record', 'diagnosis', 'treatment');
  }

  // Password / secrets
  if (/password|secret|credential|token/i.test(lower)) {
    result.blockedPatterns.push('password', 'secret.?key', 'ghp_', 'gho_');
  }

  // ── Required word extraction ──

  // Decision + rationale
  if (/decision/i.test(lower)) {
    result.entryTypes.push('decision');
    if (/rationale|reason|justification|because|why/i.test(lower)) {
      result.requiredWords.push('rationale', 'because');
    }
    if (/alternative|other option|tradeoff/i.test(lower)) {
      result.requiredWords.push('alternative', 'option');
    }
  }

  // Source/attribution
  if (/source|attribution|cite|reference|credit/i.test(lower)) {
    result.requiredWords.push('source', 'reference');
  }

  // Tags/categories
  if (/tag|categor|topic/i.test(lower)) {
    result.requiredWords.push('tag');
  }

  // Context requirements (handoffs)
  if (/context|status|handoff|transfer/i.test(lower)) {
    result.requiredWords.push('context', 'status');
  }

  // ── Entry type detection ──

  if (/handoff|hand.?off|transfer|assign/i.test(lower)) {
    if (!result.entryTypes.includes('handoff')) result.entryTypes.push('handoff');
  }

  if (/blocker|blocked|impediment|stuck/i.test(lower)) {
    if (!result.entryTypes.includes('blocker')) result.entryTypes.push('blocker');
  }

  if (/fact|knowledge/i.test(lower)) {
    if (!result.entryTypes.includes('fact')) result.entryTypes.push('fact');
  }

  // ── Compliance tags ──
  if (/compliance|audit|regulat/i.test(lower)) {
    result.requiredWords.push('compliance', 'audit');
  }

  return result;
}

/**
 * Convert natural language policy text into structured constitution rules.
 * Uses keyword/pattern matching — no AI dependency.
 *
 * @param {string} text — natural language policy (e.g. "Never store API keys")
 * @param {string} [enforceMode='block'] — 'validate' or 'block'
 * @returns {Object} { rules: [...], enforceMode: string, originalText: string }
 */
function generateFromNaturalLanguage(text, enforceMode = 'block') {
  if (!text || typeof text !== 'string') {
    throw new Error('text is required');
  }

  // Split on sentences, line breaks, or semicolons
  const sentences = text
    .split(/[.\n;]+/)
    .map(s => s.trim())
    .filter(s => s.length > 0);

  const rules = [];

  for (const sentence of sentences) {
    const lower = sentence.toLowerCase();

    // First try exact keyword matches against known patterns
    let matched = false;
    for (const template of NL_PATTERNS) {
      if (template.patterns.some(p => p.test(sentence))) {
        rules.push({
          name: template.rule.name,
          description: sentence,
          entryTypes: template.rule.entryTypes || [],
          requiredWords: template.rule.requiredWords || [],
          blockedPatterns: template.rule.blockedPatterns || [],
          patterns: [],
        });
        matched = true;
        break;
      }
    }

    if (matched) continue;

    // Fall back to deep extraction
    const extracted = extractFromText(sentence);

    // Build the rule from extracted data
    const rule = {
      name: extracted.name.slice(0, 80),
      description: sentence,
      entryTypes: extracted.entryTypes,
      requiredWords: extracted.requiredWords,
      blockedPatterns: extracted.blockedPatterns,
      patterns: [],
    };

    // Even without specific extracted fields, create a basic rule
    if (rule.requiredWords.length === 0 && rule.blockedPatterns.length === 0) {
      // Try basic keyword extraction: important nouns/verbs
      const importantWords = sentence.match(/\b[A-Z][a-z]+\b|\b(?:never|always|must|should|require|need|include|exclude|block|allow|deny)\b/gi);
      if (importantWords && importantWords.length > 0) {
        rule.requiredWords = importantWords.slice(0, 3).map(w => w.toLowerCase());
      }
    }

    rules.push(rule);
  }

  // Deduplicate rules by name
  const seen = new Set();
  const unique = [];
  for (const r of rules) {
    if (!seen.has(r.name)) {
      seen.add(r.name);
      unique.push(r);
    }
  }

  return {
    rules: unique,
    enforceMode: enforceMode || 'block',
    originalText: text,
    sentence_count: sentences.length,
    rule_count: unique.length,
  };
}

module.exports = { registerConstitution, listConstitutions, removeConstitution, validateEntry, generateFromNaturalLanguage, parseStringRule };
