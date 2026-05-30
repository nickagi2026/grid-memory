/**
 * federation.js — Cross-Grid Federation with Trust Scores + Request Signing
 *
 * Registers peer Grid instances, syncs entries between them,
 * and tracks trust levels for entries sourced from peers.
 *
 * Cryptographic hardening:
 * - Peers register with a shared secret
 * - Outgoing sync requests include HMAC-SHA256 signature header
 * - Server validates incoming X-Grid-Signature against peer's shared secret
 * - Trust level determines signature requirements (verified=required, unverified=optional)
 */

const fs = require('fs');
const path = require('path');
const http = require('http');
const https = require('https');
const crypto = require('crypto');
const govDb = require('./governance-db.js');

const PEERS_FILE = 'peers.json';

function getFedDir() {
  return process.env.GRID_STORE_DIR || path.join(
    process.env.HOME || process.env.USERPROFILE || '/tmp',
    '.openclaw', 'grid'
  );
}

function peersPath() {
  return path.join(getFedDir(), PEERS_FILE);
}

function _ensureDir() {
  const dir = getFedDir();
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
}

function _loadPeers() {
  // PRIMARY: governance-db (SQLite). LEGACY FALLBACK: JSON file.

  // Try SQLite first
  try {
    const rows = govDb.getPeers();
    if (rows && rows.length > 0) {
      return { peers: rows.map(r => ({
        url: r.url,
        trustLevel: r.trust_level,
        trustScore: r.trust_score,
        sharedSecret: r.shared_secret,
        registered_at: r.registered_at,
        updated_at: r.updated_at,
        last_synced_at: r.last_synced_at,
      })) };
    }
  } catch (e) { /* fall through */ }

  _ensureDir();
  try {
    if (fs.existsSync(peersPath())) {
      return JSON.parse(fs.readFileSync(peersPath(), 'utf-8'));
    }
  } catch (e) { /* ignore */ }
  return { peers: [] };
}

function _savePeers(data) {
  // Try SQLite first
  if (govDb.isAvailable()) {
    try {
      for (const peer of data.peers) {
        govDb.savePeer(peer.url, peer);
      }
      return;
    } catch (e) { /* fall through */ }
  }

  _ensureDir();
  fs.writeFileSync(peersPath(), JSON.stringify(data, null, 2), 'utf-8');
}

/**
 * Compute HMAC-SHA256 signature for a request body + timestamp
 */
function signRequest(body, secret) {
  const timestamp = Math.floor(Date.now() / 1000).toString();
  const payload = timestamp + '.' + (typeof body === 'string' ? body : JSON.stringify(body));
  const hmac = crypto.createHmac('sha256', secret).update(payload).digest('hex');
  return { signature: hmac, timestamp };
}

/**
 * Verify an incoming HMAC signature.
 * Returns { valid: true } if the signature matches the peer's shared secret.
 */
function verifyRequestSignature(body, signature, timestamp, peerSecret) {
  if (!peerSecret || !signature || !timestamp) return { valid: false, reason: 'Missing signature data' };
  const payload = timestamp + '.' + (typeof body === 'string' ? body : JSON.stringify(body));
  const expected = crypto.createHmac('sha256', peerSecret).update(payload).digest('hex');
  // Constant-time comparison to prevent timing attacks
  if (expected.length !== signature.length) return { valid: false, reason: 'Signature length mismatch' };
  let match = true;
  for (let i = 0; i < expected.length; i++) {
    if (expected[i] !== signature[i]) match = false;
  }
  if (!match) return { valid: false, reason: 'Signature mismatch' };
  // Reject signatures older than 5 minutes
  const now = Math.floor(Date.now() / 1000);
  if (now - parseInt(timestamp, 10) > 300) return { valid: false, reason: 'Signature expired' };
  return { valid: true };
}

function registerPeer(url, trustLevel = 'unverified', sharedSecret) {
  if (!['verified', 'unverified', 'quarantine'].includes(trustLevel)) {
    throw new Error('trustLevel must be verified, unverified, or quarantine');
  }

  const data = _loadPeers();
  const existing = data.peers.find(p => p.url === url);
  if (existing) {
    existing.trustLevel = trustLevel;
    if (sharedSecret) existing.sharedSecret = sharedSecret;
    existing.updated_at = new Date().toISOString();
    _savePeers(data);
    return { registered: true, url, trustLevel, updated: true };
  }

  data.peers.push({
    url,
    trustLevel,
    trustScore: trustLevel === 'verified' ? 80 : trustLevel === 'unverified' ? 40 : 10,
    sharedSecret: sharedSecret || null,
    registered_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    last_synced_at: null,
  });
  _savePeers(data);
  return { registered: true, url, trustLevel, updated: false, has_secret: !!sharedSecret };
}

function listPeers() {
  // Return peers without shared secrets (security: don't leak secrets)
  return _loadPeers().peers.map(p => ({
    url: p.url,
    trustLevel: p.trustLevel,
    trustScore: p.trustScore,
    registered_at: p.registered_at,
    updated_at: p.updated_at,
    last_synced_at: p.last_synced_at,
    has_secret: !!p.sharedSecret,
  }));
}

