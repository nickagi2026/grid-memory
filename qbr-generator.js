#!/usr/bin/env node
'use strict';
/**
 * qbr-generator.js — Quarterly Business Review Generator
 *
 * Produces structured QBR reports derived entirely from Grid entries.
 * Generates: executive summary, KPIs, strategic decisions, opportunity pipeline,
 * risks & contradictions, and recommendations.
 *
 * Endpoints (registered in server.js):
 *   GET  /qbr?period=Q1-2026  — Generate QBR for a specific period
 *   POST /qbr/generate         — Generate QBR with custom parameters
 *
 * Usage:
 *   const { generate } = require('./qbr-generator.js');
 *   const qbr = await generate(grid, { period: 'Q1 2026' });
 */

const { generateDashboard } = require('./mike-dashboard.js');
const { getStats } = require('./decision-graph.js');

// ─── Helpers ──────────────────────────────────────────────────────────────────

function now() {
  return new Date().toISOString();
}

function parsePeriod(period) {
  // Default: current quarter
  if (!period) {
    const date = new Date();
    const q = Math.floor(date.getMonth() / 3) + 1;
    const year = date.getFullYear();
    return { quarter: `Q${q} ${year}`, start: _quarterStart(q, year), end: _quarterEnd(q, year) };
  }

  // Parse "Q1-2026" or "Q1 2026" formats
  const match = period.match(/Q(\d)[\s-]?(\d{4})/i);
  if (match) {
    const q = parseInt(match[1], 10);
    const year = parseInt(match[2], 10);
    if (q >= 1 && q <= 4 && year >= 2000 && year <= 2100) {
      return { quarter: `Q${q} ${year}`, start: _quarterStart(q, year), end: _quarterEnd(q, year) };
    }
  }

  // Fall back to default
  const date = new Date();
  const q = Math.floor(date.getMonth() / 3) + 1;
  const year = date.getFullYear();
  return { quarter: `Q${q} ${year}`, start: _quarterStart(q, year), end: _quarterEnd(q, year) };
}

function _quarterStart(q, year) {
  return `${year}-${String((q - 1) * 3 + 1).padStart(2, '0')}-01T00:00:00.000Z`;
}

function _quarterEnd(q, year) {
  const month = q * 3; // March, June, September, December
  const lastDay = new Date(year, month, 0).getDate();
  return `${year}-${String(month).padStart(2, '0')}-${String(lastDay).padStart(2, '0')}T23:59:59.999Z`;
}

function summarizeContent(content, maxLen = 150) {
  if (!content) return '';
  // Use first line or first meaningful sentence
  const firstLine = content.split('\n')[0].trim();
  if (firstLine.length <= maxLen) return firstLine;
  return firstLine.slice(0, maxLen) + '...';
}

// ─── QBR Generator ───────────────────────────────────────────────────────────

