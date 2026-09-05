# Stage 4B data-ownership cutover and legacy retirement

Status: HISTORICAL. This is the preceding Stage 4B schema-v5 ownership and
recovery record. The current schema-v6 storage-lifecycle evidence is
[`stage4b-data-lifecycle-v1.md`](stage4b-data-lifecycle-v1.md). This handoff
superseded the schema-v4 operating instructions; those documents remain
historical evidence.

## Objective and result

PRs `#107`–`#109` completed the accepted architecture in ADR-0014:

- Stages 1–4A own `wallet-intelligence.sqlite3`.
- Stage 4B is the sole runtime writer of `continuous-shadow.sqlite3`.
- latency telemetry remains isolated in
  `wallet-intelligence-latency.sqlite3`.
- Stage 4B reads a short, coherent, versioned Stage 3 snapshot and records its
  protected membership, provenance, and digest atomically in its own store.
- stale selection stops new exposure while exits, marks, and settlement
  continue.
- schema-v5 lease and fencing state is local; no old lease was migrated.

The solution remains one Python modular monolith with local SQLite. It adds no
queue, RPC, network hop, PostgreSQL service, or microservice.

## Delivery identity

- Merged implementation/cleanup commit:
  `dbb19c262dc6e28aa4872ac24682104356ffb2f7`.
- Release directory:
  `/opt/polysia-releases/dbb19c262dc6e28aa4872ac24682104356ffb2f7`.
- Deployment archive SHA-256:
  `7e3655adbb144e3d65990987d47ad086af696a1f6eff56a42823314dbfac3ac2`.
- Image ID:
  `sha256:728a96684679a1f7a979c9bd69d9e7ac860a151c1d78d467cee6992be329f8fd`.
- The active symlink, container image, and embedded `BUILD_COMMIT` were checked
  against that exact commit.

## Migration and recovery evidence

The three pre-retirement backups are:

| Store | Backup | SHA-256 |
|---|---|---|
| Intelligence | `wallet-intelligence-20260902T053846108697Z.sqlite3` | `0608f2b6895dae3d5dd744ebe92cd5e4297f76da87fa4168f41127f97429815b` |
| Stage 4B | `continuous-shadow-20260902T054800842182Z.sqlite3` | `599e3d9805d4bf7611be0f347075b4fe60c036631a1c27b7e7868c6b8064c997` |
| Telemetry | `wallet-intelligence-latency-20260902T055516138250Z.sqlite3` | `997bf56303ba8217863f0cd0cca23ee1d7a284dbd06fde678278cd1de3203b5f` |

The exact `dbb19c2` image restored all three into disposable same-volume state
with networking disabled. Checksums and SQLite integrity passed. The restored
Intelligence database contained seven source snapshots and 13,007 snapshot
rows. The restored Stage 4B database was schema v5 with one experiment, 7,305
polls, 31,782 journal events, 9,241 Ledger rows, and a balanced Ledger. The
telemetry restore was schema v1 with 46,550 spans and 45,365 measurements.

After successful schema-v5 operation, all Wallet Intelligence writers were
stopped. The guarded repository script
`deploy/migrations/retire_legacy_continuous_shadow_v1.sql` verified schema v4
and zero running legacy polls, then removed only the 15 remaining
`continuous_shadow_*` objects from the Intelligence database. It did not
vacuum or remove frozen latency tables. Stage 1–4A counts were identical before
and after retirement, SQLite integrity was `ok`, and foreign-key violations
were zero.

## Post-retirement operational verification

The persistent worker started at `2026-09-02T10:42:04Z` with
`TRADING_MODE=DATA_ONLY`, `LIVE_TRADING_ENABLED=false`, and `NRestarts=0`.
Its first seven completed polls succeeded. The first recovered the intentional
maintenance gap; the following normal polls also succeeded. Current evidence
showed:

- schema v5 and a current local lease/fencing row;
- fresh Stage 3 selection with 145 candidates;
- `ledger_balanced=true`;
- `duplicate_processing_count=0`;
- 33,060 cumulative unique events and 96,225 cumulative evaluations;
- 454 modeled open positions;
- 205 fresh, 249 stale, and zero missing marks;
- 54 genuine settlement-backlog items.

Two natural Stage 4A Forward runs started while the Stage 4B worker was active
and completed successfully. The first evaluated 45 events, simulated 42,
recorded three unknowns, and observed zero rate limits. The second evaluated
and simulated 162 events with zero unknowns and zero rate limits. Neither
encountered a shared financial database lock. Daily and ten-minute timers
remain enabled.

The health level remains `warning` because of stale marks, a settlement backlog,
and evidence-quality limits. At the recorded check, modeled follower results
were negative: MIXED_BASELINE NAV `351.7393353866637098368054431`, Alpha NAV
`700.4289725743583050063696578`, and Stress NAV
`603.0899284145514982003539397`, each from a synthetic starting NAV of 1,000.
These are low-confidence modeled observations, not profit or Live-readiness
claims.

The existing monitor remained healthy on its prior image. The unrelated
`3x-ui` container retained identity `ab567d6d...`, start time
`2026-08-21T10:33:56Z`, and restart count zero. No Live service, signing path,
or real-order path was enabled or run.

## Rollback and retained history

The old `47ce25decb811bed79a89786875f27fb5b742d73` release and image tag remain
available, and the verified pre-retirement backups are retained. Because schema
v5 has progressed, never point the old worker at frozen schema-v4 state. To
roll back: stop the Stage 4B worker, preserve all current files, then either
restore the explicit cutover checkpoint as one coherent rollback or explicitly
abandon the post-cutover Shadow evidence. Silent partial rollback would create
a state fork and is prohibited.

Encrypted off-host backup remains unavailable. Local checksummed backups and
disposable restore rehearsal are the current recovery mechanism. This is an
operational limitation, not authorization to weaken retention or safety.
