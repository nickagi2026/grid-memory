/**
 * seed-mode.js — Demo/Seed Mode
 *
 * On first launch, populates the Grid with example agents,
 * decisions, conflicts, and federation peers.
 * Triggered by GRID_SEED_MODE=true or /seed endpoint.
 */

async function seedGrid(grid) {
  const info = await grid.info();
  if (info.total_entries > 5) return { seeded: false, reason: 'Grid already has data' };

  const entries = [];

  // Agent A: Architecture decisions
  entries.push(grid.write({
    agent_id: 'arch-agent', type: 'decision', tags: ['topic:architecture', 'demo'],
    content: 'We will use PostgreSQL for primary storage. Rationale: team expertise, ACID compliance, PostGIS for geospatial queries.',
    memory_tier: 'organization', outcome: { result: 'success', delta: 'Reduced query latency by 40%' }
  }));
  entries.push(grid.write({
    agent_id: 'arch-agent', type: 'decision', tags: ['topic:architecture', 'demo'],
    content: 'API gateway should use GraphQL. Rationale: frontend team needs flexible queries, multiple data sources to aggregate.',
    memory_tier: 'project',
  }));

  // Agent B: Operations
  entries.push(grid.write({
    agent_id: 'ops-agent', type: 'fact', tags: ['topic:deployment', 'demo'],
    content: 'Production deployment frequency: 3x/week. Rollback rate: 2%. Average deploy time: 12 minutes.',
    memory_tier: 'organization',
  }));
  entries.push(grid.write({
    agent_id: 'ops-agent', type: 'blocker', tags: ['topic:deployment', 'demo'],
    content: 'Database migration time is blocking zero-downtime deploys. Current migrations take 8+ minutes.',
    parent_entry: null,
  }));

  // Agent C: Security
  entries.push(grid.write({
    agent_id: 'sec-agent', type: 'decision', tags: ['topic:security', 'demo'],
    content: 'All API endpoints must use OAuth 2.0 with PKCE. Rationale: mobile app clients cannot store client secrets.',
    memory_tier: 'organization',
  }));
  entries.push(grid.write({
    agent_id: 'sec-agent', type: 'observation', tags: ['topic:security', 'demo'],
    content: 'Dependency scan found 12 critical CVEs in the auth library. Upgrade path identified.',
  }));

  // Deliberate contradiction for conflict detection
  entries.push(grid.write({
    agent_id: 'arch-agent', type: 'decision', tags: ['topic:database', 'demo'],
    content: 'Primary database should be MongoDB for schema flexibility.',
  }));
  entries.push(grid.write({
    agent_id: 'ops-agent', type: 'decision', tags: ['topic:database', 'demo'],
    content: 'Primary database must use PostgreSQL. Rationale: team already has PostgreSQL expertise.',
  }));

  const results = await Promise.all(entries);

  return {
    seeded: true,
    agent_count: 3,
    entry_count: results.filter(Boolean).length,
  };
}

module.exports = { seedGrid };
