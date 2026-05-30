/**
 * subscriptions.js — Live Subscription Engine (Server-Sent Events)
 *
 * Turns the Grid from a pull-based store into a reactive event bus.
 * Any client subscribes to tag scopes and receives real-time pushes
 * whenever matching entries are written.
 *
 * Usage:
 *   GET /subscribe?tags=project:alpha&types=blocker,decision
 *
 *   → SSE stream pushing events as entries are written
 *
 *   GET /subscribe/list
 *   → List all active subscriptions (admin)
 */

// ─── Subscription Registry ────────────────────────────────────────────────

// id → { res, filter, createdAt }
const subscriptions = new Map();
let subIdCounter = 0;

// Max concurrent subscriptions per IP
const MAX_SUB_PER_IP = 10;

// ─── SSE Helpers ──────────────────────────────────────────────────────────

function sendSSE(res, event, data) {
  res.write(`event: ${event}\n`);
  res.write(`data: ${JSON.stringify(data)}\n\n`);
}

function sendHeartbeat(res) {
  res.write(`:heartbeat\n\n`);
}

// ─── Subscribe ────────────────────────────────────────────────────────────

function subscribe(req, res, query) {
  // Rate limit: max subscriptions per IP
  const ip = req.headers['x-forwarded-for'] || req.connection?.remoteAddress || 'unknown';
  let ipCount = 0;
  for (const [, sub] of subscriptions) {
    if (sub.ip === ip) ipCount++;
  }
  if (ipCount >= MAX_SUB_PER_IP) {
    res.writeHead(429, { 'Content-Type': 'application/json' });
    return res.end(JSON.stringify({ error: 'Too many subscriptions from this IP', code: 'RATE_LIMITED' }));
  }

  const tags = (query.tags || '').split(',').filter(Boolean);
  const types = (query.types || '').split(',').filter(Boolean);
  const agents = (query.agents || '').split(',').filter(Boolean);
  const workspace = req.workspace || req.headers['x-grid-workspace'] || '';

  const id = ++subIdCounter;
  const filter = { tags, types, agents, workspace };
  const createdAt = new Date().toISOString();

  // Set SSE headers
  res.writeHead(200, {
    'Content-Type': 'text/event-stream',
    'Cache-Control': 'no-cache',
    'Connection': 'keep-alive',
    'Access-Control-Allow-Origin': '*',
    'X-Accel-Buffering': 'no',
  });

  // Send initial connection event
  sendSSE(res, 'connected', {
    subscription_id: id,
    filter,
    timestamp: createdAt,
  });

  // Store subscription with IP for rate limiting
  subscriptions.set(id, { res, filter, createdAt, ip });

  // Heartbeat every 30s
  const heartbeat = setInterval(() => {
    try { sendHeartbeat(res); } catch { clearInterval(heartbeat); }
  }, 30000);

  // Cleanup on disconnect
  req.on('close', () => {
    clearInterval(heartbeat);
    subscriptions.delete(id);
  });
}

// ─── Publish — called after every write ──────────────────────────────────

function publish(writtenEntry, options = {}) {
  if (subscriptions.size === 0) return;

  // The write response has entry_id (not id). Normalize both paths.
  const entryId = writtenEntry.entry_id || writtenEntry.id || '';
  const entryTags = new Set(writtenEntry.tags || []);
  const entryType = writtenEntry.type || '';
  const entryAgent = writtenEntry.agent_id || '';
  const entryContent = writtenEntry.content || '';
  const entryWorkspace = options.workspace || '';

  for (const [id, sub] of subscriptions) {
    const { res, filter } = sub;

    // Check workspace match (using options.workspace, not writtenEntry — write response doesn't include it)
    if (filter.workspace && entryWorkspace && filter.workspace !== entryWorkspace) continue;

    // Check tag match
    if (filter.tags.length > 0) {
      const matches = filter.tags.some(t => entryTags.has(t));
      if (!matches) continue;
    }

    // Check type match
    if (filter.types.length > 0 && !filter.types.includes(entryType)) continue;

    // Check agent match
    if (filter.agents.length > 0 && !filter.agents.includes(entryAgent)) continue;

    // Send event
    try {
      sendSSE(res, 'entry', {
        id: entryId,
        type: entryType,
        agent_id: entryAgent,
        tags: [...entryTags],
        content: entryContent.slice(0, 500),
      });
    } catch {
      // Client disconnected — clean up
      subscriptions.delete(id);
    }
  }
}

// ─── List Subscriptions (admin) ──────────────────────────────────────────

function listSubscriptions() {
  const result = [];
  for (const [id, sub] of subscriptions) {
    result.push({
      id,
      filter: sub.filter,
      created_at: sub.createdAt,
    });
  }
  return result;
}

// ─── Module Exports ───────────────────────────────────────────────────────

module.exports = { subscribe, publish, listSubscriptions };
