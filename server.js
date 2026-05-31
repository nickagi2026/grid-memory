#!/usr/bin/env node
/**
 * grid-memory/server.js
 *
 * HTTP wrapper for The Grid. Exposes the store.js API as REST endpoints.
 *
 * Usage:
 *   node server.js                    # listens on 0.0.0.0:8080
 *   PORT=9090 node server.js         # custom port
 *   GRID_STORE_DIR=/data node server.js  # custom data directory
 *
 * Endpoints:
 *   POST /write   { agent_id, type, content, tags, ttl_seconds, session_id, parent_entry }
 *   GET  /query   ?tags=a,b&agents=x&type=y&max=20
 *   POST /prune
 *   GET  /inject  ?context=message
 *   GET  /info
 *   DELETE /forget/:id
 *   GET  /health
 */

const http = require('http');
const fs = require('fs');
const path = require('path');
const { Grid } = require('./reference/store.js');
const openaiProxy = require('./openai-proxy.js');
const decisionGraph = require('./decision-graph.js');
const amnesiaDetector = require('./amnesia-detector.js');
const roiModule = require('./instant-roi.js');
const staleness = require('./staleness.js');
const autoContract = require('./auto-contract.js');
const constitution = require('./constitution.js');
const explain = require('./explain.js');
const cascade = require('./cascade.js');
const provenance = require('./provenance.js');
const dreaming = require('./dreaming.js');
const { Gateway, scanPII, logAudit, getKeys, getAuditLog, endpointLimiter } = require('./gateway.js');
const subscriptions = require('./subscriptions.js');
const contracts = require('./contracts.js');
const reputation = require('./reputation.js');
const conflicts = require('./conflicts.js');
const federation = require('./federation.js');
const seedMode = require("./seed-mode.js");
const setupWizard = require('./setup-wizard.js');

const PORT = parseInt(process.env.PORT, 10) || 8080;
const HOST = process.env.HOST || '0.0.0.0';

const grid = new Grid();

// ─── JSON body parser ──────────────────────────────────────────────────────────

function parseBody(req) {
  return new Promise((resolve, reject) => {
    const maxSize = parseInt(process.env.GRID_MAX_BODY_SIZE || '1048576', 10);
    let body = '';
    let totalBytes = 0;

    req.on('data', chunk => {
      totalBytes += Buffer.byteLength(chunk, 'utf-8');
      if (totalBytes > maxSize) {
        req.destroy(new Error('Request body too large'));
        reject(new Error(`Request body exceeds ${Math.round(maxSize / 1024)}KB limit`));
        return;
      }
      body += chunk;
    });

    req.on('end', () => {
      if (!body) return resolve({});
      try {
        resolve(JSON.parse(body));
      } catch (e) {
        reject(new Error('Invalid JSON'));
      }
    });
    req.on('error', reject);
  });
}

// ─── URL query parser ──────────────────────────────────────────────────────────

// ─── Workspace helper ──────────────────────────────────────────────────────

function getWorkspace(req) {
  // Priority: gateway-derived → header → env → empty
  if (req.workspace) return req.workspace;
  if (req.headers['x-grid-workspace']) return req.headers['x-grid-workspace'];
  return process.env.GRID_WORKSPACE || '';
}

// ─── Query Parser ──────────────────────────────────────────────────────────

function parseQuery(url) {
  const idx = url.indexOf('?');
  if (idx === -1) return {};
  const qs = url.slice(idx + 1);
  const params = {};
  for (const part of qs.split('&')) {
    const [k, v] = part.split('=').map(decodeURIComponent);
    if (k) params[k] = v;
  }
  return params;
}

// ─── Response helpers ──────────────────────────────────────────────────────────

function json(res, data, status = 200, corsHeaders) {
  const headers = {
    'Content-Type': 'application/json',
    'Access-Control-Allow-Origin': corsHeaders ? (corsHeaders['Access-Control-Allow-Origin'] || '*') : '*',
    'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Grid-Workspace',
  };
  if (corsHeaders && corsHeaders['Access-Control-Allow-Origin'] !== '*') {
    headers['Access-Control-Allow-Origin'] = corsHeaders['Access-Control-Allow-Origin'];
  }
  res.writeHead(status, headers);
  res.end(JSON.stringify(data, null, 2));
}

function error(res, message, status = 400, code = 'INVALID_PARAMETER') {
  json(res, { error: message, code }, status);
}

// ─── Gateway Setup ──────────────────────────────────────────────────────────────

const gateway = new Gateway();
gateway.config.ENFORCE_AUTH = process.env.GRID_ENFORCE_AUTH === 'true';

// ─── MIKE Intelligence — optional enterprise tier ────────────────
let mikeDashboard = null;
let qbrGenerator = null;
try {
  mikeDashboard = require('./mike-dashboard.js');
  qbrGenerator = require('./qbr-generator.js');
} catch (e) {
  // MIKE Intelligence not installed — routes will return 402
}

// ─── MIKE License Gate ────────────────────────────────────────────
function mikeRequired(handler) {
  return async (req, res, grid, gateway, query, params) => {
    if (!mikeDashboard) {
      res.writeHead(402, { 'Content-Type': 'application/json' });
      return res.end(JSON.stringify({
        error: 'MIKE Intelligence requires an upgrade.',
        upgrade: 'https://gridmemory.io/mike',
        contact: 'nick@criticalpathfoundry.com',
        free_features: [
          '/amnesia/detect — always free',
          '/decisions/graph — always free',
          '/roi — always free',
        ],
      }));
    }
    return handler(req, res, grid, gateway, query, params);
  };
}

if (process.env.GRID_ENFORCE_AUTH !== 'true') {
  console.warn('⚠️  GRID_ENFORCE_AUTH is not set. The server is running in DEVELOPMENT MODE with NO authentication.');
  console.warn('   Set GRID_ENFORCE_AUTH=true and create an admin API key for production use.');
  console.warn('   Create a key: curl -X POST http://localhost:' + PORT + '/gateway/key/create -H "Content-Type: application/json" -d \'{"label":"admin","permission":"admin"}\'');
}

// ─── Route Registry ────────────────────────────────────────────────────────────

const { RouteRegistry } = require('./route-registry.js');
const registry = new RouteRegistry();

