#!/usr/bin/env node
/**
 * route-registry.js — Structured Route Registry with Mandatory Permissions + Rate Limiting
 *
 * Replaces the monolithic if-else chain in server.js.
 * Every route is registered with a method, path pattern, required permission,
 * rate limit, and handler. Authorization + rate limiting are applied structurally.
 *
 * Usage:
 *   const registry = new RouteRegistry();
 *   registry.register('POST', '/write', 'architect', handler, { rateLimit: 30 });
 *
 *   // In server.js handle():
 *   const route = registry.match(method, url);
 *   if (route) {
 *     const auth = await registry.enforce(gateway, req, route);
 *     if (!auth.allowed) return auth.respond(res);
 *     await route.handler(req, res, grid, gateway);
 *     return;
 *   }
 */

'use strict';

// ─── Permission Hierarchy ────────────────────────────────────────────

const PERMISSION_LEVELS = { viewer: 0, analyst: 1, architect: 2, executive: 3, admin: 4 };

function hasPermission(required, granted) {
  if (!(required in PERMISSION_LEVELS) || !(granted in PERMISSION_LEVELS)) return false;
  return PERMISSION_LEVELS[granted] >= PERMISSION_LEVELS[required];
}

// ─── In-memory rate limiter ─────────────────────────────────────────

const _rateLimitStore = new Map();

function _checkRateLimit(key, limit) {
  if (!limit || limit <= 0) return true;
  const now = Date.now();
  const windowMs = 60000;
  const windowStart = now - windowMs;
  let timestamps = (_rateLimitStore.get(key) || []).filter(ts => ts >= windowStart);
  if (timestamps.length >= limit) {
    _rateLimitStore.set(key, timestamps);
    return false;
  }
  timestamps.push(now);
  _rateLimitStore.set(key, timestamps);
  return true;
}

// ─── Route Registry ──────────────────────────────────────────────────

class RouteRegistry {
  constructor() {
    this._routes = [];
  }

  /**
   * Register a route with mandatory permission level.
   * @param {string} method - HTTP method (GET, POST, DELETE, PATCH)
   * @param {string} path - URL path (supports :param and * suffix patterns)
   * @param {string} permission - Required permission level
   * @param {Function} handler - async (req, res, grid, gateway, query) => void
   * @param {Object} [options]
   * @param {boolean} [options.skipAuth] - Skip auth for this route (health checks only)
   * @param {boolean} [options.adminOnly] - Always require admin
   * @param {number} [options.rateLimit] - Max requests per 60s window
   */
  register(method, path, permission, handler, options = {}) {
    if (!method || !path || !handler) {
      throw new Error('method, path, and handler are required');
    }
    if (permission && !(permission in PERMISSION_LEVELS)) {
      throw new Error(`Invalid permission level: ${permission}. Valid: ${Object.keys(PERMISSION_LEVELS).join(', ')}`);
    }

    const pattern = path
      .replace(/\*/g, '.*')
      .replace(/:(\w+)/g, '([^/]+)');

    // Reject duplicate registrations (same method + path)
    const methodUC = method.toUpperCase();
    const duplicate = this._routes.some(r => r.method === methodUC && r.path === path);
    if (duplicate) {
      throw new Error('Duplicate route registration: ' + methodUC + ' ' + path);
    }

    this._routes.push({
      method: methodUC,
      path,
      pattern: new RegExp('^' + pattern + '$'),
      permission,
      handler,
      skipAuth: options.skipAuth === true,
      adminOnly: options.adminOnly === true,
      rateLimit: options.rateLimit || 0,
    });
  }

  /**
   * Register multiple routes at once.
   */
  registerMany(routes) {
    for (const r of routes) {
      this.register(r.method, r.path, r.permission, r.handler, r.options || {});
    }
  }

  /**
   * Match a request to a registered route.
   */
  match(method, url) {
    const path = url.split('?')[0];
    for (const route of this._routes) {
      if (route.method !== method.toUpperCase()) continue;
      const match = path.match(route.pattern);
      if (match) {
        const paramNames = (route.path.match(/:(\w+)/g) || []).map(p => p.slice(1));
        const params = {};
        for (let i = 0; i < paramNames.length; i++) {
          params[paramNames[i]] = match[i + 1] ? decodeURIComponent(match[i + 1]) : undefined;
        }
        return { route, params };
      }
    }
    return null;
  }

  /**
   * Enforce authentication + rate limiting for a matched route.
   */
  async enforce(gateway, req, route, options = {}) {
    const enforceAuth = options.enforceAuth !== false;

    // Rate limiting (always active, regardless of auth mode)
    if (route.rateLimit > 0) {
      const ip = req.headers['x-forwarded-for'] || req.connection?.remoteAddress || 'unknown';
      const key = route.path + ':' + ip;
      if (!_checkRateLimit(key, route.rateLimit)) {
        return {
          allowed: false,
          status: 429,
          respond: (res) => {
            const cors = { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS', 'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Grid-Workspace' };
            res.writeHead(429, cors);
            res.end(JSON.stringify({ error: `Rate limit exceeded for ${route.path}. Max ${route.rateLimit}/min.`, code: 'RATE_LIMITED' }, null, 2));
          },
        };
      }
    }

    if (!enforceAuth || route.skipAuth) {
      return { allowed: true };
    }

    if (route.adminOnly) {
      const pipeline = await gateway.enforce(req, 'admin');
      return {
        allowed: pipeline.allowed,
        status: pipeline.status,
        auth: pipeline.auth,
        respond: (res) => {
          res.writeHead(pipeline.status, gateway.corsHeaders(req));
          res.end(JSON.stringify(pipeline.error, null, 2));
        },
      };
    }

    if (route.permission) {
      const pipeline = await gateway.enforce(req, route.permission);
      return {
        allowed: pipeline.allowed,
        status: pipeline.status,
        auth: pipeline.auth,
        respond: (res) => {
          res.writeHead(pipeline.status, gateway.corsHeaders(req));
          res.end(JSON.stringify(pipeline.error, null, 2));
        },
      };
    }

    return { allowed: true };
  }

  /**
   * List all registered routes.
   */
  listRoutes() {
    return this._routes.map(r => ({
      method: r.method,
      path: r.path,
      permission: r.permission,
      skipAuth: r.skipAuth,
      adminOnly: r.adminOnly,
      rateLimit: r.rateLimit || undefined,
    }));
  }
}

module.exports = { RouteRegistry, PERMISSION_LEVELS, hasPermission };
