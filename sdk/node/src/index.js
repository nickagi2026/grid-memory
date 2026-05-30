/**
 * grid-memory — Node.js SDK for the Grid Memory Server
 *
 * Usage:
 *   const { Grid } = require('grid-memory');
 *
 *   const grid = new Grid('http://localhost:8080');
 *
 *   // Write
 *   await grid.fact('PostgreSQL pool: 25', { tags: ['database'] });
 *   await grid.decide('Use Express', { rationale: 'Ecosystem maturity', tags: ['arch'] });
 *   await grid.handoff({ from: 'researcher', to: 'builder', content: 'API spec ready', status: 'ready' });
 *
 *   // Read
 *   const { entries } = await grid.query({ tags: ['database'] });
 *   const block = await grid.inject('building the API');
 *
 *   // Admin
 *   const info = await grid.info();
 *   await grid.prune();
 */

const http = require('http');
const https = require('https');

// ─── Error types ──────────────────────────────────────────────────────────────

class GridError extends Error {
  constructor(message, statusCode) {
    super(message);
    this.name = 'GridError';
    this.statusCode = statusCode;
  }
}

// ─── HTTP helpers ─────────────────────────────────────────────────────────────

 function request(method, url, body = null, timeout = 10000) {
  return new Promise((resolve, reject) => {
    const urlObj = new URL(url);
    const transport = urlObj.protocol === 'https:' ? https : http;

    const options = {
      hostname: urlObj.hostname,
      port: urlObj.port,
      path: urlObj.pathname + urlObj.search,
      method,
      timeout,
      headers: {
        'Content-Type': 'application/json',
      },
    };

    const req = transport.request(options, (res) => {
      let data = '';
      res.on('data', (chunk) => (data += chunk));
      res.on('end', () => {
        try {
          const parsed = JSON.parse(data);
          if (res.statusCode >= 400) {
            reject(new GridError(parsed.error || data, res.statusCode));
          } else {
            resolve(parsed);
          }
        } catch (e) {
          reject(new GridError(`Invalid JSON: ${data.slice(0, 200)}`, res.statusCode));
        }
      });
    });

    req.on('error', (e) => reject(new GridError(`Connection failed: ${e.message}`)));
    req.on('timeout', () => { req.destroy(); reject(new GridError('Request timed out')); });

    if (body !== null) {
      req.write(JSON.stringify(body));
    }
    req.end();
  });
}

function get(url, query = {}) {
  const qs = Object.entries(query)
    .filter(([, v]) => v !== undefined && v !== null)
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(Array.isArray(v) ? v.join(',') : v)}`)
    .join('&');
  return request('GET', qs ? `${url}?${qs}` : url);
}

function post(url, body = {}) {
  return request('POST', url, body);
}

// ─── Grid Client ──────────────────────────────────────────────────────────────

class Grid {
  constructor(url = 'http://localhost:8080', options = {}) {
    this.url = url.replace(/\/+$/, '');
    this.defaultAgentId = options.defaultAgentId || 'node-sdk';
    this.timeout = options.timeout || 10000;
  }

  _post(path, body) {
    return post(`${this.url}${path}`, body);
  }

  _get(path, query) {
    return get(`${this.url}${path}`, query);
  }

  // ── Convenience writes ──

  async fact(content, options = {}) {
    return this._post('/write', {
      agent_id: options.agentId || this.defaultAgentId,
      type: 'fact',
      content,
      tags: options.tags || [],
      ttl_seconds: options.ttlSeconds || undefined,
    });
  }

  async decide(content, options = {}) {
    const text = options.rationale
      ? `${content}\nRationale: ${options.rationale}`
      : content;
    return this._post('/write', {
      agent_id: options.agentId || this.defaultAgentId,
      type: 'decision',
      content: text,
      tags: options.tags || [],
      ttl_seconds: options.ttlSeconds || 604800,
    });
  }

  async handoff(options = {}) {
    const text = `[${options.from} → ${options.to}] (${options.status || 'ready'}): ${options.content}`;
    return this._post('/write', {
      agent_id: options.agentId || options.from,
      type: 'handoff',
      content: text,
      tags: [...(options.tags || []), `agent:${options.to}`],
      ttl_seconds: options.ttlSeconds || 3600,
    });
  }

  async write(agentId, type, content, options = {}) {
    return this._post('/write', {
      agent_id: agentId,
      type,
      content,
      tags: options.tags || [],
      ttl_seconds: options.ttlSeconds || undefined,
      session_id: options.sessionId || '',
    });
  }

  // ── Query ──

  async query(options = {}) {
    const body = { tagMode: options.tagMode || 'OR' };
    if (options.tags) body.tags = options.tags;
    if (options.agents) body.agents = options.agents;
    if (options.type) body.type = options.type;
    if (options.types) body.types = options.types;
    if (options.max !== undefined) body.max = options.max;
    if (options.since) body.since = options.since;
    if (options.parentEntry) body.parent_entry = options.parentEntry;
    return this._post('/query', body);
  }

  async inject(context = '') {
    const result = await this._post('/inject', { context });
    return result.block || '';
  }

  // ── Admin ──

  async info() {
    return this._get('/info');
  }

  async prune() {
    return this._post('/prune', {});
  }

  async forget(entryId) {
    return request('DELETE', `${this.url}/forget/${entryId}`, null, this.timeout);
  }

  async health() {
    return this._get('/health');
  }
}

// ── Exports ──

module.exports = { Grid, GridError };