// Register MIKE intelligence endpoints with mandatory permissions
// These are the crown jewels — revenue, opportunities, decisions, risks
// parseBody and logAudit are passed in to avoid circular requires
function registerIntelligenceRoutes() {
  const { logAudit } = require('./gateway.js');

  // MIKE Intelligence endpoints with rate limits matching docs
  registry.register('GET', '/roi', 'analyst', async (req, res, grid) => {
    const roi = roiModule;
    const result = await roi.computeROI(grid);
    logAudit('roi', 'allowed', 'GET', '/roi', '', '', '', '');
    return json(res, result);
  }, { rateLimit: 30 });

  registry.register('GET', '/mike/dashboard', 'analyst', mikeRequired(async (req, res, grid) => {
    
    logAudit('mike_dashboard', 'allowed', 'GET', '/mike/dashboard', '', '', '', '');
    const result = await mikeDashboard.generateDashboard(grid);
    return json(res, result);
  }), { rateLimit: 20 });

  registry.register('GET', '/executive/dashboard', 'analyst', mikeRequired(async (req, res, grid) => {
    
    
    
    
    logAudit('executive_dashboard', 'allowed', 'GET', '/executive/dashboard', '', '', '', '');
    const [dr, dsr, qr, ar] = await Promise.allSettled([
      mikeDashboard.generateDashboard(grid), decisionGraph.getStats(grid),
      qbrGenerator.generate(grid, {}), amnesiaDetector.detect(grid),
    ]);
    return json(res, {
      summary: dr.status === 'fulfilled' ? dr.value.summary : null,
      revenue: dr.status === 'fulfilled' ? dr.value.revenue : null,
      clients: dr.status === 'fulfilled' ? dr.value.clients : [],
      recent_decisions: dr.status === 'fulfilled' ? (dr.value.decisions || {}).recent || [] : [],
      opportunities: dr.status === 'fulfilled' ? dr.value.opportunities : null,
      risks: dr.status === 'fulfilled' ? dr.value.risks : [],
      decision_stats: dsr.status === 'fulfilled' ? dsr.value : null,
      qbr: qr.status === 'fulfilled' ? { title: qr.value.title, kpis: qr.value.kpis, sections: (qr.value.sections || []).slice(0, 2) } : null,
      amnesia: ar.status === 'fulfilled' ? {
        amnesia_score: ar.value.amnesia_score,
        gaps_count: ar.value.gaps.length,
        orphans_count: ar.value.orphans.length,
        stale_count: ar.value.stale_decisions.length,
        spof_count: ar.value.single_points_of_failure.length,
        summary: ar.value.summary,
      } : null,
      generated_at: new Date().toISOString(),
    });
  }), { rateLimit: 10 });

  registry.register('GET', '/decisions/graph', 'analyst', async (req, res, grid, gateway, query) => {
    
    logAudit('decision_graph', 'allowed', 'GET', '/decisions/graph', '', '', '', '');
    const depth = query.depth ? Math.min(parseInt(query.depth, 10), 20) : 5;
    return json(res, await decisionGraph.getGraph(grid, { depth }));
  }, { rateLimit: 20 });

  registry.register('GET', '/decisions/stats', 'analyst', async (req, res, grid) => {
    
    logAudit('decision_stats', 'allowed', 'GET', '/decisions/stats', '', '', '', '');
    return json(res, await decisionGraph.getStats(grid));
  }, { rateLimit: 20 });

  registry.register('GET', '/qbr', 'analyst', mikeRequired(async (req, res, grid, gateway, query) => {
    
    logAudit('qbr_get', 'allowed', 'GET', '/qbr', '', '', '', '');
    return json(res, await qbrGenerator.generate(grid, { period: query.period || '' }));
  }), { rateLimit: 15 });

  registry.register('POST', '/qbr/generate', 'analyst', mikeRequired(async (req, res, grid) => {
    
    logAudit('qbr_generate', 'allowed', 'POST', '/qbr/generate', '', '', '', '');
    const body = await parseBody(req);
    return json(res, await qbrGenerator.generate(grid, { period: body.period || body.quarter || '' }));
  }), { rateLimit: 15 });

  registry.register('GET', '/amnesia/detect', 'analyst', async (req, res, grid) => {
    logAudit('amnesia_detect', 'allowed', 'GET', '/amnesia/detect', '', '', '', '');
    return json(res, await amnesiaDetector.detect(grid));
  }, { rateLimit: 15 });

  registry.register('POST', '/setup-wizard', 'admin', async (req, res, grid) => {
    
    logAudit('setup_wizard', 'allowed', 'POST', '/setup-wizard', '', '', '', '');
    const body = await parseBody(req);
    if (body && body.purpose) {
      logAudit('setup_wizard_apply', 'allowed', 'POST', '/setup-wizard', '', '', '', `purpose=${body.purpose}`);
      return json(res, await setupWizard.applyConfig(body, grid));
    }
    return json(res, await setupWizard.wizard(grid));
  });

  // Governance and intelligence endpoints
  registry.register('GET', '/staleness', 'analyst', async (req, res, grid) => {
    logAudit('staleness', 'allowed', 'GET', '/staleness', '', '', '', '');
    return json(res, await staleness.findStale(grid, { maxResults: 50 }));
  }, { rateLimit: 20 });

  registry.register('GET', '/drafts', 'architect', async (req, res, grid) => {
    logAudit('drafts_list', 'allowed', 'GET', '/drafts', '', '', '', '');
    return json(res, await dreaming.listDrafts(grid));
  }, { rateLimit: 20 });

  registry.register('GET', '/provenance/:id', 'analyst', async (req, res, grid, gateway, query, params) => {
    logAudit('provenance', 'allowed', 'GET', '/provenance/' + params.id, '', '', '', '');
    return json(res, await provenance.getChain(grid, params.id));
  }, { rateLimit: 30 });

  registry.register('GET', '/cascade/:id', 'analyst', async (req, res, grid, gateway, query, params) => {
    logAudit('cascade', 'allowed', 'GET', '/cascade/' + params.id, '', '', '', '');
    return json(res, await cascade.getCascade(grid, params.id));
  }, { rateLimit: 20 });

  registry.register('GET', '/explain/:id', 'analyst', async (req, res, grid, gateway, query, params) => {
    logAudit('explain', 'allowed', 'GET', '/explain/' + params.id, '', '', '', '');
    let format = query.format || 'narrative';
    if (!['narrative', 'json', 'markdown'].includes(format)) format = 'narrative';
    return json(res, await explain.generateTranscript(grid, params.id, { format }));
  }, { rateLimit: 20 });

  registry.register('POST', '/constitution', 'architect', async (req, res, grid) => {
    logAudit('constitution_register', 'allowed', 'POST', '/constitution', '', '', '', '');
    const body = await parseBody(req);
    const ws = req.headers['x-grid-workspace'] || body.workspace || 'default';
    return json(res, constitution.registerConstitution(ws, body.rules || [], body.enforceMode || 'validate'));
  });

  registry.register('DELETE', '/constitution', 'architect', async (req, res, grid) => {
    logAudit('constitution_remove', 'allowed', 'DELETE', '/constitution', '', '', '', '');
    const body = await parseBody(req);
    return json(res, constitution.removeConstitution(body.workspace || 'default'));
  });

  registry.register('POST', '/constitution/from-text', 'admin', async (req, res, grid) => {
    logAudit('constitution_from_text', 'allowed', 'POST', '/constitution/from-text', '', '', '', '');
    const body = await parseBody(req);
    const generated = constitution.generateFromNaturalLanguage(body.text, body.enforceMode || 'block');
    if (generated.rules.length > 0) {
      return json(res, { generated, registered: constitution.registerConstitution('default', generated.rules, generated.enforceMode) });
    }
    return json(res, { generated, message: 'No rules could be generated from the provided text.' });
  });

  registry.register('GET', '/auto-contracts/state', 'analyst', async (req, res, grid) => {
    logAudit('auto_contract_state', 'allowed', 'GET', '/auto-contracts/state', '', '', '', '');
    return json(res, autoContract.getApprovalState());
  });

  registry.register('POST', '/auto-contracts/approve', 'admin', async (req, res, grid) => {
    logAudit('auto_contract_approve', 'allowed', 'POST', '/auto-contracts/approve', '', '', '', '');
    const body = await parseBody(req);
    return json(res, autoContract.approveContract(body));
  });

  registry.register('POST', '/auto-contracts/reject', 'admin', async (req, res, grid) => {
    logAudit('auto_contract_reject', 'allowed', 'POST', '/auto-contracts/reject', '', '', '', '');
    const body = await parseBody(req);
    return json(res, autoContract.rejectContract(body.scope));
  });

  registry.register('GET', '/auto-contracts', 'analyst', async (req, res, grid) => {
    logAudit('auto_contracts', 'allowed', 'GET', '/auto-contracts', '', '', '', '');
    return json(res, await autoContract.suggestContracts(grid));
  }, { rateLimit: 20 });
}


  registry.register('POST', '/prune', 'admin', async (req, res, grid) => {
    logAudit('prune', 'allowed', 'POST', '/prune', '', '', '', '');
    return json(res, await grid.prune());
  });

  registry.register('DELETE', '/forget/:id', 'admin', async (req, res, grid, gateway, query, params) => {
    logAudit('forget', 'allowed', 'DELETE', '/forget/' + params.id, '', '', '', '');
    // Workspace isolation check
    const ws = getWorkspace(req);
    if (ws) {
      const lookup = await grid.read({ entry_id: params.id });
      const found = lookup.entries || [];
      if (found.length === 0) return error(res, 'Entry not found', 404);
      const entryWs = (found[0].tags || []).filter(t => t.startsWith('ws:'));
      if (entryWs.length > 0 && !entryWs.includes('ws:' + ws)) {
        return error(res, 'Entry does not belong to this workspace', 403, 'WORKSPACE_MISMATCH');
      }
    }
    const result = await grid.forget(params.id);
    if (!result.found) return error(res, result.message, 404, 'NOT_FOUND');
    return json(res, result);
  });

  registry.register('GET', '/export', 'architect', async (req, res, grid) => {
    if (!endpointLimiter(req)) return json(res, { error: 'Rate limit exceeded for /export. Max 10/min.', code: 'RATE_LIMITED' }, 429);
    logAudit('export', 'allowed', 'GET', '/export', '', '', '', '');
    const ws = getWorkspace(req);
    const result = await grid.exportAll();
    let entries = result.entries || [];
    if (ws) entries = entries.filter(e => (e.tags || []).includes('ws:' + ws));
    return json(res, { version: 1, exported_at: new Date().toISOString(), workspace: ws || 'global', entry_count: entries.length, entries: entries });
  });

  registry.register('POST', '/import', 'admin', async (req, res, grid) => {
    logAudit('import', 'allowed', 'POST', '/import', '', '', '', '');
    const body = await parseBody(req);
    if (!body.entries || !Array.isArray(body.entries)) return error(res, 'entries array is required', 400);
    const ws = getWorkspace(req);
    let imported = 0, skipped = 0;
    for (const entry of body.entries) {
      if (!entry.agent_id || !entry.content) { skipped++; continue; }
      const entryTags = [...(entry.tags || [])].filter(t => !t.startsWith('ws:'));
      if (ws) entryTags.push('ws:' + ws);
      try {
        await grid.write({ agent_id: entry.agent_id, type: entry.type || 'observation', tags: entryTags, content: entry.content, ttl_seconds: entry.ttl_seconds, session_id: entry.session_id || '', parent_entry: entry.parent_entry || null, memory_tier: entry.memory_tier || null, force_id: entry.id || null, force_created_at: entry.created_at || null, force_expires_at: entry.expires_at || null,
          workspace_id: ws || null });
        imported++;
      } catch (e) { skipped++; }
    }
    return json(res, { imported, skipped, workspace: ws || 'global' });
  });

  registry.register('POST', '/seed', 'admin', async (req, res, grid) => {
    logAudit('seed', 'allowed', 'POST', '/seed', '', '', '', '');
    return json(res, await seedMode.seedGrid(grid));
  });

  registry.register('POST', '/federation/quick-connect', 'admin', async (req, res, grid) => {
    const body = await parseBody(req);
    logAudit('federation_quick_connect', 'allowed', 'POST', '/federation/quick-connect', '', '', '', body.peerUrl || '');
    return json(res, await require('./federation.js').quickConnect(body.peerUrl, body.options || {}));
  });

  registry.register('POST', '/contracts', 'architect', async (req, res, grid) => {
    logAudit('contracts_register', 'allowed', 'POST', '/contracts', '', '', '', '');
    const body = await parseBody(req);
    return json(res, require('./contracts.js').registerContract(body.scope, body.schema, body.enforce, body.created_by));
  });

  registry.register('DELETE', '/contracts/:scope', 'architect', async (req, res, grid, gateway, query, params) => {
    logAudit('contracts_remove', 'allowed', 'DELETE', '/contracts/' + params.scope, '', '', '', '');
    return json(res, require('./contracts.js').removeContract(params.scope));
  });

  registry.register('GET', '/agents/reputation', 'analyst', async (req, res, grid) => {
    logAudit('reputation', 'allowed', 'GET', '/agents/reputation', '', '', '', '');
    return json(res, await require('./reputation.js').getAll(grid));
  });



  registry.register('POST', '/federation/peers', 'admin', async (req, res, grid) => {
    const body = await parseBody(req);
    logAudit('federation_peer_add', 'allowed', 'POST', '/federation/peers', '', '', '', body.url || '');
    return json(res, require('./federation.js').registerPeer(body.url, body.trustLevel || 'unverified', body.sharedSecret || null));
  });

  registry.register('GET', '/federation/peers', 'analyst', async (req, res, grid) => {
    logAudit('federation_peers_list', 'allowed', 'GET', '/federation/peers', '', '', '', '');
    return json(res, { peers: require('./federation.js').listPeers() });
  });

  registry.register('DELETE', '/federation/peers/*', 'admin', async (req, res, grid, gateway, query, params) => {
    const fullPath = req.url.split('?')[0];
    const peerUrl = decodeURIComponent(fullPath.slice('/federation/peers/'.length));
    logAudit('federation_peer_remove', 'allowed', 'DELETE', '/federation/peers/' + peerUrl, '', '', '', '');
    return json(res, require('./federation.js').removePeer(peerUrl));
  });

  registry.register('POST', '/federation/sync/*', 'admin', async (req, res, grid) => {
    const fullPath = req.url.split('?')[0];
    const peerUrl = decodeURIComponent(fullPath.slice('/federation/sync/'.length));
    logAudit('federation_sync', 'allowed', 'POST', '/federation/sync/' + peerUrl, '', '', '', '');
    return json(res, await require('./federation.js').syncFromPeer(grid, peerUrl));
  });