async function generate(grid, periodInfo = {}) {
  const periodStr = periodInfo.period || periodInfo.quarter || '';
  const { quarter, start, end } = parsePeriod(periodStr);

  // Get dashboard data for context
  const dashboard = await generateDashboard(grid);

  // Get decision stats
  let decisionStats;
  try {
    decisionStats = await getStats(grid);
  } catch (e) {
    decisionStats = { total_decisions: 0, decisions_with_outcomes: 0, outcome_coverage: '0%', overall_success_rate: '0%', outcomes: { success: 0, failure: 0, partial: 0 }, patterns: [], top_topics: [] };
  }

  // Pull entries for the period
  const periodResult = await grid.read({
    since: start,
    before: end,
    max: 500,
  });
  const periodEntries = periodResult.entries || [];

  // Pull all entries for full context
  const allResult = await grid.read({ max: 500 });
  const allEntries = allResult.entries || [];

  // ── KPIs ──
  const decisionsInPeriod = periodEntries.filter(e => e.type === 'decision');
  const decisionsWithOutcome = decisionsInPeriod.filter(e => {
    return e.outcome || (e.content && (e.content.includes('Outcome: success') || e.content.includes('Outcome: failure')));
  });

  // Contradictions
  const contradictions = allEntries.filter(e =>
    (e.tags || []).includes('contradiction') || (e.tags || []).some(t => t.startsWith('contradiction'))
  );

  // Opportunities
  const oppEntries = allEntries.filter(e =>
    e.type === 'opportunity' || (e.tags || []).includes('opportunity')
  );
  const wonOpps = oppEntries.filter(e => {
    const stage = _extractStageFromTags(e.tags);
    return stage === 'won';
  });

  // Calculate avg decision-to-outcome time and most contentious topic
  let totalDecisionToOutcomeDays = 0;
  let decisionOutcomeCount = 0;
  for (const d of decisionsInPeriod) {
    if (d.outcome && d.outcome.recorded_at) {
      const decisionTime = new Date(d.created_at).getTime();
      const outcomeTime = new Date(d.outcome.recorded_at).getTime();
      if (outcomeTime > decisionTime) {
        totalDecisionToOutcomeDays += (outcomeTime - decisionTime) / (1000 * 60 * 60 * 24);
        decisionOutcomeCount++;
      }
    }
  }

  // Most contentious topic (most decisions with outcomes pending)
  const topicDecisionCount = new Map();
  for (const d of decisionsInPeriod) {
    for (const tag of d.tags || []) {
      if (tag.startsWith('agent:') || tag.startsWith('stage:') || tag.startsWith('ws:')) continue;
      if (!d.outcome) {
        topicDecisionCount.set(tag, (topicDecisionCount.get(tag) || 0) + 1);
      }
    }
  }
  const topContentious = [...topicDecisionCount.entries()].sort((a, b) => b[1] - a[1]);
  const mostContentiousTopic = topContentious.length > 0 ? topContentious[0][0] : 'none';

  // Total revenue from won deals
  const totalRevenue = wonOpps.reduce((sum, e) => {
    return sum + _extractRevenue(e.content);
  }, 0);

  // Best decision-maker
  let topDecisionMaker = 'N/A';
  if (decisionStats.decision_makers && decisionStats.decision_makers.length > 0) {
    const withCoverage = decisionStats.decision_makers.filter(m => parseInt(m.tracked_outcomes) > 0);
    if (withCoverage.length > 0) {
      topDecisionMaker = withCoverage.reduce((best, m) => {
        const rateB = parseFloat(m.success_rate) || 0;
        const rateBest = parseFloat(best.success_rate) || 0;
        return rateB > rateBest ? m : best;
      }, withCoverage[0]).agent;
    }
  }

  const kpis = {
    decisions_made: decisionsInPeriod.length,
    decisions_with_outcome: decisionsWithOutcome.length,
    contradictions_found: contradictions.length,
    opportunities_identified: oppEntries.length,
    opportunities_won: wonOpps.length,
    total_revenue: '$' + totalRevenue.toLocaleString(),
    avg_decision_to_outcome_days: decisionOutcomeCount > 0
      ? Math.round((totalDecisionToOutcomeDays / decisionOutcomeCount) * 10) / 10
      : 0,
    top_decision_maker: topDecisionMaker,
    most_contentious_topic: mostContentiousTopic,
  };

  // ── Executive Summary ──
  const executiveSummary = _buildExecutiveSummary(quarter, periodEntries, kpis, dashboard);

  // ── Sections ──
  const sections = [];

  // 1. Strategic Decisions
  sections.push({
    title: 'Strategic Decisions',
    type: 'decisions',
    insights: _buildDecisionInsights(decisionsInPeriod, kpis),
    data: decisionsInPeriod.slice(0, 15).map(d => ({
      id: d.id,
      agent: d.agent_id,
      summary: summarizeContent(d.content, 120),
      outcome: d.outcome ? d.outcome.result : null,
      created_at: d.created_at,
    })),
  });

  // 2. Opportunity Pipeline
  sections.push({
    title: 'Opportunity Pipeline',
    type: 'opportunities',
    insights: _buildOpportunityInsights(oppEntries, dashboard),
    data: oppEntries.slice(0, 20).map(o => ({
      id: o.id,
      stage: _extractStageFromTags(o.tags),
      summary: summarizeContent(o.content, 120),
      value: _extractRevenue(o.content),
      created_at: o.created_at,
    })),
  });

  // 3. Risks & Contradictions
  sections.push({
    title: 'Risks & Contradictions',
    type: 'risks',
    insights: _buildRiskInsights(contradictions, allEntries),
    data: contradictions.slice(0, 10).map(c => ({
      id: c.id,
      agent: c.agent_id,
      summary: summarizeContent(c.content, 120),
      tags: c.tags,
      created_at: c.created_at,
    })),
  });

  // 4. Recommendations
  sections.push({
    title: 'Recommendations',
    type: 'recommendations',
    insights: _buildRecommendations(kpis, dashboard, periodEntries),
    data: _generateRecommendations(kpis, dashboard, periodEntries),
  });

  return {
    title: `Grid QBR — ${quarter}`,
    period: `${start.slice(0, 10)} to ${end.slice(0, 10)}`,
    generated_at: now(),
    executive_summary: executiveSummary,
    kpis,
    sections,
  };
}

// ─── Section Builders ────────────────────────────────────────────────────────

function _buildExecutiveSummary(quarter, entries, kpis, dashboard) {
  const agentCount = dashboard.summary ? dashboard.summary.unique_agents : 0;
  const entryCount = entries.length;

  return (
    `In ${quarter}, the Grid tracked ${entryCount} entries ` +
    `across ${Math.max(agentCount, kpis.decisions_made > 0 ? 1 : 0)} agents. ` +
    `${kpis.decisions_made} strategic decisions were made, ` +
    `${kpis.opportunities_identified} opportunities identified, ` +
    `and ${kpis.opportunities_won} won. ` +
    `Revenue from won deals: ${kpis.total_revenue}. ` +
    `Top decision-maker: ${kpis.top_decision_maker} with ${kpis.decisions_made} decisions tracked.`
  );
}

