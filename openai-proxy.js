function getWorkspace(req) {
  if (req.workspace) return req.workspace;
  if (req.headers['x-grid-workspace']) return req.headers['x-grid-workspace'];
  return process.env.GRID_WORKSPACE || '';
}

/**
 * openai-proxy.js — OpenAI-Compatible Proxy Middleware
 *
 * Transparently sits between any agent framework and the real LLM.
 * Every request passes through the Grid for context injection.
 *
 * Zero-code integration for any framework that supports custom base_url:
 *   base_url = "http://localhost:8080/v1"
 *
 * Environment variables:
 *   GRID_UPSTREAM_URL      — upstream LLM endpoint (default: https://api.openai.com)
 *   GRID_UPSTREAM_API_KEY  — API key for upstream (required)
 *   GRID_UPSTREAM_MODEL    — default model override (optional)
 */

const http = require('http');
const { Grid } = require('./reference/store.js');

// ─── Configuration ──────────────────────────────────────────────────────────────

const UPSTREAM_URL = (process.env.GRID_UPSTREAM_URL || 'https://api.openai.com').replace(/\/+$/, '');
const UPSTREAM_API_KEY = process.env.GRID_UPSTREAM_API_KEY || '';
const DEFAULT_MODEL = process.env.GRID_UPSTREAM_MODEL || '';
const PROXY_TIMEOUT = parseInt(process.env.GRID_PROXY_TIMEOUT || '60000', 10);

// ─── Grid Instance (shared with server.js if same process) ────────────────────

let gridInstance = null;

function setGrid(grid) {
  gridInstance = grid;
}

function getGrid() {
  if (!gridInstance) {
    gridInstance = new Grid();
  }
  return gridInstance;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function now() {
  return new Date().toISOString();
}

function obfuscateKey(key) {
  if (!key || key.length < 8) return key;
  return key.slice(0, 4) + '...' + key.slice(-4);
}

// ─── Context Injection ─────────────────────────────────────────────────────────

function injectIntoMessages(messages, contextBlock) {
  if (!contextBlock || !messages || messages.length === 0) return messages;

  // Find the system message (first message with role "system")
  const sysIdx = messages.findIndex(m => m.role === 'system');
  const contextPreamble = `─── SHARED MEMORY GRID CONTEXT ───\n${contextBlock}\n─── END GRID CONTEXT ───\n\n`;

  if (sysIdx >= 0) {
    // Inject context into existing system message
    const enriched = [...messages];
    enriched[sysIdx] = {
      ...enriched[sysIdx],
      content: contextPreamble + (enriched[sysIdx].content || ''),
    };
    return enriched;
  }

  // No system message — prepend one
  return [
    { role: 'system', content: contextPreamble + 'You are a helpful assistant with access to shared team memory.' },
    ...messages,
  ];
}

// ─── Forwarding ────────────────────────────────────────────────────────────────

function forwardRequest(openaiBody, streamMode) {
  if (streamMode) {
    // Return the upstream response object for streaming
    return new Promise((resolve, reject) => {
      const urlObj = new URL(UPSTREAM_URL);
      const transport = urlObj.protocol === 'https:' ? require('https') : require('http');
      const body = JSON.stringify(openaiBody);
      const options = {
        hostname: urlObj.hostname, port: urlObj.port || (urlObj.protocol === 'https:' ? 443 : 80),
        path: '/v1/chat/completions', method: 'POST', timeout: PROXY_TIMEOUT,
        headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body), 'Authorization': `Bearer ${UPSTREAM_API_KEY}` },
      };
      const req = transport.request(options, (res) => resolve({ stream: true, response: res }));
      req.on('error', reject);
      req.on('timeout', () => { req.destroy(); reject(new Error('Timed out')); });
      req.write(body);
      req.end();
    });
  }
  return new Promise((resolve, reject) => {
    const urlObj = new URL(UPSTREAM_URL);
    const transport = urlObj.protocol === 'https:' ? require('https') : require('http');
    const body = JSON.stringify(openaiBody);
    const options = {
      hostname: urlObj.hostname, port: urlObj.port || (urlObj.protocol === 'https:' ? 443 : 80),
      path: '/v1/chat/completions', method: 'POST', timeout: PROXY_TIMEOUT,
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body), 'Authorization': `Bearer ${UPSTREAM_API_KEY}` },
    };
    const req = transport.request(options, (res) => {
      let data = '';
      res.on('data', chunk => (data += chunk));
      res.on('end', () => {
        try { resolve({ status: res.statusCode, headers: res.headers, body: JSON.parse(data) }); }
        catch (e) { resolve({ status: res.statusCode, headers: res.headers, body: data }); }
      });
    });
    req.on('error', (e) => reject(new Error('Upstream: ' + e.message)));
    req.on('timeout', () => { req.destroy(); reject(new Error('Timed out')); });
    req.write(body);
    req.end();
  });
}