registerIntelligenceRoutes();

// ─── Router ────────────────────────────────────────────────────────────────────

async function handle(req, res) {
  // CORS preflight
  if (req.method === 'OPTIONS') {
    const cors = gateway.corsHeaders(req);
    res.writeHead(204, cors);
    return res.end();
  }

  // Check route registry first (structured auth enforcement)
  const match = registry.match(req.method, req.url);
  if (match) {
    if (process.env.GRID_ENFORCE_AUTH === 'true') {
      const auth = await registry.enforce(gateway, req, match.route);
      if (!auth.allowed) {
        return auth.respond(res);
      }
      if (auth.auth && auth.auth.workspace) {
        req.workspace = auth.auth.workspace;
      }
    }
    const query = parseQuery(req.url);
    await match.route.handler(req, res, grid, gateway, query, match.params);
    return;
  }

  const method = req.method;
  const url = req.url.split('?')[0];

  // Gateway management endpoints (bypass enforcement, require admin)
  if (method === 'POST' && url.startsWith('/gateway/key/create')) {
    // Require admin auth
    if (process.env.GRID_ENFORCE_AUTH === 'true') {
      const pipeline = await gateway.enforce(req, 'admin');
      if (!pipeline.allowed) {
        const cors = gateway.corsHeaders(req);
        res.writeHead(pipeline.status, cors);
        return res.end(JSON.stringify(pipeline.error, null, 2));
      }
    }
    let body = '';
    req.on('data', c => body += c);
    req.on('end', () => {
      try {
        const opts = JSON.parse(body);
        const result = gateway.createKey(
          opts.label || 'API Key',
          opts.workspace || '*',
          opts.permission || 'read',
          opts.expires_in_days || null
        );
        res.writeHead(200, gateway.corsHeaders(req));
        res.end(JSON.stringify({ ...result, plaintext_key: result.plaintextKey, key_id: result.keyId }, null, 2));
      } catch (e) {
        res.writeHead(400, gateway.corsHeaders(req));
        res.end(JSON.stringify({ error: e.message }));
      }
    });
    return;
  }

  // Gateway admin auth helper
  async function requireAdmin() {
    if (process.env.GRID_ENFORCE_AUTH === 'true') {
      const p = await gateway.enforce(req, 'admin');
      return p.allowed ? null : p;
    }
    return null;
  }

  if (url === '/gateway/keys' && method === 'GET') {
    const authErr = await requireAdmin(); if (authErr) { res.writeHead(authErr.status, gateway.corsHeaders(req)); return res.end(JSON.stringify(authErr.error)); }
    const keys = await gateway.listKeys();
    res.writeHead(200, gateway.corsHeaders(req));
    return res.end(JSON.stringify({ keys }, null, 2));
  }

  if (url.startsWith('/gateway/key/revoke/') && method === 'DELETE') {
    const authErr = await requireAdmin(); if (authErr) { res.writeHead(authErr.status, gateway.corsHeaders(req)); return res.end(JSON.stringify(authErr.error)); }
    const keyId = url.slice('/gateway/key/revoke/'.length);
    const result = gateway.revokeKey(keyId);
    res.writeHead(200, gateway.corsHeaders(req));
    return res.end(JSON.stringify(result, null, 2));
  }

  if (url === '/gateway/audit' && method === 'GET') {
    const authErr = await requireAdmin(); if (authErr) { res.writeHead(authErr.status, gateway.corsHeaders(req)); return res.end(JSON.stringify(authErr.error)); }
    const filter = {
      action: req.url.includes('action=') ? new URL(req.url, 'http://localhost').searchParams.get('action') : null,
      workspace: req.url.includes('workspace=') ? new URL(req.url, 'http://localhost').searchParams.get('workspace') : null,
      limit: req.url.includes('limit=') ? new URL(req.url, 'http://localhost').searchParams.get('limit') : null,
    };
    const entries = await gateway.getAuditLog(filter);
    res.writeHead(200, gateway.corsHeaders(req));
    return res.end(JSON.stringify({ entries }, null, 2));
  }

  if (url === '/gateway/audit/verify' && method === 'GET') {
    const authErr = await requireAdmin(); if (authErr) { res.writeHead(authErr.status, gateway.corsHeaders(req)); return res.end(JSON.stringify(authErr.error)); }
    const result = await gateway.verifyAuditIntegrity();
    res.writeHead(result.valid ? 200 : 409, gateway.corsHeaders(req));
    return res.end(JSON.stringify(result, null, 2));
  }

  if (url.startsWith('/gateway/key/rotate/') && method === 'POST') {
    const authErr = await requireAdmin(); if (authErr) { res.writeHead(authErr.status, gateway.corsHeaders(req)); return res.end(JSON.stringify(authErr.error)); }
    const keyId = url.slice('/gateway/key/rotate/'.length);
    const result = gateway.rotateKey(keyId);
    res.writeHead(result.rotated ? 200 : 404, gateway.corsHeaders(req));
    return res.end(JSON.stringify(result, null, 2));
  }

  if (url === '/gateway/pii/scan' && method === 'POST') {
    // Require admin auth when enforcement is on
    if (process.env.GRID_ENFORCE_AUTH === 'true') {
      const p = await gateway.enforce(req, 'admin');
      if (!p.allowed) {
        res.writeHead(p.status, gateway.corsHeaders(req));
        return res.end(JSON.stringify(p.error, null, 2));
      }
    }
    let body = '';
    req.on('data', c => body += c);
    req.on('end', () => {
      try {
        const parsed = JSON.parse(body);
        const content = parsed.content || '';
        const result = scanPII(content);
        res.writeHead(200, gateway.corsHeaders(req));
        return res.end(JSON.stringify(result, null, 2));
      } catch (e) {
        res.writeHead(400, gateway.corsHeaders(req));
        return res.end(JSON.stringify({ error: e.message }));
      }
    });
    return;
  }

  // ENTERPRISE PIPELINE: authenticate + authorize every request
  if (process.env.GRID_ENFORCE_AUTH === 'true') {
    // Skip gateway endpoints (they require admin but are handled above)
    if (!url.startsWith('/gateway/')) {
      const pipeline = await gateway.enforce(req);
      if (!pipeline.allowed) {
        const cors = gateway.corsHeaders(req);
        res.writeHead(pipeline.status, cors);
        return res.end(JSON.stringify(pipeline.error, null, 2));
      }
      // Propagate derived workspace from gateway into request context
      if (pipeline.auth && pipeline.auth.workspace) {
        req.workspace = pipeline.auth.workspace;
      }
    }
  }

  const query = parseQuery(req.url);

  try {
    // GET /health
    if (method === 'GET' && url === '/health') {
      const info = await grid.info();
      return json(res, {
        status: 'ok',
        store: {
          total_entries: info.total_entries,
          alive_entries: info.alive_entries,
          store_size_kb: info.store_size_kb
        },
        version: '1.0.0'
      });
    }

    // GET /info
    if (method === 'GET' && url === '/info') {
      const info = await grid.info();
      return json(res, info);
    }

    // POST /query (complex queries with JSON body, avoids URL length limits)
    if (method === 'POST' && url === '/query') {
      const body = await parseBody(req);
      const workspace = getWorkspace(req);
      const queryTags = body.tags || [];

      // Enforce workspace isolation on POST /query
      if (workspace && !queryTags.includes(`ws:${workspace}`)) {
        queryTags.push(`ws:${workspace}`);
      }

      const result = await grid.read({
        tags: queryTags,
        agents: body.agents || [],
        type: body.type || null,
        types: body.types || [],
        max: body.max || undefined,
        since: body.since || null,
        before: body.before || null,
        tagMode: body.tagMode || 'AND',  // AND mode ensures workspace isolation
        parent_entry: body.parent_entry || null
      });
      return json(res, result);
    }

    // POST /write
    if (method === 'POST' && url === '/write') {
      const body = await parseBody(req);
      if (!body.agent_id) return error(res, 'agent_id is required');
      if (!body.content) return error(res, 'content is required');
      if (body.type && !['decision','fact','task_status','artifact_ref','handoff','question','observation','blocker','state_update'].includes(body.type)) {
        return error(res, `Invalid type "${body.type}". Valid types: decision, fact, task_status, artifact_ref, handoff, question, observation, blocker, state_update`);
      }

      logAudit('write', 'allowed', 'POST', url, getWorkspace(req), body.agent_id || '', '', body.content ? body.content.slice(0, 80) : '');

      // Move tags declaration before any feature that references it (fixes TDZ bug)
      const tags = body.tags || [];
      const workspace = getWorkspace(req);

      // Memory Contracts: validate against registered schemas
      if (contracts.listContracts().length > 0) {
        const contractResult = contracts.validate(tags, body.content || '');
        if (!contractResult.valid && contractResult.blocked) {
          return error(res, `Contract validation failed: ${contractResult.errors.map(e => e.error).join('; ')}`, 400, 'CONTRACT_VIOLATION');
        }
      }

      // Constitutional Memory: validate against workspace constitution
      if (workspace) {
        const entryToValidate = { type: body.type || 'observation', content: body.content || '' };
        const constResult = constitution.validateEntry(entryToValidate, workspace);
        if (constResult.blocked) {
          logAudit('constitution_blocked', 'blocked', 'POST', url, workspace, body.agent_id || '', '', constResult.errors.map(e => e.error).join('; '));
          return error(res, `Constitution validation failed: ${constResult.errors.map(e => e.error).join('; ')}`, 400, 'CONSTITUTION_VIOLATION');
        }
      }

      // Semantic dedup audit (when enabled)
      if (process.env.GRID_DEDUP_ENABLED === 'true') {
        const dedup = require('./deduplication.js');
        const dupResult = await dedup.findDuplicate(grid, body.content || '', tags, body.agent_id, workspace);
        if (dupResult.isDuplicate) {
          await dedup.confirmEntry(grid, dupResult.existingEntry.id, body.agent_id, workspace);
          logAudit('dedup_confirmed', 'allowed', 'POST', url, workspace, body.agent_id || '', dupResult.existingEntry.id || '', 'Duplicate suppressed: similarity=' + dupResult.similarity);
          // Return the existing entry instead of creating a new one
          return json(res, {
            entry_id: dupResult.existingEntry.id,
            duplicated: true,
            similarity: dupResult.similarity,
            original_agent: dupResult.existingEntry.agent_id,
            original_created: dupResult.existingEntry.created_at,
          });
        }
      }

      // Conflict detection (when enabled — writes CONFLICT entry if found, non-blocking)
      if (process.env.GRID_CONFLICT_ENABLED === 'true' && tags.length > 0 && body.content) {
        const conflictResult = await conflicts.findConflicts(grid, body.content || '', tags, body.agent_id, workspace);
        if (conflictResult.hasConflict) {
          await conflicts.resolveConflict(grid, conflictResult, body.content || '', body.agent_id, workspace);
          logAudit('conflict_detected', 'allowed', 'POST', url, workspace, body.agent_id || '', conflictResult.existing_entry || '', 'Conflict resolved: ' + (conflictResult.existing_agent || 'unknown'));
        }
      }

      // PII/PHI check on content (when enforcement is enabled)
      const piiMode = process.env.GRID_PII_MODE || 'off';
      if (piiMode !== 'off') {
        const piiResult = scanPII(body.content || '');
        if (piiResult.hasPII) {
          if (piiMode === 'block') {
            logAudit('pii_blocked', 'blocked', 'POST', url, workspace, '', '', 'PII detected: ' + piiResult.findings.map(f => f.type).join(', '));
            return error(res, `Write blocked by PII policy: ${piiResult.findings.map(f => f.type).join(', ')}`, 400, 'PII_BLOCKED');
          }
          if (piiMode === 'redact') {
            // Auto-redact PII from content
            body.content = piiResult.redacted;
          }
        }
      }

      // Add workspace tag for isolation
      if (workspace && !tags.includes(`ws:${workspace}`)) {
        tags.push(`ws:${workspace}`);
      }

      // Generate embedding for semantic search (optional)
      let embedding = null;
      if (body.content && process.env.GRID_EMBEDDING_API_KEY) {
        try {
          const { embed } = require('./embeddings.js');
          embedding = await embed(body.content).catch(() => null);
        } catch (e) {
          // Embedding unavailable — falls back to tag matching
        }
      }

      const result = await grid.write({
        agent_id: body.agent_id,
        type: body.type || 'observation',
        tags: tags,
        content: body.content,
        embedding: embedding,
        ttl_seconds: body.ttl_seconds,
        session_id: body.session_id,
        parent_entry: body.parent_entry,
        status: body.status || 'active',
        outcome: body.outcome || null,
        requires_approval: body.requires_approval || null,
        origin_trust: body.origin_trust || 'native',
        workspace_id: workspace
      });

      // Cascade: track propagation if parent_entry is set
      if (body.parent_entry) {
        cascade.trackPropagation(grid, body.parent_entry, result.entry_id, workspace);
      }

      // Publish to live subscribers (pass workspace for workspace-scoped subscriptions)
      subscriptions.publish(result, { workspace });
      return json(res, result, 201);
    }

    // GET /query
    if (method === 'GET' && url === '/query') {
      const workspace = getWorkspace(req);
      const queryTags = query.tags ? query.tags.split(',').filter(Boolean) : [];
      const queryText = query.q || null;  // semantic search query

      // Auto-filter by workspace when header is present
      if (workspace && !queryTags.includes(`ws:${workspace}`)) {
        queryTags.push(`ws:${workspace}`);
      }

      // Use AND mode when workspace filtering is active (enforces isolation)
      const hasWorkspace = queryTags.some(t => t.startsWith('ws:'));
      const result = await grid.read({
        tags: queryTags,
        agents: query.agents ? query.agents.split(',').filter(Boolean) : [],
        type: query.type || null,
        types: query.types ? query.types.split(',').filter(Boolean) : [],
        max: query.max ? parseInt(query.max, 10) : undefined,
        since: query.since || null,
        before: query.before || null,
        tagMode: hasWorkspace ? 'AND' : (query.tagMode || 'OR'),
        q: queryText,
      });
      return json(res, result);
    }

    // POST /inject
    if (method === 'POST' && url === '/inject') {
      logAudit('inject', 'allowed', 'POST', url, getWorkspace(req), '', '', '');
      const body = await parseBody(req);
      const workspace = getWorkspace(req);
      let result;
      if (workspace) {
        const wsQuery = await grid.read({ tags: [`ws:${workspace}`], max: 50, tagMode: 'AND' });
        const entries = wsQuery.entries || [];
        const lines = [`\u2500\u2500\u2500 SHARED MEMORY GRID \u2500\u2500\u2500\n`];
        lines.push(`Recent entries (workspace: ${workspace}):\n`);
        for (const e of entries.slice(0, 15)) {
          lines.push(`[${e.type || 'observation'}] agent:${e.agent_id || '?'} \u2014 ${(e.content || '').slice(0, 200)}\n`);
        }
        lines.push(`\n\u2500\u2500\u2500 END GRID \u2500\u2500\u2500`);
        result = { block: lines.join('\n'), entry_count: entries.length, bytes: Buffer.byteLength(lines.join('\n'), 'utf-8') };
      } else {
        result = await grid.inject(body.context || '');
      }
      return json(res, result);
    }

    // GET /inject (workspace-scoped when header present)
    if (method === 'GET' && url === '/inject') {
      const workspace = getWorkspace(req);
      let result;
      if (workspace) {
        const wsQuery = await grid.read({ tags: [`ws:${workspace}`], max: 50, tagMode: 'AND' });
        const entries = wsQuery.entries || [];
        const lines = [`\u2500\u2500\u2500 SHARED MEMORY GRID \u2500\u2500\u2500\n`];
        lines.push(`Recent entries (workspace: ${workspace}):\n`);
        for (const e of entries.slice(0, 15)) {
          lines.push(`[${e.type || 'observation'}] agent:${e.agent_id || '?'} \u2014 ${(e.content || '').slice(0, 200)}\n`);
        }
        lines.push(`\n\u2500\u2500\u2500 END GRID \u2500\u2500\u2500`);
        result = { block: lines.join('\n'), entry_count: entries.length, bytes: Buffer.byteLength(lines.join('\n'), 'utf-8') };
      } else {
        result = await grid.inject(query.context || '');
      }
      return json(res, result);
    }

    // POST /prune
    if (method === 'POST' && url === '/prune') {
      logAudit('prune', 'allowed', 'POST', url, getWorkspace(req), '', '', '');
      const result = await grid.prune();
      return json(res, result);
    }

    // DELETE /forget/:id
    if (method === 'DELETE' && url.startsWith('/forget/')) {
      logAudit('delete', 'allowed', 'DELETE', url, getWorkspace(req), '', '', '');
      const id = url.slice(8); // '/forget/'.length
      if (!id) return error(res, 'Entry ID is required');
      if (process.env.GRID_ENFORCE_AUTH === 'true') {
        const p = await gateway.enforce(req, 'admin');
        if (!p.allowed) { res.writeHead(p.status, gateway.corsHeaders(req)); return res.end(JSON.stringify(p.error)); }
      }
      // Workspace isolation: verify entry belongs to caller's workspace
      const ws = getWorkspace(req);
      if (ws) {
        const lookup = await grid.read({ entry_id: id });
        const found = lookup.entries || [];
        if (found.length === 0) return error(res, 'Entry not found', 404);
        const entryWs = (found[0].tags || []).filter(t => t.startsWith('ws:'));
        // Only enforce workspace check if entry HAS workspace tags (global entries are cross-workspace)
        if (entryWs.length > 0 && !entryWs.includes('ws:' + ws)) {
          return error(res, 'Entry does not belong to this workspace', 403, 'WORKSPACE_MISMATCH');
        }
      }
      const result = await grid.forget(id);
      if (!result.found) return error(res, result.message, 404, 'NOT_FOUND');
      return json(res, result);
    }



    if (method === 'POST' && url.startsWith('/drafts/') && url.endsWith('/approve')) {
      const id = url.slice('/drafts/'.length, -'/approve'.length);
      if (!id) return error(res, 'Entry ID is required');
      const authErr = await requireAdmin(); if (authErr) { res.writeHead(authErr.status, gateway.corsHeaders(req)); return res.end(JSON.stringify(authErr.error)); }
      logAudit('draft_approve', 'allowed', 'POST', url, getWorkspace(req), '', id, '');
      const result = await grid.promoteEntry(id);
      if (!result.found) return error(res, result.message, 404, 'NOT_FOUND');
      return json(res, result);
    }

    // ── Feature 4: Grid Dreaming ──
    if (method === 'POST' && url === '/dream') {
      const authErr = await requireAdmin(); if (authErr) { res.writeHead(authErr.status, gateway.corsHeaders(req)); return res.end(JSON.stringify(authErr.error)); }
      logAudit('dream', 'allowed', 'POST', url, getWorkspace(req), '', '', '');
      const body = await parseBody(req);
      const result = await dreaming.runDreamCycle(grid, {
        ttlMultiplier: body.ttlMultiplier || 2,
      });
      return json(res, result);
    }

    // ── Feature 5: Provenance Shield ──
    if (method === 'GET' && url.startsWith('/provenance/')) {
      const id = url.slice('/provenance/'.length);
      if (!id) return error(res, 'Entry ID is required');
      logAudit('provenance', 'allowed', 'GET', url, getWorkspace(req), '', id, '');
      const result = provenance.scoreProvenance(grid, id);
      if (!result) return error(res, 'Entry not found', 404, 'NOT_FOUND');
      return json(res, result);
    }

    if (method === 'POST' && url.startsWith('/quarantine/')) {
      const id = url.slice('/quarantine/'.length);
      if (!id) return error(res, 'Entry ID is required');
      const authErr = await requireAdmin(); if (authErr) { res.writeHead(authErr.status, gateway.corsHeaders(req)); return res.end(JSON.stringify(authErr.error)); }
      const body = await parseBody(req);
      logAudit('quarantine', 'allowed', 'POST', url, getWorkspace(req), '', id, body.reason || '');
      const result = await provenance.quarantineEntry(grid, id, body.reason || '');
      return json(res, result);
    }

    // Quarantine review endpoint
    if (method === 'POST' && url.startsWith('/quarantine/review/')) {
      const id = url.slice('/quarantine/review/'.length);
      if (!id) return error(res, 'Entry ID is required');
      const authErr = await requireAdmin(); if (authErr) { res.writeHead(authErr.status, gateway.corsHeaders(req)); return res.end(JSON.stringify(authErr.error)); }
      const body = await parseBody(req);
      if (!body.decision || !['approve', 'reject'].includes(body.decision)) return error(res, 'decision must be "approve" or "reject"', 400);
      logAudit('quarantine_review', 'allowed', 'POST', url, getWorkspace(req), '', id, body.decision);
      const result = await provenance.reviewEntry(grid, id, body.decision);
      return json(res, result);
    }

    // ── Feature 6: Cascade Firewall ──
    if (method === 'GET' && url.startsWith('/cascade/')) {
      const id = url.slice('/cascade/'.length);
      if (!id) return error(res, 'Entry ID is required');
      logAudit('cascade', 'allowed', 'GET', url, getWorkspace(req), '', id, '');
      const result = cascade.getCascade(grid, id);
      return json(res, result);
    }

    if (method === 'POST' && url.startsWith('/recall/')) {
      const id = url.slice('/recall/'.length);
      if (!id) return error(res, 'Entry ID is required');
      const authErr = await requireAdmin(); if (authErr) { res.writeHead(authErr.status, gateway.corsHeaders(req)); return res.end(JSON.stringify(authErr.error)); }
      const body = await parseBody(req);
      logAudit('recall', 'allowed', 'POST', url, getWorkspace(req), '', id, body.reason || '');
      const result = await cascade.recallEntry(grid, id, body.reason || '');
      return json(res, result);
    }

    // ── Feature 7: Constitutional Memory ──

    // Natural-language constitution generation
    if (method === 'POST' && url === '/constitution/from-text') {
      if (process.env.GRID_ENFORCE_AUTH === 'true') {
        const p = await gateway.enforce(req, 'admin');
        if (!p.allowed) { res.writeHead(p.status, gateway.corsHeaders(req)); return res.end(JSON.stringify(p.error)); }
      }
      const ws = getWorkspace(req) || 'default';
      const body = await parseBody(req);
      if (!body.text) return error(res, 'text is required', 400);
      logAudit('constitution_from_text', 'allowed', 'POST', url, ws, '', '', body.text.slice(0, 80));
      try {
        const generated = constitution.generateFromNaturalLanguage(body.text, body.enforceMode || 'block');
        // Register the generated constitution against the workspace
        if (generated.rules.length > 0) {
          const registered = constitution.registerConstitution(ws, generated.rules, generated.enforceMode);
          return json(res, { generated, registered });
        }
        return json(res, { generated, message: 'No rules could be generated from the provided text.' });
      } catch (e) { return error(res, e.message, 400); }
    }

    if (url === '/constitution' && method === 'POST') {
      const authErr = await requireAdmin(); if (authErr) { res.writeHead(authErr.status, gateway.corsHeaders(req)); return res.end(JSON.stringify(authErr.error)); }
      const body = await parseBody(req);
      const ws = getWorkspace(req);
      if (!ws) return error(res, 'X-Grid-Workspace header is required', 400);
      logAudit('constitution_register', 'allowed', 'POST', url, ws, '', '', JSON.stringify(body.rules ? body.rules.length + ' rules' : ''));
      try {
        const result = constitution.registerConstitution(ws, body.rules || [], body.enforceMode || 'validate');
        return json(res, result);
      } catch (e) { return error(res, e.message, 400); }
    }

    if (url === '/constitution' && method === 'GET') {
      logAudit('constitution_list', 'allowed', 'GET', url, getWorkspace(req), '', '', '');
      const ws = getWorkspace(req);
      const result = constitution.listConstitutions(ws || undefined);
      return json(res, result);
    }

    if (url === '/constitution' && method === 'DELETE') {
      const authErr = await requireAdmin(); if (authErr) { res.writeHead(authErr.status, gateway.corsHeaders(req)); return res.end(JSON.stringify(authErr.error)); }
      const ws = getWorkspace(req);
      if (!ws) return error(res, 'X-Grid-Workspace header is required', 400);
      logAudit('constitution_remove', 'allowed', 'DELETE', url, ws, '', '', '');
      const result = constitution.removeConstitution(ws);
      return json(res, result);
    }

    // Also wire constitution check into write handler (done at write time)

    // ── Feature 8: Cross-Grid Federation ──
    if (url === '/federation/peers' && method === 'POST') {
      const authErr = await requireAdmin(); if (authErr) { res.writeHead(authErr.status, gateway.corsHeaders(req)); return res.end(JSON.stringify(authErr.error)); }
      const body = await parseBody(req);
      if (!body.url) return error(res, 'Peer URL is required');
      logAudit('federation_peer_add', 'allowed', 'POST', url, '', '', '', body.url);
      try {
        const result = federation.registerPeer(body.url, body.trustLevel || 'unverified', body.sharedSecret || null);
        return json(res, result);
      } catch (e) { return error(res, e.message, 400); }
    }

    if (url === '/federation/peers' && method === 'GET') {
      if (!endpointLimiter(req)) return error(res, 'Rate limit exceeded for /federation. Max 20/min.', 429, 'RATE_LIMITED');
      if (process.env.GRID_ENFORCE_AUTH === 'true') {
        const p = await gateway.enforce(req, 'analyst');
        if (!p.allowed) { res.writeHead(p.status, gateway.corsHeaders(req)); return res.end(JSON.stringify(p.error)); }
      }
      logAudit('federation_peers_list', 'allowed', 'GET', url, '', '', '', '');
      const peers = federation.listPeers();
      return json(res, { peers });
    }

    if (url.startsWith('/federation/peers/') && method === 'DELETE') {
      const authErr = await requireAdmin(); if (authErr) { res.writeHead(authErr.status, gateway.corsHeaders(req)); return res.end(JSON.stringify(authErr.error)); }
      const encodedUrl = url.slice('/federation/peers/'.length);
      const peerUrl = decodeURIComponent(encodedUrl);
      logAudit('federation_peer_remove', 'allowed', 'DELETE', url, '', '', '', peerUrl);
      const result = federation.removePeer(peerUrl);
      return json(res, result);
    }

    if (url.startsWith('/federation/sync/') && method === 'POST') {
      const authErr = await requireAdmin(); if (authErr) { res.writeHead(authErr.status, gateway.corsHeaders(req)); return res.end(JSON.stringify(authErr.error)); }
      // Capture raw body for signature validation
      let fedRawBody = '';
      req.on('data', c => fedRawBody += c);
      await new Promise(resolve => req.on('end', resolve));
      // Validate incoming request signature when provided
      const sigCheck = federation.validateIncomingRequest(req, fedRawBody);
      if (!sigCheck.valid && req.headers['x-grid-signature']) {
        return error(res, 'Invalid federation signature: ' + sigCheck.reason, 401, 'FED_SIGNATURE_INVALID');
      }
      const encodedUrl = url.slice('/federation/sync/'.length);
      const peerUrl = decodeURIComponent(encodedUrl);
      logAudit('federation_sync', 'allowed', 'POST', url, '', '', '', peerUrl);
      const result = await federation.syncFromPeer(grid, peerUrl);
      return json(res, result);
    }

    // ── Feature 9: Explainability Transcript ──
    if (method === 'GET' && url.startsWith('/explain/')) {
      const id = url.slice('/explain/'.length);
      if (!id) return error(res, 'Entry ID is required');
      logAudit('explain', 'allowed', 'GET', url, getWorkspace(req), '', id, '');
      const format = query.format || 'narrative';
      if (!['narrative', 'json', 'markdown'].includes(format)) return error(res, 'Format must be narrative, json, or markdown');
      const result = await explain.generateTranscript(grid, id, { format });
      return json(res, result);
    }

    // ── Seed Mode ──


    // ── Quick-Connect Federation ──
    if (method === 'POST' && url === '/federation/quick-connect') {
      if (process.env.GRID_ENFORCE_AUTH === 'true') {
        const p = await gateway.enforce(req, 'admin');
        if (!p.allowed) { res.writeHead(p.status, gateway.corsHeaders(req)); return res.end(JSON.stringify(p.error)); }
      }
      const body = await parseBody(req);
      if (!body.peerUrl) return error(res, 'peerUrl is required');
      logAudit('federation_quick_connect', 'allowed', 'POST', url, '', '', '', body.peerUrl);
      try {
        const result = await federation.quickConnect(body.peerUrl, body.options || {});
        return json(res, result);
      } catch (e) { return error(res, e.message, 400); }
    }

    // ── Auto-Contract Suggestions ──
    if (method === 'GET' && url === '/auto-contracts') {
      if (process.env.GRID_ENFORCE_AUTH === 'true') {
        const p = await gateway.enforce(req, 'viewer');
        if (!p.allowed) { res.writeHead(p.status, gateway.corsHeaders(req)); return res.end(JSON.stringify(p.error)); }
      }
      logAudit('auto_contracts', 'allowed', 'GET', url, '', '', '', '');
      const result = await autoContract.suggestContracts(grid);
      return json(res, result);
    }

    // ── Auto-Contract Approval ──
    if (method === 'POST' && url === '/auto-contracts/approve') {
      if (process.env.GRID_ENFORCE_AUTH === 'true') {
        const p = await gateway.enforce(req, 'admin');
        if (!p.allowed) { res.writeHead(p.status, gateway.corsHeaders(req)); return res.end(JSON.stringify(p.error)); }
      }
      const body = await parseBody(req);
      if (!body.scope || !body.suggested_schema) {
        return error(res, 'scope and suggested_schema are required');
      }
      logAudit('auto_contract_approve', 'allowed', 'POST', url, '', '', '', body.scope);
      try {
        const result = autoContract.approveContract(body);
        return json(res, result);
      } catch (e) { return error(res, e.message, 400); }
    }

    if (method === 'POST' && url === '/auto-contracts/reject') {
      if (process.env.GRID_ENFORCE_AUTH === 'true') {
        const p = await gateway.enforce(req, 'admin');
        if (!p.allowed) { res.writeHead(p.status, gateway.corsHeaders(req)); return res.end(JSON.stringify(p.error)); }
      }
      const body = await parseBody(req);
      if (!body.scope) return error(res, 'scope is required');
      logAudit('auto_contract_reject', 'allowed', 'POST', url, '', '', '', body.scope);
      try {
        const result = autoContract.rejectContract(body.scope);
        return json(res, result);
      } catch (e) { return error(res, e.message, 400); }
    }

    if (method === 'GET' && url === '/auto-contracts/state') {
      logAudit('auto_contract_state', 'allowed', 'GET', url, '', '', '', '');
      const result = autoContract.getApprovalState();
      return json(res, result);
    }

    error(res, 'Not found: ' + method + ' ' + url, 404, 'NOT_FOUND');

  } catch (err) {
    console.error(`[Grid Server] Error: ${err.message}`);
    error(res, err.message, 500, 'INTERNAL_ERROR');
  }
}