function removePeer(url) {
  const data = _loadPeers();
  const idx = data.peers.findIndex(p => p.url === url);
  if (idx === -1) return { removed: false, message: `Peer ${url} not found` };
  data.peers.splice(idx, 1);
  _savePeers(data);
  // Also delete from governance DB
  try { govDb.deletePeer(url); } catch (e) { /* ignore govDb errors */ }
  return { removed: true, url };
}

function getPeerTrust(url) {
  const data = _loadPeers();
  const peer = data.peers.find(p => p.url === url);
  if (!peer) return { found: false };
  return {
    found: true,
    url,
    trustLevel: peer.trustLevel,
    trustScore: peer.trustScore,
    has_secret: !!peer.sharedSecret,
    last_synced_at: peer.last_synced_at,
  };
}

function getPeerSecret(url) {
  const data = _loadPeers();
  const peer = data.peers.find(p => p.url === url);
  return peer ? (peer.sharedSecret || null) : null;
}

/**
 * Signed HTTP request to a peer. Includes HMAC signature when shared secret is configured.
 */
function _signedRequest(peerUrl, endpoint, body) {
  const fullUrl = peerUrl.replace(/\/$/, '') + endpoint;
  const urlObj = new URL(fullUrl);
  const transport = urlObj.protocol === 'https:' ? https : http;
  const secret = getPeerSecret(peerUrl);

  return new Promise((resolve, reject) => {
    const bodyStr = body ? JSON.stringify(body) : '';
    const headers = { 'Content-Type': 'application/json' };

    // Sign the request if we have a shared secret with this peer
    if (secret) {
      const { signature, timestamp } = signRequest(bodyStr, secret);
      headers['X-Grid-Signature'] = signature;
      headers['X-Grid-Timestamp'] = timestamp;
    }

    const method = body ? 'POST' : 'GET';
    const req = transport.request(fullUrl, {
      method,
      headers: { ...headers, 'Content-Length': Buffer.byteLength(bodyStr) },
      timeout: 10000,
    }, (res) => {
      let data = '';
      res.on('data', c => data += c);
      res.on('end', () => {
        try { resolve(JSON.parse(data)); }
        catch { resolve(null); }
      });
    });
    req.on('error', reject);
    req.on('timeout', () => { req.destroy(); reject(new Error('timeout')); });
    if (bodyStr) req.write(bodyStr);
    req.end();
  });
}

/**
 * Validate incoming request signature against all registered peers.
 * Called by the server's federation sync handler to verify the caller.
 */
function validateIncomingRequest(req, rawBody) {
  const signature = req.headers['x-grid-signature'];
  const timestamp = req.headers['x-grid-timestamp'];
  if (!signature || !timestamp) return { valid: false, reason: 'No signature provided', peer: null };

  const data = _loadPeers();
  for (const peer of data.peers) {
    if (!peer.sharedSecret) continue;
    const body = rawBody !== undefined ? rawBody : '';
    const result = verifyRequestSignature(body, signature, timestamp, peer.sharedSecret);
    if (result.valid) {
      return { valid: true, peer: peer.url, trustLevel: peer.trustLevel };
    }
  }
  return { valid: false, reason: 'No matching peer found for signature', peer: null };
}

/**
 * Make an unsigned GET request to discover peer info.
 */
function _getRequest(url) {
  const urlObj = new URL(url);
  const transport = urlObj.protocol === 'https:' ? https : http;
  return new Promise((resolve, reject) => {
    const req = transport.request(url, { method: 'GET', timeout: 8000 }, (res) => {
      let data = '';
      res.on('data', c => data += c);
      res.on('end', () => {
        try { resolve(JSON.parse(data)); }
        catch { resolve(null); }
      });
    });
    req.on('error', reject);
    req.on('timeout', () => { req.destroy(); reject(new Error('timeout')); });
    req.end();
  });
}

/**
 * One-Click Federation: Quick-connect to a peer.
 *
 * Probes the peer, generates a shared secret, registers both directions.
 *
 * @param {string} peerUrl — URL of the peer Grid (e.g. http://other-grid:8080)
 * @param {Object} [options]
 * @param {string} [options.trustLevel] — trust level to assign ('verified'|'unverified'|'quarantine')
 * @param {string} [options.sharedSecret] — optional pre-shared secret; auto-generated if omitted
 * @returns {Object} connection result
 */