// ─── Request Handler ───────────────────────────────────────────────────────────

async function handleChatCompletions(req, res, parsedBody) {
  const grid = getGrid();

  // Parse body (already parsed by caller or parse here)
  const body = parsedBody || await parseBody(req);

  // Validate
  if (!body.messages || !Array.isArray(body.messages) || body.messages.length === 0) {
    return jsonError(res, 'messages is required and must be a non-empty array', 400);
  }

  // Extract context hint from last user message
  const lastUserMsg = [...body.messages].reverse().find(m => m.role === 'user');
  const contextHint = lastUserMsg ? (lastUserMsg.content || '') : '';

  // Determine workspace from request
  const workspace = getWorkspace(req);

  // Inject Grid context (workspace-scoped when header is present)
  let contextBlock = '';
  try {
    if (workspace) {
      // Workspace-scoped: query only this workspace's entries
      const wsQuery = await grid.read({ tags: [`ws:${workspace}`], max: 50, tagMode: 'AND' });
      const entries = wsQuery.entries || [];
      if (entries.length > 0) {
        // Build context block manually from workspace-scoped entries
        const lines = [`\u2500\u2500\u2500 SHARED MEMORY GRID \u2500\u2500\u2500\n`];
        lines.push(`Recent entries (workspace: ${workspace}):\n`);
        for (const e of entries.slice(0, 15)) {
          const type = e.type || 'observation';
          const agent = e.agent_id || '?';
          const content = (e.content || '').slice(0, 200);
          lines.push(`[${type}] agent:${agent} \u2014 ${content}\n`);
        }
        lines.push(`\n\u2500\u2500\u2500 END GRID \u2500\u2500\u2500`);
        contextBlock = lines.join('\n');
      }
    } else {
      // No workspace — use global inject (trusted internal mode)
      const injectResult = await grid.inject(contextHint);
      contextBlock = injectResult.block || '';
    }
  } catch (e) {
    console.error(`[Grid Proxy] Context injection failed: ${e.message}`);
  }

  const enrichedMessages = injectIntoMessages(body.messages, contextBlock);

  // Build forwarded request
  const forwardBody = {
    model: body.model || DEFAULT_MODEL || 'gpt-4o',
    messages: enrichedMessages,
    temperature: body.temperature,
    max_tokens: body.max_tokens,
    top_p: body.top_p,
    frequency_penalty: body.frequency_penalty,
    presence_penalty: body.presence_penalty,
    stop: body.stop,
    stream: body.stream,
  };

  // Remove undefined fields
  for (const key of Object.keys(forwardBody)) {
    if (forwardBody[key] === undefined) delete forwardBody[key];
  }

  // Check that upstream is configured
  if (!UPSTREAM_API_KEY) {
    // No upstream — return the enriched messages for debugging
    return jsonOk(res, {
      id: `grid_${Date.now()}`,
      object: 'chat.completion',
      created: Math.floor(Date.now() / 1000),
      model: forwardBody.model,
      choices: [{
        index: 0,
        message: {
          role: 'assistant',
          content: `[Grid Proxy] No upstream API key configured (GRID_UPSTREAM_API_KEY).\n\nEnriched messages would have been:\n\n${JSON.stringify(enrichedMessages, null, 2)}`,
        },
        finish_reason: 'stop',
      }],
      usage: { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 },
      _grid_context_injected: !!contextBlock,
    });
  }

  // Forward to upstream
  try {
    const isStream = body.stream === true;
    const upstream = await forwardRequest(forwardBody, isStream);

    // Handle streaming: pipe directly to the client
    if (isStream && upstream.stream) {
      res.writeHead(200, {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'Access-Control-Allow-Origin': '*',
      });
      upstream.response.pipe(res);
      return;
    }

    // Log the exchange to the Grid
    try {
      const userPreview = (lastUserMsg ? lastUserMsg.content : '').slice(0, 200).replace(/\n/g, ' ');
      const assistantContent = upstream.body.choices?.[0]?.message?.content || '';
      const assistantPreview = assistantContent.slice(0, 200).replace(/\n/g, ' ');
      await grid.write({
        agent_id: 'openai-proxy',
        type: 'observation',
        tags: ['llm-exchange', `model:${forwardBody.model}`],
        content: `[LLM] User: ${userPreview}\nAssistant: ${assistantPreview}`,
        ttl_seconds: 3600,
      });
    } catch (logErr) {
      // Logging failure is non-fatal
    }

    // Return upstream response with grid metadata
    const response = upstream.body;
    if (typeof response === 'object' && response !== null) {
      response._grid_context_injected = !!contextBlock;
      response._grid_entry_count = contextBlock ? (contextBlock.match(/^\[/gm) || []).length : 0;
    }

    jsonRespond(res, upstream.status, response);

  } catch (err) {
    console.error(`[Grid Proxy] Upstream error: ${err.message}`);
    jsonError(res, `Upstream LLM error: ${err.message}`, 502);
  }
}

// ─── Models Endpoint ───────────────────────────────────────────────────────────

async function handleModels(req, res) {
  const models = [];
  if (DEFAULT_MODEL) {
    models.push({
      id: DEFAULT_MODEL,
      object: 'model',
      created: Math.floor(Date.now() / 1000),
      owned_by: 'grid-proxy',
    });
  }
  models.push({
    id: 'grid-proxy',
    object: 'model',
    created: Math.floor(Date.now() / 1000),
    owned_by: 'grid',
    description: 'Grid Memory proxy — injects context, forwards to upstream LLM',
  });

  jsonOk(res, {
    object: 'list',
    data: models,
  });
}

// ─── Body Parser ───────────────────────────────────────────────────────────────

function parseBody(req) {
  return new Promise((resolve, reject) => {
    let data = '';
    req.on('data', chunk => (data += chunk));
    req.on('end', () => {
      if (!data) return resolve({});
      try {
        resolve(JSON.parse(data));
      } catch (e) {
        reject(new Error('Invalid JSON in request body'));
      }
    });
    req.on('error', reject);
  });
}

// ─── Response Helpers ──────────────────────────────────────────────────────────

function jsonOk(res, data) {
  jsonRespond(res, 200, data);
}

function jsonError(res, message, status = 400, code = 'INVALID_PARAMETER') {
  jsonRespond(res, status, { error: { message, type: 'error', code, param: null } });
}

function jsonRespond(res, status, data) {
  const body = JSON.stringify(data, null, 2);
  res.writeHead(status, {
    'Content-Type': 'application/json',
    'Access-Control-Allow-Origin': '*',
  });
  res.end(body);
}

// ─── Router ────────────────────────────────────────────────────────────────────

async function route(req, res) {
  const method = req.method;
  const url = req.url.split('?')[0];

  // CORS preflight
  if (method === 'OPTIONS') {
    res.writeHead(204, {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type, Authorization',
    });
    return res.end();
  }

  try {
    // GET /v1/models
    if (method === 'GET' && url === '/v1/models') {
      return handleModels(req, res);
    }

    // POST /v1/chat/completions
    if (method === 'POST' && url === '/v1/chat/completions') {
      const body = await parseBody(req);
      return handleChatCompletions(req, res, body);
    }

    // Not found
    jsonError(res, `Not found: ${method} ${url}`, 404, 'NOT_FOUND');

  } catch (err) {
    console.error(`[Grid Proxy] Error: ${err.message}`);
    jsonError(res, err.message, 500, 'INTERNAL_ERROR');
  }
}

// ─── Exports ───────────────────────────────────────────────────────────────────

module.exports = {
  route,
  setGrid,
  handleChatCompletions,
};
