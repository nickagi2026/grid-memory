# Grid Memory — Benchmarks

## API Throughput (JSON file store)

| Operation | Concurrency | Throughput | Notes |
|-----------|-------------|-----------|-------|
| Write | Sequential | ~89 ops/sec | 500 entries, async serial |
| Read | Sequential | ~500 ops/sec | tag-scoped AND query |
| Score All | Sequential | 10 agents/59ms | 500 entries, O(n) single pass |
| Subscription Publish | In-memory | ~100k/sec | 100 concurrent publishes |
| Federation Register | Sequential | ~393/sec | 50 peers with shared secrets |
| Federated Peer List | Sequential | <1ms | 50 peers, secrets excluded |

## GRID-BENCH Results

| Test | Score | Purpose | Threshold |
|------|-------|---------|-----------|
| coordinationAccuracy | 100/100 | N-agent multi-writer consensus | ≥80 |
| conflictDetectionRate | 100/100 | Contradiction seed detection | ≥30 |
| cascadeContainment | 100/100 | Poison entry + descendant recall | =100 |
| recoveryFidelity | 100/100 | Export→import field accuracy | ≥95 |

Benchmark methodology: docs/BENCHMARK_METHODOLOGY.md

---

## Related Documents

- [Benchmark Methodology](BENCHMARK_METHODOLOGY.md) — How the benchmarks work
- [GRID-BENCH Results](GRID_BENCH.md) — Full benchmark results
