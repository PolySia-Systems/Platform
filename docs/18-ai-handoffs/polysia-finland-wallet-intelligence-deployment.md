# Finland Wallet Intelligence DATA_ONLY Deployment Handoff

## Outcome

PolySia repository baseline
`c0a3747c2112437ebe232da4ff274b8025ad6ad0` is deployed on
`Hetzner-Finland-Helsinki-01` as an immutable release. Monitor and Wallet
Intelligence Stages 1–4 are active only in `DATA_ONLY`/Shadow. No real order,
cancellation, transfer, fill, position, fee, or other external mutation was
created by this deployment.

`LIVE_TRADING_ENABLED=false`, the Live token allowlist is empty, and no Copy
authorization or acknowledgement exists. The dynamic handoff can prepare the
legacy runner's protected input, but it cannot authorize Live or call Strategy,
Risk, Execution, a signer, or a venue adapter.

## Delivery

- PR `#80`: Dynamic all-market Stage 4.
- PR `#81`: protected dynamic pre-Live handoff.
- PR `#82`: genuinely read-only handoff and valid systemd documentation URIs.
- PR `#83`: candidate position pagination through the official maximum offset.
- PR `#84`: persistent protected scratch for large backup restore rehearsal.
- Deployed release archive SHA-256:
  `263f8e15bdb57c1c2d199b50342ca98eddaea92a3698e5a1334b4128f82d4409`.
- GitHub repository Deploy Keys are disabled. Deployment therefore used a
  workstation-generated exact-commit `git archive`, matching SHA-256 on both
  ends, an immutable `/opt/polysia-releases/<commit>` tree, and an atomic
  `/opt/polysia` symlink. No write-capable GitHub credential is on the host.

## Runtime evidence

- Monitor: healthy, non-root, read-only root filesystem, no published port.
- Configuration: ready and redacted; `TRADING_MODE=DATA_ONLY` and Live false.
- Source: 21 pages and 2,022 PolyCop wallets.
- Stage 2: 2,022 current candidate rows.
- Stage 3: Alpha 50, Stress 100, one overlap, five rejected, 1,868 Watchlist,
  and zero Live-review candidates.
- Seven-day Historical Stage 4: 149 unique candidates; 22,368 events; 21,115
  simulated; 1,253 unknown; zero rejected; zero rate limits; circuit closed.
- Natural ten-minute Forward timer: succeeded repeatedly with rate limits zero.
- Dynamic handoff: 119 qualified; exact 102 published; Alpha 30, Stress 73,
  one overlap; address-free manifest; file mode `0600`, directory mode `0700`.
- One-cycle authenticated runner smoke:
  `DRY_RUN_BOUNDED_COMPLETE`, zero attempts, zero mutation, source available,
  authenticated stream probe passed, geoblock allowed, rate limits zero.

Historical and Forward PnL values are model output under explicit fee,
slippage, delay, and liquidity assumptions. They are not realized profit and
are not a promotion decision.

## Automation

- Stages 1–3: daily at 03:15 UTC with bounded randomized delay.
- Seven-day Historical Stage 4: daily at 04:00 UTC with bounded randomized
  delay.
- Forward Stage 4: every ten minutes.
- Dynamic runtime-bank handoff: operator-only one-shot, no timer.

All three timers are enabled. The same persistent fenced pipeline lease prevents
concurrent Stage 1–4 publication. Failure preserves last-known-good database,
Stage 3 selection, Stage 4 evidence, and candidate bank.

## Backup, restore, and rollback

- Base backup:
  `polysia-20260824T212818971921Z.sqlite3`, SHA-256
  `759e17110dc9de99251303ba364f598c4e69d50dca57eda5e44015f8d3ad4130`.
- Wallet Intelligence backup:
  `wallet-intelligence-20260824T212830190738Z.sqlite3`, SHA-256
  `14a42e4148e7d21f1dc9d01be8894127efcdba136f08444f1e4fa1fece78552b`.
- Base restore: integrity `ok`, 33 tables, disposable file removed.
- Wallet restore: 2,022 source rows, 2,022 Stage 2 pool rows, 155 Stage 3
  memberships, eight Stage 4 runs, and 47,225 Stage 4 evaluations; protected
  scratch automatically removed.
- Rollback release and image for the preceding deployed baseline were verified
  readable without network. The current symlink can be atomically returned to
  that release; persistent state must not be deleted.

Backups remain on the same host. Encrypted off-host backup is still required for
host-loss recovery.

## Issues found and resolved during deployment

1. Repository initialization attempted to chmod the read-only handoff mount.
   The first attempt failed safely; the write-oriented call was removed and
   regression-tested.
2. One candidate exceeded the former 2,500-position baseline bound. Pagination
   now honors the official `/positions` contract through offset 10,000 and still
   fails closed beyond it.
3. The 69.7 MiB Wallet Intelligence restore exceeded the 64 MiB tmpfs. Restore
   now uses automatically cleaned protected persistent scratch beside the
   backup.

## Unrelated-service preservation

The `3x-ui` container inspect digest remained
`78bb4b8773f758a0ed7b0a0537f60eb1369da9d58bbd4bc9310513001fba53bc`,
its restart count remained zero, and its original start time did not change.
The UFW rules digest remained
`885076fe126a5c48fa68bc5f8dee984169396a52608c43a1fb1aceaa9e9fcb56`.
PolySia publishes no host port.

## Remaining limitations and next gate

- Generic all-market Live Copy is not implemented or authorized. The protected
  handoff feeds the existing exact-102, BTC 15-minute bounded runner only.
- `LIVE_REVIEW_CANDIDATE` remains empty.
- One successful dry-run and one seven-day modeled window are insufficient for
  profitability or production-readiness claims.
- External alert delivery, encrypted off-host backup, high availability, and
  branch protection remain open.

The next gate is continued DATA_ONLY/Shadow observation and evidence review.
Any Tiny-Live requires a new explicit run-specific authorization, exact green
commit, fresh protected bank, clean authenticated preflight, and every existing
Risk/Execution/reconciliation gate.
