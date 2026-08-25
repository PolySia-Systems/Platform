# Wallet Intelligence Stage 4B Continuous Shadow Handoff

## Verified outcome

Stage 4B Continuous Shadow Portfolio v0.2 is merged and deployed on
`Hetzner-Finland-Helsinki-01` at exact runtime commit
`d39f5b355b1d83ed2019a93c6647b8ceb1572e5f`. PRs `#86` and `#87` delivered the
durable experiment and restore evidence; PR `#88` completed cumulative reporting
and schema-v3 health evidence. The later `main` commit `596e820` changes only
Standards adoption, governance documentation, and its validator; it does not
change the deployed runtime.

- Release archive SHA-256:
  `ac14f90c758b5ed76eea70205805a56a1bd58aa6720aa6580dbbb4ab260751cd`.
- Image identity:
  `sha256:16f15c9883ae1c49ce97b2445cd5bae3c6a41a7aa1413059ddba6e61f77847b2`.
- Experiment: `71e7622c8a6e472f847d212b78099903`.
- Policy and bankroll versions: `continuous-shadow-policy-v0.2` and
  `synthetic-bankroll-v0.2`.
- External mode: public GET reads and protected local SQLite writes only.
- Runtime safety: `TRADING_MODE=DATA_ONLY`; `LIVE_TRADING_ENABLED=false`.
- No order, cancellation, transfer, approval, signature, fill, account position,
  or other external trading mutation was created by Stage 4B.

## Implemented boundary

Stage 4B is additive to Stage 4A. It supplies a durable first-seen event journal,
incremental checkpoint, one persistent synthetic portfolio per Wallet, one shared
PolySia follower, per-leader attribution, capital and conflict limits,
non-reused liquidity, partial-fill evidence, official market fee schedules,
cross-run exits, verified 0/1 settlement, Decimal ledger reconciliation,
interval-aware health, and `RUNNING -> DRAINING -> FINALIZED` lifecycle.

All output is address-free. Protected addresses remain inside the existing
wallet-intelligence identity tables and are passed only in memory to the official
read adapter. Stage 4B imports no Execution, Risk, strategy, wallet, signing,
cancellation, transfer, or order-authority module.

## Repository verification

- PR `#88` merged only after GitHub CI run `32802499713` passed its required
  quality and aggregate gates.
- Local final validation: Standards PASS, compileall PASS, Ruff PASS, Mypy PASS
  across 171 source files, 815 Pytest tests PASS, pip check PASS, secret scan
  PASS, package build PASS, locked-environment pip-audit PASS, CycloneDX SBOM
  generation PASS, and `git diff --check` PASS.
- A complete security diff review covered all five changed production files and
  reported zero security findings.

## Migration, backup, restore, and rollback

The transactional and idempotent Stage 4B v2-to-v3 migration preserved the
existing experiment and every prior financial record. Stage 4A remains schema
v1 and was not changed.

- Final pre-migration v2 backup:
  `wallet-intelligence-20260825T174143168987Z.sqlite3`, SHA-256
  `7e1b6eae0423550a8c4999f01f89e8a341fcf9f4f3b844226f241c0e5e014e45`.
- Immediate post-migration v3 backup:
  `wallet-intelligence-20260825T174324724805Z.sqlite3`, SHA-256
  `8d15e83ec74732ef8c8eb8c7080ad5100b18f4ee71147344c1d5a2a4a5a458a5`.
- Final post-recovery v3 backup:
  `wallet-intelligence-20260825T175130849077Z.sqlite3`, SHA-256
  `2a6ee317ca48250ed20cb9a0baeb44e2902795409f709ec494c06187cb809408`.
- Every backup passed checksum, SQLite integrity, foreign-key, schema, and
  disposable restore validation.
- A real rollback restored the v2 backup and ran the prior
  `f5e1f33956b338eb3a5e3f59204353eba44c0e60` image successfully. A real
  rollforward restored the v3 backup and returned to `d39f5b3`; event, poll,
  ledger, portfolio, and experiment counts were preserved.

Schema-v3 rollback therefore disables the Stage 4B timer, restores the verified
v2 backup, and then starts the v2 image. Switching code alone intentionally
fails closed on the unsupported schema.