async function quickConnect(peerUrl, options = {}) {
  const baseUrl = peerUrl.replace(/\/+$/, '');
  const results = {
    peerUrl: baseUrl,
    steps: [],
    connected: false,
  };

  // Step 1: Check if peer is reachable via /health
  try {
    const health = await _getRequest(baseUrl + '/health');
    if (!health || health.status !== 'ok') {
      results.steps.push({ step: 'health_check', status: 'failed', detail: 'Peer not healthy' });
      results.error = 'Peer is not reachable or healthy';
      return results;
    }
    results.steps.push({ step: 'health_check', status: 'passed', detail: health.status });
  } catch (e) {
    results.steps.push({ step: 'health_check', status: 'failed', detail: e.message });
    results.error = 'Peer unreachable: ' + e.message;
    return results;
  }

  // Step 2: Get peer info via /info
  let peerInfo = null;
  try {
    peerInfo = await _getRequest(baseUrl + '/info');
    results.steps.push({
      step: 'discover',
      status: 'passed',
      detail: peerInfo ? `Total entries: ${peerInfo.total_entries || '?'}` : 'Info endpoint returned no data',
      peer_info: peerInfo || {},
    });
  } catch (e) {
    results.steps.push({ step: 'discover', status: 'warn', detail: 'Info endpoint unavailable: ' + e.message });
  }

  // Step 3: Generate shared secret
  const sharedSecret = options.sharedSecret || (
    crypto.randomBytes(32).toString('hex')
  );
  results.steps.push({ step: 'secret_generation', status: 'passed', detail: options.sharedSecret ? 'Using provided secret' : 'Auto-generated 64-char hex secret' });

  // Step 4: Determine trust level based on peer response
  let trustLevel = options.trustLevel || 'unverified';
  if (!options.trustLevel) {
    // If peer has signatures, trust is higher
    if (peerInfo && peerInfo.features && peerInfo.features.includes('signed_federation')) {
      trustLevel = 'verified';
    }
    // If peer returned detailed info, it's more credible
    if (peerInfo && peerInfo.total_entries > 0) {
      trustLevel = 'verified';
    }
  }
  results.steps.push({ step: 'trust_evaluation', status: 'passed', detail: 'Trust level: ' + trustLevel });

  // Step 5: Register peer locally
  try {
    const localRegistration = registerPeer(baseUrl, trustLevel, sharedSecret);
    results.steps.push({
      step: 'local_registration',
      status: 'passed',
      detail: localRegistration.updated ? 'Updated existing peer' : 'Registered new peer',
    });
  } catch (e) {
    results.steps.push({ step: 'local_registration', status: 'failed', detail: e.message });
    results.error = 'Local registration failed: ' + e.message;
    return results;
  }

  // Step 6: Register as peer on remote by calling POST /federation/peers
  try {
    // Get our own info so the remote knows who we are
    const remoteRegistration = await _signedRequest(baseUrl, '/federation/peers', {
      url: process.env.GRID_PUBLIC_URL || 'http://localhost:' + (process.env.PORT || 8080),
      trustLevel: 'unverified',
      sharedSecret,
    });
    results.steps.push({
      step: 'remote_registration',
      status: remoteRegistration && remoteRegistration.registered ? 'passed' : 'warn',
      detail: remoteRegistration && remoteRegistration.registered
        ? 'Successfully registered on remote'
        : 'Remote registration may require manual approval: ' + JSON.stringify(remoteRegistration || {}),
    });
  } catch (e) {
    results.steps.push({
      step: 'remote_registration',
      status: 'warn',
      detail: 'Could not register on remote (may need manual setup): ' + e.message,
    });
  }

  results.connected = true;
  results.trustLevel = trustLevel;
  results.has_secret = true;

  return results;
}

async function syncFromPeer(grid, peerUrl, options = {}) {
  const data = _loadPeers();
  const peer = data.peers.find(p => p.url === peerUrl);
  if (!peer) return { synced: false, message: `Peer ${peerUrl} not registered` };

  const trustMap = { verified: 'verified', unverified: 'unverified', quarantine: 'quarantine' };
  const originTrust = trustMap[peer.trustLevel] || 'unverified';

  try {
    const signed = !!peer.sharedSecret;
    const peerData = await _signedRequest(peerUrl, '/export');
    if (!peerData || !peerData.entries) {
      return { synced: false, message: 'Failed to fetch entries from peer', peer: peerUrl, signed };
    }

    let imported = 0;
    let skipped = 0;
    for (const entry of peerData.entries) {
      if (!entry.agent_id || !entry.content) { skipped++; continue; }
      try {
        await grid.write({
          agent_id: entry.agent_id,
          type: entry.type || 'observation',
          tags: [...(entry.tags || []), 'federated', `federated_from:${peerUrl.replace(/[^a-zA-Z0-9]/g, '_')}`],
          content: `[federated${signed ? '+signed' : ''}:${peerUrl}] ${entry.content}`,
          ttl_seconds: entry.ttl_seconds,
          session_id: entry.session_id || '',
          parent_entry: null,
          origin_trust: originTrust,
        });
        imported++;
      } catch (e) { skipped++; }
    }

    peer.last_synced_at = new Date().toISOString();
    _savePeers(data);

    return {
      synced: true,
      peer: peerUrl,
      imported,
      skipped,
      total_available: peerData.entry_count || (peerData.entries || []).length,
      origin_trust: originTrust,
      signed,
    };
  } catch (err) {
    return { synced: false, message: `Sync failed: ${err.message}`, peer: peerUrl };
  }
}

module.exports = {
  registerPeer, listPeers, removePeer, getPeerTrust, getPeerSecret,
  syncFromPeer, signRequest, verifyRequestSignature, validateIncomingRequest,
  quickConnect,
};