function _buildDecisionInsights(decisions, kpis) {
  if (decisions.length === 0) return 'No strategic decisions recorded this period.';
  const withOutcome = decisions.filter(d => d.outcome || (d.content && d.content.includes('Outcome:')));
  const successRate = withOutcome.length > 0
    ? Math.round((withOutcome.filter(d => {
        const o = d.outcome ? d.outcome.result : null;
        return o === 'success';
      }).length / withOutcome.length) * 100)
    : 0;
  return (
    `${decisions.length} decisions made this period, ` +
    `${withOutcome.length} with tracked outcomes ` +
    `(${successRate}% success rate). ` +
    `Average ${kpis.avg_decision_to_outcome_days} days from decision to outcome.`
  );
}

function _buildOpportunityInsights(oppEntries, dashboard) {
  if (oppEntries.length === 0) return 'No opportunities identified this period.';
  const stages = {};
  for (const o of oppEntries) {
    const stage = _extractStageFromTags(o.tags);
    stages[stage] = (stages[stage] || 0) + 1;
  }
  const stageSummary = Object.entries(stages)
    .sort((a, b) => b[1] - a[1])
    .map(([s, c]) => `${s}: ${c}`)
    .join(', ');
  const pipelineValue = dashboard.opportunities ? dashboard.opportunities.pipeline_value : '$0';
  return (
    `${oppEntries.length} opportunities in pipeline (${stageSummary}). ` +
    `Pipeline value: ${pipelineValue}. ` +
    `Win rate: ${dashboard.opportunities ? dashboard.opportunities.win_rate : '0%'}.`
  );
}

function _buildRiskInsights(contradictions, allEntries) {
  if (contradictions.length === 0) {
    // Check for stale entries
    const nowIso = now();
    const staleCount = allEntries.filter(e => {
      if (!e.last_read_at) return false;
      return (new Date(nowIso) - new Date(e.last_read_at)) > (30 * 24 * 60 * 60 * 1000);
    }).length;
    if (staleCount > 0) {
      return `No contradictions found. ${staleCount} entries have not been read in 30+ days.`;
    }
    return 'No significant risks or contradictions detected this period.';
  }
  return `${contradictions.length} contradictions detected. Review flagged entries and resolve inconsistencies.`;
}

function _buildRecommendations(kpis, dashboard, entries) {
  const recs = [];

  if (kpis.decisions_made > 0 && kpis.decisions_with_outcome < kpis.decisions_made * 0.5) {
    recs.push('Improve outcome tracking — fewer than 50% of decisions have recorded outcomes.');
  }

  if (kpis.contradictions_found > 0) {
    recs.push(`Resolve ${kpis.contradictions_found} contradictions before making decisions dependent on conflicting information.`);
  }

  if (kpis.opportunities_identified > 0 && kpis.opportunities_won === 0) {
    recs.push('Focus on converting identified opportunities — none have progressed to won this period.');
  }

  const entriesWithLowConfidence = entries.filter(e => {
    const content = (e.content || '').toLowerCase();
    return content.includes('confidence: low') || content.includes('low confidence') || content.includes('uncertain');
  });
  if (entriesWithLowConfidence.length > 5) {
    recs.push(`Review ${entriesWithLowConfidence.length} low-confidence entries for potential risk mitigation.`);
  }

  if (recs.length === 0) {
    recs.push('Continue current trajectory — all metrics are healthy.');
  }

  return recs;
}

function _generateRecommendations(kpis, dashboard, entries) {
  const recs = _buildRecommendations(kpis, dashboard, entries);
  return recs.map((r, i) => ({
    priority: i === 0 ? 'high' : i === 1 ? 'medium' : 'low',
    recommendation: r,
    context: 'Derived from Grid QBR analysis',
  }));
}

// ─── Internal Helpers ────────────────────────────────────────────────────────

function _extractStageFromTags(tags) {
  for (const t of tags || []) {
    if (t.startsWith('stage:')) return t.slice(6);
  }
  return 'detected';
}

function _extractRevenue(content) {
  if (!content) return 0;
  const match = content.match(/Estimated Annual Value:\s*\$?([\d,]+(?:\.\d+)?)/);
  if (match) return parseFloat(match[1].replace(/,/g, ''));
  const revMatch = content.match(/Revenue:\s*\$?([\d,]+(?:\.\d+)?)/);
  if (revMatch) return parseFloat(revMatch[1].replace(/,/g, ''));
  const valMatch = content.match(/Value:\s*\$?([\d,]+(?:\.\d+)?)/);
  if (valMatch) return parseFloat(valMatch[1].replace(/,/g, ''));
  return 0;
}

// ─── CLI Entry Point ─────────────────────────────────────────────────────────

async function main() {
  const { Grid } = require('./reference/store.js');
  const grid = new Grid();
  const period = process.argv[2] || '';

  try {
    const qbr = await generate(grid, { period });
    console.log(JSON.stringify(qbr, null, 2));
  } catch (err) {
    console.error(JSON.stringify({ error: err.message }, null, 2));
    process.exit(1);
  }
}

if (require.main === module) {
  main();
}

module.exports = { generate, parsePeriod };
