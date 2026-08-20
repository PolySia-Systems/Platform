# Before and After

> **Historical comparison:** this document records the 2026-07-11 Phase I
> transition. Its dependency versions, test counts, CI matrix, environment,
> and audit state are preserved as historical evidence. Use
> [PROJECT_STATUS](../../00-governance/PROJECT_STATUS.md) and the
> [architecture overview](../../04-architecture/overview.md) for current truth.

| Area | Preserved baseline | PolySia delivery |
|---|---|---|
| Repository | Working code inside `Polymarket Python SDK`; invalid external Git worktree pointer | Honest local Git repository on `main`; legacy folder still retained and ignored |
| Identity | Distribution/import/CLI `pm_trader` / `pm-trader` | Canonical distribution, namespace, and CLI `polysia`; no active legacy import or command |
| Runtime | `polymarket` environment had a broken editable-project path | Separate verified `PolySia` environment; exact Windows Conda/pip snapshots; old environment retained |
| Architecture | Venue details and CLI helpers were broadly coupled | Venue-neutral domain/application ports, consolidated Polymarket adapter, CLI support modules, separate acceptance models/renderers |
| Polymarket SDK | Official beta SDK used without one documented boundary | `polymarket-client==0.1.0b11` pinned; imports confined to adapter; contract and rollback tests/docs |
| Test evidence | 328 passing tests concentrated mainly in unit tests | 351 tests collected across unit, property, integration, architecture, contract, migration, and characterization layers |
| Delivery controls | No current CI/pre-commit/supply-chain foundation | Windows CI matrix, pre-commit, tracked-file secret scan, Dependabot, build gate, SBOM; local vulnerability audit pending network access |
| Realistic validation | Existing live-oriented tools and historical evidence | Authenticated read-only, paper, local shadow, and public real-data shadow passed; no unauthorized live mutation |

All twelve baseline capabilities in the capability catalog remain represented.
Public discovery/streaming, normalized events, Decimal order books, SQLite,
strategies, independent risk and kill switch, paper execution/PnL,
authenticated account reads, guarded live tooling, reconciliation, observability,
and delivery automation are preserved. The migration adds boundaries and tests;
it does not connect strategies to live execution or broaden live authority.
