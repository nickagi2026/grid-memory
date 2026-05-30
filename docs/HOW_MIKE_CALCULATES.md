# How MIKE Calculates Things

This document explains how every MIKE intelligence metric is calculated — so executives, consultants, and technical buyers can evaluate the methodology.

---

## ROI Calculation

**Endpoint:** `GET /roi`

ROI is calculated from actual Grid entries, not estimates:

| Component | How It's Calculated |
|-----------|-------------------|
| **Duplicates prevented** | Exact content match detection — entries with identical content (>20 chars) within the query window |
| **Contradictions detected** | Cross-agent decision analysis — same tag scope, different agents, opposing language patterns |
| **Opportunities found** | Keyword detection — entries containing "opportunity", "potential", "should consider/explore/evaluate" |
| **Time saved estimate** | `(duplicates × 15 min) + (contradictions × 30 min) + (opportunities × 10 min) + (decisions × 5 min) / 60 min/hr` |
| **Format** | Rounded to nearest 0.1 hours, minimum 0.5 hours/week |

Time estimates are conservative — they represent time MIKE saved by surfacing issues that would otherwise require manual discovery.

---

## Opportunity Score

**Endpoint:** `GET /mike/dashboard` (opportunities section)

```
priority = estimated_value × (confidence × stage_weight) / effort
```

| Factor | Range | Source |
|--------|-------|--------|
| **Estimated value** | $0–$1M+ | Extracted from content patterns ("Revenue:", "Value:", "Estimated Annual Value:") |
| **Confidence** | 0–100% | Evidence count (30%), pattern strength (25%), recency (20%), agent reputation (15%), outcome correlation (10%) |
| **Stage weight** | 0.3–0.9 | detected=0.3, reviewed=0.5, accepted=0.7, assessment=0.8, proposed=0.9 |
| **Effort** | hours | Estimated from similar projects in organizational memory |

### Stage Definitions

| Stage | Description |
|-------|-------------|
| **Detected** | Signal identified — MIKE found a potential opportunity |
| **Reviewed** | Human reviewed the opportunity signal |
| **Accepted** | Opportunity is real — worth pursuing |
| **Assessment** | Active evaluation — scope, value, effort being assessed |
| **Proposed** | Proposal delivered to client/stakeholder |
| **Won** | Opportunity converted to revenue |
| **Lost** | Opportunity declined or lost to competitor |

---

## Win Rate

**Endpoint:** `GET /mike/dashboard` (revenue section)

```
win_rate = won / (won + lost) × 100
```

Calculated from all entries with `tag: win-loss` and `result: won` or `result: lost` content patterns. Only includes opportunities that have reached a terminal stage (won or lost).

---

## Revenue Accuracy

**Endpoint:** `GET /mike/dashboard` (revenue section)

```
accuracy = actual_value / estimated_value × 100
```

Calculated from ROI tracking entries. When a won opportunity's actual revenue is tracked, MIKE compares it against the original estimate.

---

## Pipeline Value

**Endpoint:** `GET /mike/dashboard` (opportunities section)

```
pipeline_value = sum(estimated_value × stage_weight × age_factor for all open opportunities)
```

Pipeline value uses stage-weighted probability with age decay:

| Factor | Values | Source |
|--------|--------|--------|
| **Stage weight** | detected=0.1, reviewed=0.3, accepted=0.5, assessment=0.7, proposed=0.85, won=1.0, lost=0 | Stage of each opportunity in pipeline |
| **Age factor** | ≤180 days = 1.0, >180 days = 0.5 | Days since opportunity was created |

---

## Amnesia Score

**Endpoint:** `GET /amnesia/detect`

```
amnesia_score = gap_weight + orphan_weight + stale_weight + spof_weight + severity_bonus
```

| Component | Max Weight | How It's Calculated |
|-----------|-----------|-------------------|
| **Gaps** | 0.25 | Topics not referenced in 30+ days. Weight = min(gaps / total_entries × 5, 0.25) |
| **Orphans** | 0.25 | Decisions made without outcome tracking. Weight = min(orphans / total_decisions × 3, 0.25) |
| **Stale decisions** | 0.25 | Decisions >60 days old without review. Weight = min(stale / total_decisions × 3, 0.25) |
| **SPOFs** | 0.25 | Knowledge held by only one agent. Weight = min(spofs / total_entries × 5, 0.25) |
| **Severity bonus** | 0.20 | High-severity items add 0.05 each (max 0.20) |

Scores: < 0.3 = healthy, 0.3–0.6 = warning, > 0.6 = critical.

---

## Decision Success Rate

**Endpoint:** `GET /decisions/stats`

```
success_rate = successful_decisions / (successful + failed + partial) × 100
```

Based on decisions that have outcome data. Decisions without outcomes are excluded from the rate calculation but counted separately as "unmeasured."

### Decision Quality Factors

| Factor | Impact on Success Rate | Source |
|--------|----------------------|--------|
| Written rationale | +73% success | Historical decision-outcome correlation |
| Alternatives documented | +45% success | Compared to decisions without alternatives |
| Outcome tracked | 85% accountability rate | Audit trail verification |
| Undocumented decisions | 40% chance of reversal | Observed reversal patterns |

---

## Risk Scoring

**Endpoint:** `GET /executive/dashboard` (risks section)

```
risk_score = severity × probability × imminence
```

| Factor | Range | How It's Determined |
|--------|-------|-------------------|
| **Severity** | 0–10 | Business impact if risk materializes (extracted from content patterns) |
| **Probability** | 0–1 | Likelihood based on historical pattern analysis |
| **Imminence** | 0–1 | How soon it could materialize (recency-weighted) |

### Risk Categories

| Type | Criteria | Severity Basis |
|------|----------|---------------|
| **Amnesia** | Topic not discussed in 30+ days | Days since last reference / 30 |
| **Orphan** | Decision made >14 days without outcome | Days orphaned / 30 |
| **Stale** | Decision >60 days without review | Age / 60 |
| **SPOF** | Topic known by only one agent | Topic criticality (derived from reference frequency) |
| **Contradiction** | Two agents saying opposite things | Number of affected decisions |

---

## QBR Metrics

**Endpoint:** `GET /qbr`

QBR reports aggregate data from the analysis period:

| Metric | Source |
|--------|--------|
| **Decisions made** | Entries with type=decision within period |
| **Decisions with outcomes** | Entries with type=decision + linked outcome entries |
| **Win rate** | Won / (Won + Lost) from opportunity tracking |
| **Pipeline value** | Sum of open opportunity estimated values × stage weight |
| **Top decision-maker** | Agent with most decision entries × outcome success rate |
| **Most contentious topic** | Topic with most contradictions |
| **Amnesia score** | Current organizational amnesia score |

---

## Dashboard KPIs

**Endpoint:** `GET /mike/dashboard` (summary)

| KPI | Calculation |
|-----|-----------|
| **Total entries** | Count of all live (non-expired) entries |
| **Unique agents** | Distinct agent_id values across all entries |
| **Unique workspaces** | Distinct ws: tag values |
| **Oldest/newest entry** | Min/max created_at timestamps |

All metrics are computed from live data at request time. No caching, no pre-aggregation — you always see the current state.
