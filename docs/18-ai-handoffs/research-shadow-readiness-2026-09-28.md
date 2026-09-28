# Research and Continuous Shadow Readiness — 2026-09-28

This is dated operational evidence from the owner-authorized Helsinki
`DATA_ONLY` release and bounded public-data checks. Query the host for current
state. No Live mode, order, trading-account mutation, Nuremberg access, or
`3x-ui` change was performed.

## Release and repository evidence

| PR | Merge commit | Purpose | CI |
|---|---|---|---|
| [#180](https://github.com/PolySia-Systems/Platform/pull/180) | `da5ac6f9fe632afd579dcf080e3074aaa32ae494` | Causal admission, matched Control replay, and diagnostic stages | [36360847049](https://github.com/PolySia-Systems/Platform/actions/runs/36360847049) |
| [#181](https://github.com/PolySia-Systems/Platform/pull/181) | `1be47988f8c7bebefeb31f0aa5bfa8ce189751a9` | Versioned 1–40 wallet software envelope, selection, readiness, and UI backend contracts | [36405839566](https://github.com/PolySia-Systems/Platform/actions/runs/36405839566) |
| [#182](https://github.com/PolySia-Systems/Platform/pull/182) | `621b3d6926f8358ad25a1770279e28cb57dc9bf4` | Defer the public market stream until discovered token IDs exist | [36412431074](https://github.com/PolySia-Systems/Platform/actions/runs/36412431074) |

The exact approved and installed code/image tag is
`621b3d6926f8358ad25a1770279e28cb57dc9bf4`. The verified release tar
SHA-256 is `395d8008ad24b7702f385fae52dfa352b21c25e168c33b1a015ec00df5cfd771`;
the built Docker image ID is
`sha256:efa8fc8c119dfe8dc9c5e115065c16738de4f6d46ac4191cff5efea44885e31b`.
The image's `BUILD_COMMIT` matched the tag. A network-isolated image health
check returned `DATA_ONLY`, `live_trading_enabled=false`, and
`live_trading_allowed=false`. The previous
`08a387d62be856047a593c931600863d550c1548` release and image were
retained for rollback.

## Public-data and capacity gate

- A 2026-09-28 10:23 UTC bounded four-hour-lookback preflight on the preceding
  `1be47988…` image read 50 SHADOW_ALPHA candidates: 44 inactive, four with
  observable recent activity, and two missing book/depth. It observed 59
  activity events across candidates. Only four candidates met the selection
  conditions. Its rough latest-token rate of 2.5 observable events/hour and
  eight hours for 20 events had **high uncertainty** and was not a forecast.
  Options 5/10/20/40 were `INSUFFICIENT_ACTIVE_CANDIDATES`; even one wallet
  had `INSUFFICIENT_OBSERVED_RATE`. This preflight was `PENDING_CAPACITY`.
- The approved new image ran a 90-second, ranked five-wallet candidate-only
  probe. Report:
  `/var/lib/polysia/reports/capacity-probe-5-90s-621b3d6.json`. It completed
  without timeout or source exception. Trades and Activity each reported
  complete available-page empty reads for all five wallets, zero parsed and
  eligible rows, and no rate limits. Their shared request telemetry reported
  370 Trades-route attempts, 115 other-route attempts, and at most 0.154
  seconds of scheduling delay. Do not add the duplicated shared telemetry in
  the two source-health views. The optional market source remained
  `not_started` because discovery found zero token IDs; the earlier empty-ID
  `ValueError` no longer occurred. It emitted zero events. `success_empty`
  describes the bounded available Data API v2 pages, not upstream completeness
  or future wallet inactivity.
- The new-image five-wallet active preflight returned
  `recent-active SHADOW_ALPHA candidates are insufficient` (sanitized stderr
  at `/var/lib/polysia/reports/preflight-5-621b3d6.stderr`). No matching
  operator-reviewed `wallet-capacity-v1` record exists. The 1–40 range is a
  **software envelope**; operationally validated capacity for a new v2
  workload is **none**. The five-wallet probe did not measure aggregate
  shared-IP consumers, total host memory/CPU, SQLite growth, or a nonempty
  market mix. Probes at 10/20/40, a standard Canary, and a four-hour economic
  run were not started after the five-wallet data gate failed. The frozen
  20-observation, 95% mapping, and 90% executable-evidence gates were not
  reduced. There is no new economic result or profitability evidence.

## Shadow cutover and recovery

- Before the change, the existing v1 three-wallet Shadow period
  `fb5f188f022548339bec5ef76951365d` was healthy, with zero positions and
  relevant pending observations. The worker was stopped, and the pre-migration
  three-store bundle `bundle-20260928T111726303233Z` passed disposable
  `restore-check`: Wallet schema 1, Shadow schema 8, latency schema 1, balanced
  ledger, and SQLite integrity. Its Shadow file SHA-256 was
  `eed20f1ee6ef52117d23312afe2b6debec83ab2f85cd9860ea90eeb228b51526`.
  That period was explicitly drained and finalized; its rows were retained.
- The release symlink, root-owned image pin, and private runtime Spec were
  atomically changed to the approved SHA. The runtime remains v1, ranked,
  three wallets, with the previous financial and source limits. The first
  worker start failed safely because the new period had not yet been created;
  systemd performed one restart. `portfolio-start` then created period
  `e561cea2823c4bc88791618aa954af15`, and the worker started successfully.
  This failed start is retained in the journal; the later `NRestarts=0` is
  after the explicit reset/start and does not erase that event.
- The post-migration three-store bundle
  `bundle-20260928T113014592896Z` passed `restore-check`: Shadow schema 9,
  seven retained experiments, 1,137 polls, zero Shadow events, balanced ledger,
  Wallet and latency schemas 1. Its Shadow file SHA-256 was
  `d0fa6e77ea2b8dc677b87d95a845ca8cafac94baaac24b7a99fe225412da738a`.
  Both exact bundles remain on the host. Their combined 20-entry tar was
  encrypted off-host at
  `C:\Users\Siamak\Documents\PolySia-backups\helsinki-621b3d6-20260928\cutover-pre-post-20260928.tar.aesgcm`.
  Plaintext SHA-256 was
  `3bea8fbd7dd8c9c47f7c337aaca7343c3b0c6a952738dccd30006dfeba9b15cf`;
  encrypted SHA-256 was
  `d269a58c1e8cd9177762d4384fb405d5fc211e00e17809ff717d6a6d9e46c0b6`.
  Off-host decryption reproduced the plaintext hash and tar entry count;
  disposable plaintext was removed. The key is DPAPI CurrentUser wrapped:
  recovery requires the same Windows user profile and the companion
  `.key.dpapi` file.
- At 2026-09-28 11:38 UTC, the installed Shadow image and release symlink
  matched `621b3d69…`; systemd was active, post-recovery `NRestarts=0`, the
  latest poll succeeded, health was `healthy`, ledger balanced, selection
  fresh, and positions, events, and evaluations were all zero. The Research
  Runner was inactive. `3x-ui` remained running and untouched. These are
  dated checks, not continuous guarantees.

Rollback after schema 9 requires stopping the new worker, preserving the
post-migration database and evidence, restoring the verified **pre-migration**
schema-8 three-store bundle, reverting the saved runtime Spec, image pin, and
release symlink, then starting and checking the old worker. Do not point the
old image at schema 9 or delete either bundle. Any post-backup polls require
an explicit evidence-retention decision before restore.

## Unresolved evidence and next gate

The 2026-09-27 four-hour Runner's zero persisted Wallet events remain
historically `UNKNOWN` in cause: saved reports do not prove whether the
selected cohort was inactive, upstream data was absent, or another cause
applied. The September 28 probe shows zero events during a **new** bounded
read and distinguishes complete available-page emptiness from an unstarted
market stream. It cannot retroactively classify the old run.

The daily Stage 1–3 timer succeeded at 2026-09-28 03:17 UTC but reported an
idempotent replay of the 2026-09-27 source snapshot; it did not publish a new
selection. If that snapshot exceeds the existing 36-hour freshness bound,
Shadow blocks new exposure while continuing safe handling of existing state.
The highest-value next action is to obtain a genuinely refreshed, sufficiently
active and observable candidate cohort, then repeat bounded preflight and
measure the full intended host workload before making an operational capacity
record. A standard Canary must pass unchanged data gates before a new formal
economic evaluation. No Live or real-order conclusion follows.