// ─── Quick Actions Generator ─────────────────────────────────────────────────────

function _generateQuickActions(dashboardResult, amnesiaResult) {
  const actions = [];

  // Check if seed is needed (empty dashboard)
  if (dashboardResult.status === 'fulfilled' && dashboardResult.value.summary && dashboardResult.value.summary.total_entries === 0) {
    actions.push({ action: 'seed', label: 'Seed the Grid with demo data', endpoint: 'POST /seed', priority: 'high' });
    actions.push({ action: 'setup', label: 'Run setup wizard', endpoint: 'POST /setup-wizard', priority: 'high' });
  }

  // Check for unconfigured contracts
  if (dashboardResult.status === 'fulfilled' && dashboardResult.value.opportunities && dashboardResult.value.opportunities.total === 0) {
    actions.push({ action: 'contracts', label: 'Configure memory contracts', endpoint: 'POST /contracts', priority: 'medium' });
  }

  // Check amnesia issues
  if (amnesiaResult.status === 'fulfilled') {
    const a = amnesiaResult.value;
    if (a.amnesia_score > 0.3) {
      actions.push({ action: 'review_gaps', label: `${a.gaps.length} knowledge gaps detected — review`, endpoint: 'GET /amnesia/detect', priority: a.amnesia_score > 0.6 ? 'high' : 'medium' });
    }
    if (a.orphans.length > 5) {
      actions.push({ action: 'review_orphans', label: `${a.orphans.length} decisions never acted upon`, endpoint: 'GET /amnesia/detect', priority: 'medium' });
    }
    if (a.single_points_of_failure.length > 0) {
      actions.push({ action: 'reduce_spof', label: `${a.single_points_of_failure.length} knowledge single-points-of-failure`, endpoint: 'GET /amnesia/detect', priority: 'high' });
    }
  }

  return actions;
}

