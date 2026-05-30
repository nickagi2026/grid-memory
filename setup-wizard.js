#!/usr/bin/env node
/**
 * setup-wizard.js — Frictionless UX: Setup Wizard
 *
 * Provides an interactive wizard that checks if the Grid has been configured
 * and returns guided setup steps for new users.
 *
 * Functions:
 *   wizard(grid)          — returns wizard steps if Grid needs setup
 *   applyConfig(steps, grid?) — takes wizard answers and auto-configures
 *
 * Endpoints:
 *   POST /setup-wizard    — check or run setup
 */

'use strict';

const constitution = require('./constitution.js');
const contracts = require('./contracts.js');
const seedMode = require('./seed-mode.js');

/**
 * Check if the Grid has been configured (async — awaits grid.info()).
 */
async function isConfigured(grid) {
  const info = await grid.info();
  const consts = constitution.listConstitutions();
  const hasConstitution = Object.keys(consts || {}).length > 0;
  const existingContracts = contracts.listContracts();
  const hasContracts = existingContracts.length > 0;
  const hasEntries = (info.total_entries || 0) > 0;

  return {
    configured: hasEntries || hasConstitution || hasContracts,
    hasEntries,
    hasConstitution,
    hasContracts,
  };
}

/**
 * Return wizard steps for a fresh Grid.
 */
async function wizard(grid) {
  const status = await isConfigured(grid);

  if (status.configured) {
    return {
      needs_setup: false,
      configured: true,
      status,
      message: 'Grid is already configured. Use individual endpoints to add more rules.',
    };
  }

  return {
    needs_setup: true,
    status,
    steps: [
      {
        id: 'purpose',
        question: 'What are you building?',
        description: 'This helps us set up the right memory structure and templates.',
        options: [
          'Agent team coordination',
          'Decision tracking',
          'Knowledge management',
          'Compliance/audit',
        ],
      },
      {
        id: 'agents',
        question: 'How many agents will write to this Grid?',
        description: 'Determines memory tier sizing and concurrency settings.',
        options: ['1\u20135', '5\u201320', '20+'],
      },
      {
        id: 'compliance',
        question: 'Do you need compliance/audit features?',
        description: 'Enables PII scanning, immutable audit logs, and governance tracking.',
        options: [
          'No',
          'Yes \u2014 HIPAA',
          'Yes \u2014 SOC2',
          'Yes \u2014 custom',
        ],
      },
    ],
  };
}

/**
 * Apply wizard configuration answers.
 * @param {Object} answers — { purpose, agents, compliance }
 * @param {Object} [grid] — optional Grid instance (needed for seeding)
 * @returns {Object} — configuration summary
 */
async function applyConfig(answers, grid) {
  if (!answers || typeof answers !== 'object') {
    throw new Error('answers object is required');
  }

  const config = {
    purpose: answers.purpose || 'Agent team coordination',
    agents: answers.agents || '1\u20135',
    compliance: answers.compliance || 'No',
  };

  const results = {
    constitutionRules: [],
    memoryTiers: [],
    demoData: false,
    featuresEnabled: [],
  };

  // ── Configure constitution rules based on purpose ──
  const constitutionRules = [];

  switch (config.purpose) {
    case 'Agent team coordination':
      constitutionRules.push('All handoffs must include context');
      constitutionRules.push('Never store API keys in content');
      constitutionRules.push('All blockers must include resolution path');
      results.featuresEnabled.push('handoff tracking', 'blocker management');
      results.memoryTiers = ['session', 'project'];
      break;

    case 'Decision tracking':
      constitutionRules.push('All decisions must include rationale');
      constitutionRules.push('All decisions must include alternatives');
      constitutionRules.push('Never include PII in content');
      results.featuresEnabled.push('ADR tracking', 'rationale enforcement');
      results.memoryTiers = ['project', 'organization'];
      break;

    case 'Knowledge management':
      constitutionRules.push('All facts must include source');
      constitutionRules.push('Never store API keys in content');
      constitutionRules.push('All entries must include at least one topic tag');
      results.featuresEnabled.push('knowledge base', 'provenance tracking');
      results.memoryTiers = ['session', 'project', 'organization'];
      break;

    case 'Compliance/audit':
      constitutionRules.push('All decisions must include rationale');
      constitutionRules.push('Never include PII in content');
      constitutionRules.push('Don\'t include credentials in content');
      constitutionRules.push('All entries must include source attribution');
      results.featuresEnabled.push('audit trail', 'PII scanning', 'immutable logging');
      results.memoryTiers = ['organization', 'permanent'];
      break;

    default:
      constitutionRules.push('All decisions must include rationale');
      results.featuresEnabled.push('basic governance');
      results.memoryTiers = ['project'];
  }

  // ── Configure based on agent count ──
  switch (config.agents) {
    case '1\u20135':
      results.memoryTiers = results.memoryTiers.filter(t => t !== 'permanent');
      break;
    case '5\u201320':
      results.featuresEnabled.push('conflict detection');
      break;
    case '20+':
      results.featuresEnabled.push('conflict detection', 'reputation scoring', 'subscription filtering');
      if (!results.memoryTiers.includes('permanent')) {
        results.memoryTiers.push('permanent');
      }
      break;
  }

  // ── Configure compliance features ──
  switch (config.compliance) {
    case 'No':
      break;
    case 'Yes \u2014 HIPAA':
      constitutionRules.push('Never include PHI in content');
      results.featuresEnabled.push('PHI scanning (block mode)');
      break;
    case 'Yes \u2014 SOC2':
      constitutionRules.push('All decisions must include rationale');
      constitutionRules.push('Never include credentials in content');
      results.featuresEnabled.push('audit trail enforcement', 'access logging');
      break;
    case 'Yes \u2014 custom':
      constitutionRules.push('All entries must include compliance tags');
      results.featuresEnabled.push('custom compliance rules');
      break;
  }

  // ── Register the constitution rules ──
  if (constitutionRules.length > 0) {
    const register = constitution.registerConstitution(
      'default',
      constitutionRules,
      'validate'
    );
    results.constitutionRules = constitutionRules;
    results.constitutionRegistered = register.registered;
  }

  // ── Seed demo data if appropriate ──
  const shouldSeed = config.purpose !== 'Compliance/audit';
  results.demoData = shouldSeed;
  results.demoDataEnabled = shouldSeed;

  // Actually seed if grid is available (await ensures seed completes before returning)
  if (shouldSeed && grid && typeof grid.write === 'function') {
    try {
      const seedResult = await seedMode.seedGrid(grid);
      results.demoData = seedResult.seeded;
      results.demoEntryCount = seedResult.entry_count || 0;
    } catch (e) {
      results.demoData = false;
      results.demoError = e.message;
    }
  }

  return {
    configured: true,
    config,
    results,
    summary: `Configured Grid for "${config.purpose}" with ${constitutionRules.length} constitution rules, ${results.memoryTiers.length} memory tiers, and ${results.featuresEnabled.length} features enabled.`,
  };
}

module.exports = { wizard, applyConfig, isConfigured };
