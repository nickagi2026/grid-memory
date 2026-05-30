# GRID-BENCH Results

Generated: 2026-05-30T01:02:29.208Z

## Summary

| Metric | Value |
|--------|-------|
| Average Score | 100/100 |
| Tests Passing | 4/4 |

## Individual Results

| Test | Score | Status |
|------|-------|--------|
| coordinationAccuracy | 100/100 | ✓ |
| conflictDetectionRate | 100/100 | ✓ |
| cascadeContainment | 100/100 | ✓ |
| recoveryFidelity | 100/100 | ✓ |

### Test Descriptions

1. **coordinationAccuracy** — 3 agents write to a shared topic, a 4th retrieves consensus. Score based on entry overlap.
2. **conflictDetectionRate** — 5 contradictions are seeded at known positions. Measures detection rate via staleness analysis.
3. **cascadeContainment** — A poisoned entry cascades through 3 agents. Measures recall coverage when the source is recalled.
4. **recoveryFidelity** — Full export → clear → re-import. Measures field-level round-trip accuracy (>95% target).
---

## Score Explanation

All scores are out of 100. The pass threshold is 60. Scores below 60 indicate the system failed that benchmark category.

## Related Documents

- [Benchmark Results](BENCHMARKS.md) — Throughput and latency benchmarks
- [Benchmark Methodology](BENCHMARK_METHODOLOGY.md) — How the benchmarks work

---

## Score Interpretation

All scores are out of 100. The pass threshold is 60.

| Score Range | Meaning |
|-------------|---------|
| 90–100 | Excellent |
| 75–89 | Good |
| 60–74 | Adequate (passes) |
| Below 60 | Fails — needs improvement |

Each benchmark includes:
- **Raw score**: The actual measurement
- **Pass threshold**: Minimum acceptable score (60)
- **Dataset size**: Number of entries used in the test
- **Methodology**: Link to [BENCHMARK_METHODOLOGY.md](BENCHMARK_METHODOLOGY.md)

*Benchmarks generated automatically. Results may vary by hardware configuration.*