// ─── Start ─────────────────────────────────────────────────────────────────────

// Share grid instance with the OpenAI proxy
openaiProxy.setGrid(grid);

const server = http.createServer(handle);

server.listen(PORT, HOST, () => {
  if (process.env.GRID_SEED_MODE !== 'false') {
    seedMode.seedGrid(grid).then(r => {
      if (r.seeded) console.log('🌱 Seed mode (auto): ' + r.entry_count + ' entries from ' + r.agent_count + ' agents');
      else if (!r.reason) console.log('🌱 Seed mode: auto-seed ran, result=' + JSON.stringify(r));
    }).catch(e => console.error('Seed failed:', e.message));
  }
  console.log(`═══ Grid Memory Server ═══`);
  console.log(`Listening on http://${HOST}:${PORT}`);
  console.log(`Endpoints:`);
  console.log(`  POST /write           — Write an entry`);
  console.log(`  GET|POST /query       — Query entries`);
  console.log(`  GET|POST /inject      — Get context injection block`);
  console.log(`  POST /prune           — Remove expired entries`);
  console.log(`  GET  /info            — Store stats`);
  console.log(`  DELETE /forget/       — Remove a specific entry`);
  console.log(`  GET  /health          — Health check`);
  console.log(`  GET  /v1/models       — List models (OpenAI-compat)`);
  console.log(`  POST /v1/chat/completions — Chat completions (OpenAI-compat)`);
  console.log(`Business:`);
  console.log(`  GET  /roi               — Instant ROI insights`);
  console.log(`  GET  /mike/dashboard    — MIKE operations dashboard`);
  console.log(`  GET  /executive/dashboard — Executive overview`);
  console.log(`  GET  /decisions/graph   — Decision graph`);
  console.log(`  GET  /decisions/stats   — Decision analytics`);
  console.log(`  GET  /qbr               — QBR report (use ?period=Q1-2026)`);
  console.log(`  POST /qbr/generate      — Generate QBR report`);
  console.log(`  GET  /amnesia/detect    — Organizational amnesia scan`);
  console.log(`Federation:`);
  console.log(`  POST /federation/quick-connect — One-click peer connect`);
  console.log(`Setup:`);
  console.log(`  POST /setup-wizard      — Guided configuration`);
  console.log(`  POST /constitution/from-text — NL policy → constitution`);
  console.log(`  GET  /auto-contracts    — Auto-contract suggestions`);
  console.log(`  POST /auto-contracts/approve — Approve a contract suggestion`);
  console.log(`  POST /auto-contracts/reject  — Reject a contract suggestion`);
  if (process.env.GRID_UPSTREAM_API_KEY) {
    const keyPreview = process.env.GRID_UPSTREAM_API_KEY.slice(0, 4) + '...' + process.env.GRID_UPSTREAM_API_KEY.slice(-4);
    console.log(`Upstream: ${process.env.GRID_UPSTREAM_URL || 'https://api.openai.com'} (key: ${keyPreview})`);
  } else {
    console.log(`Upstream: NOT CONFIGURED — set GRID_UPSTREAM_API_KEY. Returns debug responses.`);
  }
  console.log(`Data dir: ${process.env.GRID_STORE_DIR || '(default)'}`);
  console.log(`═══════════════════════════════`);
});

