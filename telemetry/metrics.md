# Telemetry — Shared Memory Grid Metrics

## Collected Metrics (Local Only, No External Sending)

| Metric | Source | Purpose |
|--------|--------|---------|
| `total_entries` | info() | Store health |
| `alive_entries` | info() | Active memory count |
| `expired_entries` | info() | Pruning effectiveness |
| `unique_agents` | info() | Cross-agent utilization |
| `unique_tags` | info() | Tag diversity |
| `store_size_kb` | info() | Disk usage |
| `writes_per_session` | Internal count | Write frequency |
| `reads_per_session` | Internal count | Read frequency |
| `prunes_per_session` | Internal count | Maintenance frequency |
| `injections_per_session` | Internal count | Context injection frequency |
| `expired_filtered` | Read result | Query filtering efficiency |
| `truncation_count` | Inject result | Context injection truncation |

## What Metrics Are NOT Collected

- Entry content (never leaves the store file)
- Agent communication patterns
- User identity or workspace details
- Any data that could reconstruct what was stored

## No External Telemetry

The Grid sends zero data to any external service. Every metric is derived from local file operations. There are no analytics hooks, no beacon calls, and no network dependencies.

The `telemetry/` directory exists for documentation and future local observability only.