## Observation and recovery evidence

The initial uninterrupted observation ran for 5,464 seconds (more than 90
minutes). It recorded 54 unique source events, 108 portfolio evaluations, 29
overlap duplicates, zero duplicate processing, two settlements, and 89
successful polls. The Decimal ledger balanced. The follower's then-current
marked result was partial because executable marks were unavailable for some
positions; it was not presented as verified profit or loss.

An operator-workflow interruption after the intentional migration pause left
the timer enabled but inactive from 03:00 UTC until recovery at 17:47 UTC. No
financial state was lost. The first recovery poll resumed from the durable
watermark and captured 1,271 backlog events, but 1,270 became `UNKNOWN` because
fresh copyable book evidence no longer existed. This is correct fail-safe
classification, not a profitability observation. Subsequent natural polls had
zero UNKNOWN results, zero rate limits, no retry/circuit event, and continued
from the restored checkpoint.

The verified post-recovery cumulative state at 17:50 UTC was:

- 1,336 unique source events and 2,672 portfolio evaluations;
- 34 overlap duplicates and zero duplicate processing;
- 38 simulated, 15 rejected, and 1,289 UNKNOWN unique events;
- 10 settlements; six follower closes: one winning and five losing;
- 30 open synthetic positions; four follower positions without fully current
  executable marks; no settlement backlog and no unknown fee provenance;
- follower cash `814.7341927380302912217805834`, NAV
  `926.9590215763384692908168136`, modeled partial total P&L
  `-73.04097842366153070918318634`, fees `5.20722`, exposure
  `118.6270650793650793650793651`, and drawdown
  `0.0730409784236615307091831864`;
- Alpha modeled total P&L `-57.80810`; Stress modeled partial total P&L
  `-23.099574710924403337909473`;
- ledger balanced and duplicate-processing count zero. The Decimal identity
  delta was `-1E-25`, within stored Decimal representation, while valuation
  remained explicitly `INCOMPLETE_MARKS`.

These values are synthetic Shadow evidence, not realized account P&L. Confidence
is `LOW` because the run is shorter than 24 hours, the recovery backlog dominates
the cumulative UNKNOWN ratio, and some marks are not fully current.

## Runtime verification

- The Stage 4B one-minute timer is enabled and active. Stage 4A and daily Wallet
  Intelligence timers remain active.
- A manual catch-up service run and subsequent timer-started runs completed with
  `Result=success`, proving persisted restart recovery.
- The monitor was recreated on the exact deployed image and is healthy with no
  published port.
- `3x-ui` remained container
  `ab567d6d3f4ed7246e13459cfabd58387e413f900dcb693dc2a26a44dba76bb2`,
  image `sha256:652ef431a2d351cfcc7b5dc91798de5c1dd50da8c1b44f9e3afee1c60817035e`,
  start time `2026-08-21T10:33:56.972826114Z`, and restart count zero.

## Before/after finding status

- **FIXED:** durable global deduplication, checkpoint recovery, cross-run state,
  Decimal accounting, settlement, pool-separated reporting, processing status,
  settlement backlog, schema migration, backup/restore, rollback/rollforward,
  restart recovery, rate-limit telemetry, and honest incomplete valuation.
- **FIXED:** the interrupted timer was restarted and the backlog recovered
  without duplicate processing or state loss. The runbook now requires operators
  to verify both enabled and active timer state after maintenance.
- **NEEDS MORE DATA:** profitability, stable win/loss distribution, observed
  partial fills, sufficient closed-position evidence, complete current marks,
  and a representative UNKNOWN ratio after uninterrupted operation.
- **NOT FIXED:** external alert delivery and encrypted off-host backup remain
  separate operational work. Local health correctly detects stale polling but
  cannot notify an operator by itself.

## Next gate

Leave the experiment running in DATA_ONLY and evaluate the bounded 24-hour
follow-up. Do not use the current negative, partial, backlog-distorted sample for
Live selection. Any Tiny-Live still requires a separate explicit authorization,
fresh official Polymarket verification, copyability evidence, Risk/Execution
gates, and reconciliation.
