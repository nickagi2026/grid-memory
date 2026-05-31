#!/usr/bin/env node
/**
 * semantic-search/embeddings.js — Embedding Generation for Semantic Search
 *
 * Generates embeddings via OpenAI-compatible API and computes cosine similarity.
 *
 * Supports:
 *   - OpenAI API (text-embedding-3-small / text-embedding-ada-002)
 *   - Any OpenAI-compatible embedding API
 *   - Local embedding cache to avoid redundant API calls
 *
 * Environment:
 *   GRID_EMBEDDING_API_KEY   — API key for embedding service
 *   GRID_EMBEDDING_URL       — Custom API URL (default: https://api.openai.com)
 *   GRID_EMBEDDING_MODEL     — Model name (default: text-embedding-3-small)
 *   GRID_EMBEDDING_DIMS      — Output dimensions (default: 1536)
 */

'use strict';

const https = require('https');
const crypto = require('crypto');
const fs = require('fs');

// ─── Configuration ───

const CONFIG = {
  apiKey: process.env.GRID_EMBEDDING_API_KEY || '',
  apiUrl: process.env.GRID_EMBEDDING_URL || 'https://api.openai.com',
  model: process.env.GRID_EMBEDDING_MODEL || 'text-embedding-3-small',
  dimensions: parseInt(process.env.GRID_EMBEDDING_DIMS || '1536', 10),
};

// ─── Embedding Cache ───

// ─── Embedding Cache (in-memory + file) ───

const _cache = new Map();
const CACHE_PATH = process.env.GRID_EMBEDDING_CACHE || 'embedding_cache.json';

function _cacheKey(text) {
  return crypto.createHash('sha256').update(text).digest('hex');
}

function _loadCache() {
  try {
    if (fs.existsSync(CACHE_PATH)) {
      const data = JSON.parse(fs.readFileSync(CACHE_PATH, 'utf-8'));
      for (const [k, v] of Object.entries(data)) _cache.set(k, v);
    }
  } catch (e) { /* cache file corrupt — start fresh */ }
}

function _saveCache() {
  try {
    const obj = {};
    for (const [k, v] of _cache) obj[k] = v;
    fs.writeFileSync(CACHE_PATH, JSON.stringify(obj), 'utf-8');
  } catch (e) { /* cache write failure — non-fatal */ }
}

// Load cache on module init
_loadCache();

// ─── Cosine Similarity ───

function cosineSimilarity(a, b) {
  if (!a || !b || a.length !== b.length) return 0;
  let dot = 0, normA = 0, normB = 0;
  for (let i = 0; i < a.length; i++) {
    dot += a[i] * b[i];
    normA += a[i] * a[i];
    normB += b[i] * b[i];
  }
  if (normA === 0 || normB === 0) return 0;
  return dot / (Math.sqrt(normA) * Math.sqrt(normB));
}

// ─── Embedding Generation ───

/**
 * Generate an embedding vector for a text string.
 * Uses cached embedding if available.
 * @param {string} text - Text to embed
 * @returns {Promise<number[]>} Embedding vector
 */
async function embed(text) {
  if (!text || typeof text !== 'string') {
    throw new Error('Text is required for embedding');
  }

  const trimmed = text.trim().slice(0, 8000);
  const key = _cacheKey(trimmed);
  if (_cache.has(key)) return _cache.get(key);

  if (!CONFIG.apiKey) {
    return null;  // Semantic search disabled — set GRID_EMBEDDING_API_KEY
  }

  const vector = await _callEmbeddingAPI(trimmed);
  _cache.set(key, vector);
  _saveCache();
  return vector;
}

function _callEmbeddingAPI(text) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify({
      input: text,
      model: CONFIG.model,
      dimensions: CONFIG.dimensions,
    });

    const urlObj = new URL('/v1/embeddings', CONFIG.apiUrl);
    const req = https.request({
      hostname: urlObj.hostname,
      port: urlObj.port || 443,
      path: urlObj.pathname,
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${CONFIG.apiKey}`,
        'Content-Length': Buffer.byteLength(body),
      },
    }, (res) => {
      let data = '';
      res.on('data', c => data += c);
      res.on('end', () => {
        try {
          const parsed = JSON.parse(data);
          if (parsed.error) reject(new Error(parsed.error.message));
          else if (parsed.data && parsed.data[0] && parsed.data[0].embedding) {
            resolve(parsed.data[0].embedding);
          } else {
            reject(new Error('Unexpected embedding response format'));
          }
        } catch (e) { reject(new Error(`Embedding API parse error: ${e.message}`)); }
      });
    });
    req.on('error', reject);
    req.write(body);
    req.end();
  });
}

/**
 * Embed multiple texts in batch.
 * @param {string[]} texts - Array of texts to embed
 * @returns {Promise<number[][]>} Array of embedding vectors
 */
async function embedBatch(texts) {
  const results = [];
  for (const t of texts) {
    results.push(await embed(t));
  }
  return results;
}

/**
 * Score entries by semantic similarity to a query.
 * @param {string} query - Search query
 * @param {Array} entries - Array of entries with .content and optionally .embedding
 * @param {number} [limit=10] - Max results to return
 * @returns {Promise<Array<{entry, score}>>} Scored entries, sorted by similarity
 */
async function search(query, entries, limit = 10) {
  if (!entries || entries.length === 0) return [];

  const queryVec = await embed(query);
  const batch = entries.map((e, i) => ({
    entry: e,
    text: (e.content || '').slice(0, 8000),
    index: i,
  }));

  // Generate embeddings for entries that don't have them cached
  const results = [];
  for (const item of batch) {
    try {
      const entryVec = await embed(item.text);
      const score = cosineSimilarity(queryVec, entryVec);
      results.push({ entry: item.entry, score });
    } catch {
      results.push({ entry: item.entry, score: 0 });
    }
  }

  results.sort((a, b) => b.score - a.score);
  return results.slice(0, limit);
}

module.exports = { embed, embedBatch, search, cosineSimilarity };
