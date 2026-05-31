# Grid Memory — Route Inventory

## Registry-Protected (34 routes)

| Method | Path | Permission | Rate Limit |
|--------|------|-----------|-----------|
| GET | /roi | analyst | 30/min |
| GET | /mike/dashboard | analyst | 20/min |
| GET | /executive/dashboard | analyst | 10/min |
| GET | /decisions/graph | analyst | 20/min |
| GET | /decisions/stats | analyst | 20/min |
| GET | /qbr | analyst | 15/min |
| POST | /qbr/generate | analyst | 15/min |
| GET | /amnesia/detect | analyst | 15/min |
| POST | /setup-wizard | admin | — |
| GET | /staleness | analyst | 20/min |
| GET | /drafts | architect | 20/min |
| GET | /provenance/:id | analyst | 30/min |
| GET | /cascade/:id | analyst | 20/min |
| GET | /explain/:id | analyst | 20/min |
| POST | /constitution | architect | — |
| DELETE | /constitution | architect | — |
| POST | /constitution/from-text | admin | — |
| GET | /auto-contracts/state | analyst | — |
| POST | /auto-contracts/approve | admin | — |
| POST | /auto-contracts/reject | admin | — |
| GET | /auto-contracts | analyst | 20/min |
| POST | /prune | admin | — |
| DELETE | /forget/:id | admin | — |
| GET | /export | architect | — |
| POST | /import | admin | — |
| POST | /seed | admin | — |
| POST | /federation/quick-connect | admin | — |
| POST | /contracts | architect | — |
| DELETE | /contracts/:scope | architect | — |
| GET | /agents/reputation | analyst | — |
| POST | /federation/peers | admin | — |
| GET | /federation/peers | analyst | — |
| DELETE | /federation/peers/* | admin | — |
| POST | /federation/sync/* | admin | — |

## Manual / Gateway-Protected

| Method | Path | Notes |
|--------|------|-------|
| POST | /gateway/key/create | admin auth |
| GET | /gateway/keys | admin auth |
| DELETE | /gateway/key/revoke/:id | admin auth |
| POST | /gateway/pii/scan | admin auth |
| GET | /gateway/audit | admin auth |
| GET | /gateway/audit/verify | admin auth |

## Public / Static

| Method | Path | Notes |
|--------|------|-------|
| GET | /health | Always public |
| GET | /info | Public read |
| POST | /write | Core operation |
| GET/POST | /query | Core operation |
| GET/POST | /inject | Core operation |
| GET | /dashboard/* | Static HTML |

## Enterprise-Only (Returns 402 in Community)

| Method | Path |
|--------|------|
| GET | /mike/dashboard |
| GET | /executive/dashboard |
| GET | /qbr |
| POST | /qbr/generate |
