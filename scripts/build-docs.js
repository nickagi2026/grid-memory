#!/usr/bin/env node
'use strict';
const fs = require('fs');
const path = require('path');
const { marked } = require('marked');

const docsDir = path.resolve(__dirname, '..', 'docs');

function headingId(text) {
  return text.toLowerCase()
    .replace(/[^\w\s-]/g, '')
    .replace(/[\s]+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '')
    .trim();
}

const renderer = new marked.Renderer();
renderer.heading = function({ text, depth }) {
  const id = headingId(text);
  return `<h${depth} id="${id}">${text}</h${depth}>`;
};
marked.use({ renderer });

const devMd = fs.readFileSync(path.join(docsDir, 'COMPREHENSIVE_GUIDE.md'), 'utf-8');
const businessMd = fs.readFileSync(path.join(docsDir, 'MIKE_BUSINESS_GUIDE.md'), 'utf-8');

const devHtml = marked.parse(devMd);
const businessHtml = marked.parse(businessMd);

function extractToc(md) {
  const lines = md.split('\n');
  const items = [];
  for (const line of lines) {
    const m = line.match(/^(#{2,4})\s+(.+)/);
    if (m) {
      const depth = m[1].length;
      const text = m[2].replace(/\*\*/g, '').replace(/`/g, '').trim();
      items.push({ depth, text, id: headingId(text) });
    }
  }
  return items;
}

const devToc = extractToc(devMd);
const bizToc = extractToc(businessMd);

// Build sidebar: Overview + Layer groups
const sidebarLinks = [];

// Static overview section
sidebarLinks.push({ html: `<div class="sidebar-section">Overview</div>` });
sidebarLinks.push({ html: `<a href="#overview" class="slink">System Overview</a>` });
sidebarLinks.push({ html: `<a href="#layer-1-memory-engine" class="slink">Layer 1: Memory Engine</a>` });
sidebarLinks.push({ html: `<a href="#layer-2-governance" class="slink">Layer 2: Governance</a>` });
sidebarLinks.push({ html: `<a href="#layer-3-intelligence" class="slink">Layer 3: Intelligence</a>` });
sidebarLinks.push({ html: `<a href="#quick-start-reference" class="slink">Quick Start Reference</a>` });

// Engine + Governance TOC (from developer guide, sections 1-10)
sidebarLinks.push({ html: `<div class="sidebar-section" style="margin-top:12px;">Layer 1 &amp; 2 — Developer Guide</div>` });
for (const item of devToc) {
  const indent = (item.depth - 2) * 16;
  sidebarLinks.push({ html: `<a href="#${item.id}" class="slink" style="padding-left:${20 + indent}px;font-size:${item.depth === 2 ? '14px' : '13px'};font-weight:${item.depth === 2 ? '600' : '400'};">${item.text}</a>` });
}

// Intelligence TOC (from business guide)
sidebarLinks.push({ html: `<div class="sidebar-section" style="margin-top:12px;">Layer 3 — Intelligence Guide</div>` });
for (const item of bizToc) {
  const indent = (item.depth - 2) * 16;
  sidebarLinks.push({ html: `<a href="#${item.id}" class="slink" style="padding-left:${20 + indent}px;font-size:${item.depth === 2 ? '14px' : '13px'};font-weight:${item.depth === 2 ? '600' : '400'};">${item.text}</a>` });
}

function renderSidebar(links) {
  return links.map(l => l.html).join('\n');
}

// The overview section as HTML
const overviewHtml = `
<!-- ─── Overview ─── -->
<div class="overview-section" id="overview">
  <h2>System Overview</h2>
  <p>Grid Memory is a single product with three layers. Each layer builds on the one below it. You can use just Layer 1, or all three — they work together out of the box.</p>

  <div class="layer-cards">
    <div class="layer-card" onclick="document.getElementById('layer-1-memory-engine').scrollIntoView({behavior:'smooth',block:'start'})">
      <div class="layer-num">1</div>
      <div class="layer-name">Memory Engine</div>
      <div class="layer-desc">Append-only, tamper-evident storage for multi-agent teams. Write decisions, facts, observations. Query with relevance-weighted retrieval. TTL-based expiry. Context injection for subagents.</div>
      <div class="layer-cta">Go to Layer 1 →</div>
    </div>
    <div class="layer-card" onclick="document.getElementById('layer-2-governance').scrollIntoView({behavior:'smooth',block:'start'})">
      <div class="layer-num">2</div>
      <div class="layer-name">Governance</div>
      <div class="layer-desc">Contracts, constitutions, federation, and security. Schema enforcement, natural-language policies, cross-Grid sync, PII detection, HMAC audit trails, API key management.</div>
      <div class="layer-cta">Go to Layer 2 →</div>
    </div>
    <div class="layer-card" onclick="document.getElementById('layer-3-intelligence').scrollIntoView({behavior:'smooth',block:'start'})">
      <div class="layer-num">3</div>
      <div class="layer-name">Intelligence (MIKE)</div>
      <div class="layer-desc">Business intelligence derived from memory. Opportunity engine, decision graph, QBR generator, amnesia detector, client intelligence, executive dashboard.</div>
      <div class="layer-cta">Go to Layer 3 →</div>
    </div>
  </div>

  <h3 style="margin-top:3em;">What Should I Read?</h3>
  <table>
    <tr><th>You Are</th><th>Start With</th></tr>
    <tr><td>Developer integrating the API</td><td><a href="#1-why-this-exists">Layer 1: Memory Engine</a></td></tr>
    <tr><td>DevOps setting up security</td><td><a href="#6-memory-contracts-schema-enforcement">Layer 2: Governance</a></td></tr>
    <tr><td>Executive wanting business insights</td><td><a href="#1-what-is-mike">Layer 3: Intelligence (MIKE)</a></td></tr>
    <tr><td>Consultant delivering QBRs</td><td><a href="#9-qbr-intelligence">Layer 3: QBR Intelligence</a></td></tr>
    <tr><td>Just evaluating the product</td><td><a href="#3-installation--step-by-step">Installation →</a> then <a href="#4-your-first-5-minutes">First 5 Minutes →</a></td></tr>
  </table>
</div>

<!-- ─── Layer 1 ─── -->
<div class="section-divider" id="layer-1-memory-engine">
  <h2>Layer 1: Memory Engine</h2>
  <p>The core — append-only, relevance-weighted, TTL-managed storage</p>
</div>

<!-- ─── Layer 2 ─── -->
<div class="section-divider" id="layer-2-governance">
  <h2>Layer 2: Governance</h2>
  <p>Contracts, constitutions, federation, security, and audit</p>
</div>

<!-- ─── Layer 3 ─── -->
<div class="section-divider" id="layer-3-intelligence">
  <h2>Layer 3: Intelligence (MIKE)</h2>
  <p>Opportunity engine, decision graph, QBR, dashboards, amnesia detection</p>
</div>

<!-- ─── Quick Start ─── -->
<div class="section-divider" id="quick-start-reference">
  <h2>Quick Start Reference</h2>
  <p>Install, write, query — in 60 seconds</p>
</div>
`;

// Inject layer dividers into the dev HTML so the TOC anchors match
// We inject them at strategic positions within the dev content
let layeredDevHtml = devHtml;

// Insert layer-1-memory-engine anchor before "Why This Exists"
layeredDevHtml = layeredDevHtml.replace('<h2 id="1-why-this-exists">', '<h2 id="1-why-this-exists" class="first-after-layer">');

// Insert layer-2-governance anchor before "Memory Contracts"
layeredDevHtml = layeredDevHtml.replace('<h2 id="6-memory-contracts-schema-enforcement">', '<div class="layer-inline-divider" id="layer-2-governance-anchor"></div><h2 id="6-memory-contracts-schema-enforcement">');

// Insert layer-3-intelligence anchor before the business guide content (already has section divider)
// Quick-start-reference anchor goes before "Quick Reference Card"

const html = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Grid Memory — Complete Guide</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --bg: #0f1117;
    --bg-card: #1a1c25;
    --bg-code: #15171e;
    --border: #2d2f3a;
    --text: #e2e8f0;
    --text-dim: #8892a4;
    --accent: #63b3ed;
    --accent2: #68d391;
    --accent3: #f6ad55;
    --accent4: #fc8181;
    --link: #63b3ed;
    --heading: #f7fafc;
    --code-bg: #1e2030;
  }

  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.7;
    font-size: 16px;
  }

  /* ─── Sidebar ─── */
  #sidebar {
    position: fixed; top: 0; left: 0; bottom: 0; width: 280px;
    background: var(--bg-card);
    border-right: 1px solid var(--border);
    overflow-y: auto; z-index: 100;
    padding: 0 0 40px;
  }
  #sidebar::-webkit-scrollbar { width: 4px; }
  #sidebar::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }

  #sidebar .logo {
    padding: 24px 20px 16px;
    border-bottom: 1px solid var(--border);
    margin-bottom: 8px;
    font-size: 20px; font-weight: 700;
    color: var(--accent);
    letter-spacing: 1px;
    background: linear-gradient(180deg, rgba(99,179,237,0.08) 0%, transparent 100%);
    position: sticky; top: 0; z-index: 2;
  }
  #sidebar .logo small {
    display: block; font-size: 10px; font-weight: 500;
    color: var(--text-dim); letter-spacing: 2.5px;
    text-transform: uppercase;
    margin-top: 4px;
  }

  .sidebar-section {
    padding: 12px 20px 4px;
    font-size: 10px; font-weight: 700; text-transform: uppercase;
    letter-spacing: 1.5px; color: #556;
    margin-top: 8px;
  }

  .slink {
    display: block;
    padding: 3px 16px 3px 20px;
    color: #a0aec0;
    text-decoration: none;
    font-size: 13px;
    font-weight: 400;
    border-left: 2px solid transparent;
    transition: all 0.15s;
  }
  .slink:hover {
    color: #63b3ed !important;
    border-left-color: #63b3ed !important;
    background: rgba(99,179,237,0.05);
  }

  /* ─── Main Content ─── */
  #content {
    margin-left: 280px;
    padding: 40px 60px 100px;
    max-width: 880px;
  }

  /* ─── Typography ─── */
  h1, h2, h3, h4 { color: var(--heading); line-height: 1.3; }
  h1 { font-size: 2.2em; font-weight: 800; margin: 0.6em 0 0.3em; letter-spacing: -0.02em; }
  h2 { font-size: 1.5em; font-weight: 700; margin: 2em 0 0.6em; padding-bottom: 0.3em; border-bottom: 2px solid var(--border); letter-spacing: -0.01em; }
  h3 { font-size: 1.15em; font-weight: 600; margin: 1.5em 0 0.5em; }
  h4 { font-size: 1em; font-weight: 600; margin: 1.2em 0 0.4em; color: var(--accent); }
  p { margin: 0.8em 0; }
  a { color: var(--link); text-decoration: none; }
  a:hover { text-decoration: underline; }
  strong { color: var(--heading); }
  em { color: var(--accent2); }
  ul, ol { margin: 0.6em 0 0.6em 1.5em; }
  li { margin: 0.3em 0; }
  hr { margin: 2em 0; border: none; border-top: 1px solid var(--border); }

  blockquote {
    border-left: 3px solid var(--accent); padding: 12px 20px; margin: 1em 0;
    background: rgba(99,179,237,0.06); border-radius: 0 8px 8px 0;
    color: var(--text-dim); font-style: italic;
  }
  blockquote strong { color: var(--accent); }

  code {
    font-family: 'SF Mono', 'Fira Code', 'monospace'; font-size: 0.88em;
    background: var(--code-bg); padding: 2px 7px; border-radius: 4px; color: #e6d8b5;
  }
  pre {
    background: var(--bg-code); border: 1px solid var(--border); border-radius: 8px;
    padding: 16px 20px; margin: 1em 0; overflow-x: auto; line-height: 1.5;
  }
  pre code { background: none; padding: 0; font-size: 0.85em; color: #e2e8f0; }

  table { width: 100%; border-collapse: collapse; margin: 1em 0; font-size: 0.94em; }
  th, td { padding: 10px 14px; border: 1px solid var(--border); text-align: left; }
  th { background: var(--bg-card); color: var(--heading); font-weight: 600; font-size: 0.92em; letter-spacing: 0.3px; }
  td { background: rgba(26,28,37,0.5); }
  tr:hover td { background: rgba(99,179,237,0.03); }

  /* ─── Overview Section ─── */
  .overview-section { margin-bottom: 2em; }
  .overview-section h2 { font-size: 1.8em; border: none; text-align: center; margin-bottom: 0.5em; }
  .overview-section > p { text-align: center; color: var(--text-dim); max-width: 600px; margin: 0 auto 2em; }

  .layer-cards { display: flex; gap: 20px; margin: 2em 0; }
  .layer-card {
    flex: 1; background: var(--bg-card); border: 1px solid var(--border);
    border-radius: 12px; padding: 24px; cursor: pointer;
    transition: all 0.2s; position: relative; overflow: hidden;
  }
  .layer-card:hover {
    border-color: var(--accent); transform: translateY(-2px);
    box-shadow: 0 8px 24px rgba(99,179,237,0.1);
  }
  .layer-num {
    width: 40px; height: 40px; border-radius: 10px;
    display: flex; align-items: center; justify-content: center;
    font-size: 18px; font-weight: 800; margin-bottom: 12px;
  }
  .layer-card:nth-child(1) .layer-num { background: rgba(99,179,237,0.15); color: var(--accent); }
  .layer-card:nth-child(2) .layer-num { background: rgba(104,211,145,0.15); color: var(--accent2); }
  .layer-card:nth-child(3) .layer-num { background: rgba(246,173,85,0.15); color: var(--accent3); }
  .layer-name { font-size: 16px; font-weight: 700; color: var(--heading); margin-bottom: 8px; }
  .layer-desc { font-size: 13px; color: var(--text-dim); line-height: 1.5; margin-bottom: 12px; }
  .layer-cta { font-size: 12px; font-weight: 600; color: var(--accent); }

  /* ─── Section Dividers ─── */
  .section-divider {
    margin: 5em 0 3em;
    padding: 2.5em 0;
    border-top: 3px solid var(--accent);
    border-bottom: 3px solid var(--accent);
    text-align: center;
    background: linear-gradient(90deg, transparent, rgba(99,179,237,0.05), transparent);
  }
  .section-divider h2 {
    border: none; margin: 0 0 8px; color: var(--accent); font-size: 1.8em;
  }
  .section-divider p {
    color: var(--text-dim); font-size: 14px; margin: 0; letter-spacing: 1px;
  }
  .section-divider:nth-of-type(2) { border-color: var(--accent2); }
  .section-divider:nth-of-type(2) h2 { color: var(--accent2); }
  .section-divider:nth-of-type(3) { border-color: var(--accent3); }
  .section-divider:nth-of-type(3) h2 { color: var(--accent3); }

  .layer-inline-divider { height: 1px; margin: 3em 0; }

  /* ─── Header ─── */
  .gm-header {
    text-align: center; padding: 40px 0 20px;
    border-bottom: 1px solid var(--border); margin-bottom: 30px;
  }
  .gm-header .title { font-size: 36px; font-weight: 800; color: var(--accent); letter-spacing: 2px; padding: 20px 0 4px; }
  .gm-header .subtitle { color: var(--text-dim); font-size: 13px; letter-spacing: 2px; text-transform: uppercase; margin-top: 8px; }

  @media (max-width: 900px) {
    .layer-cards { flex-direction: column; }
  }

  @media print {
    #sidebar { display: none; }
    #content { margin-left: 0; padding: 20px 30px; max-width: none; }
    body { background: white; color: #111; font-size: 11pt; }
    pre { background: #f5f5f5 !important; border-color: #ddd; }
    code { background: #f5f5f5 !important; color: #333 !important; }
    table { border-color: #ccc; }
    th, td { border-color: #ccc; }
    th { background: #f0f0f0; }
    td { background: white; }
    a { color: #1a56db; }
    h1, h2, h3, h4 { color: #111; }
    strong { color: #111; }
    blockquote { border-left-color: #1a56db; background: #f8faff; }
    blockquote strong { color: #1a56db; }
    .section-divider { border-color: #1a56db; background: none; }
    .section-divider h2 { color: #1a56db; }
    .section-divider p { color: #666; }
    .section-divider:nth-of-type(2) { border-color: #1a56db; }
    .section-divider:nth-of-type(2) h2 { color: #1a56db; }
    .section-divider:nth-of-type(3) { border-color: #1a56db; }
    .section-divider:nth-of-type(3) h2 { color: #1a56db; }
    .layer-card { break-inside: avoid; border-color: #ddd; }
    .layer-num { background: #f0f0f0 !important; color: #333 !important; }
    h2 { page-break-after: avoid; }
    h3 { page-break-after: avoid; }
    pre, table { page-break-inside: avoid; }
  }

  @media (max-width: 768px) {
    #sidebar { display: none; }
    #content { margin-left: 0; padding: 20px; }
  }
</style>
</head>
<body>

<nav id="sidebar">
  <div class="logo">
    Grid Memory
    <small>Three Layers · One Product</small>
  </div>
  ${renderSidebar(sidebarLinks)}
</nav>

<div id="content">

<div class="gm-header">
  <div class="title">Grid Memory</div>
  <div class="subtitle">Layer 1: Memory Engine · Layer 2: Governance · Layer 3: Intelligence</div>
</div>

${overviewHtml}

${layeredDevHtml}

${businessHtml}

</div>

<script>
document.querySelectorAll('a[href^="#"]').forEach(function(a) {
  a.addEventListener('click', function(e) {
    var id = this.getAttribute('href').slice(1);
    var target = document.getElementById(id);
    if (target) {
      e.preventDefault();
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  });
});
</script>
</body>
</html>`;

const outPath = path.join(docsDir, 'MIKE_COMPLETE_GUIDE.html');
fs.writeFileSync(outPath, html, 'utf-8');
console.log('Written: ' + outPath);
console.log('Size: ' + (Buffer.byteLength(html) / 1024).toFixed(0) + ' KB');
