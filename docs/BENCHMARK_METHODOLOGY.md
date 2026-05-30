# GRID-BENCH Methodology

## Overview

GRID-BENCH is an open benchmark for evaluating multi-agent memory systems. Unlike LOCOMO (which tests single-user temporal recall), GRID-BENCH measures what actually breaks in production multi-agent deployments.

## Why GRID-BENCH?

Existing benchmarks (LOCOMO, MEMO, etc.) measure single-agent, single-session recall. They do not measure:
- Coordination between multiple agents writing to shared state
- Detection and containment of contradictory or malicious entries
- Data integrity through export/import cycles
- Resilience to cascade contamination

GRID-BENCH fills this gap.

## Test Definitions

### coordinationAccuracy (threshold: 80/100)
Three agents write entries to a shared tag scope. A fourth agent queries the same scope. Score = overlap between retrieved entries and expected entries. A perfect score means all three agents' entries are retrieved.

### conflictDetectionRate (threshold: 30/100)
Five contradictory pairs are seeded in the store (ten total entries). The staleness detector scans for contradictions. Score = percentage of involved entries flagged as having contradictions. Low bar (30%) because word-overlap-based contradiction detection is intentionally conservative.

### cascadeContainment (threshold: 100/100)
A poisoned entry is written and cascaded through three descendant entries via parent_entry. The source is recalled. Score = percentage of descendant entries marked as contaminated. Must be 100% — partial containment is a security failure.

### recoveryFidelity (threshold: 95/100)
Five entries with diverse field values are written to a Grid instance. The store is exported, cleared, and re-imported. Field-level comparison between original and recovered entries across all schema fields. Score = percentage of fields matching.

## Scoring
Each test returns a 0-100 score. Tests at or above their threshold are PASS. Average across all tests is the overall score.

## Future
- Full GRID-BENCH specification as an open standard
- Reference implementations for other memory systems (Mem0, Zep, Letta)
- Multi-node federation benchmarks

---

## Related Documents

- [Benchmark Results](BENCHMARKS.md) — Throughput and latency benchmarks
- [GRID-BENCH Results](GRID_BENCH.md) — Full benchmark results
