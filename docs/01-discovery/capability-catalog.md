# Baseline Capability Catalog

This catalog is a baseline non-live inventory. It is not current product
truth for Wallet Intelligence, Stage 4B, or later DATA_ONLY work. Use
[`docs/README.md`](../README.md) and
[`PROJECT_STATUS.md`](../00-governance/PROJECT_STATUS.md) for CURRENT state.

| ID | Capability | Current stage | Preservation gate |
|---|---|---|---|
| CAP-001 | Public market discovery and realtime stream | Foundation | Adapter and stream tests |
| CAP-002 | Normalized events and in-memory bus | Foundation | Unit and integration path |
| CAP-003 | Decimal order book and microstructure | Foundation | Arithmetic/property tests |
| CAP-004 | SQLite repositories | MVP | Temporary-database integration tests |
| CAP-005 | Strategy framework and research strategies | Research | Paper-only boundary tests |
| CAP-006 | Independent pre-trade risk and kill switch | Foundation | Negative and invariant tests |
| CAP-007 | Paper execution, position, and P&L | MVP | Deterministic replay tests |
| CAP-008 | Authenticated Polymarket account adapter | Limited live | Contract/read-only tests |
| CAP-009 | Guarded submit/cancel and tiny-live tooling | Experimental | Dry-run, allowlist, geoblock, one-attempt tests |
| CAP-010 | Reconciliation and manual-intervention detection | MVP | Mismatch and pause tests |
| CAP-011 | Observability, readiness, and operator reports | MVP | Sanitized golden tests |
| CAP-012 | Deployment and handoff automation | Foundation | Build/install and no-live checks |

Future multi-market, Web3, DeFi, copy-trading, advanced portfolio, institutional
infrastructure, and operations-console capabilities are inventory items, not
commitments in the current modernization.

