# Shared Data and Continuous Shadow Acceptance — 2026-09-27

This is dated operational evidence for the owner-authorized Helsinki
`DATA_ONLY` run. Query the host for current health. No Live mode, real order,
credential use, or trading-account mutation was authorized or performed.
The unrelated `3x-ui` container was left running.

## Repository delivery

| PR | Merge SHA | Result |
|---|---|---|
| [#170](https://github.com/PolySia-Systems/Platform/pull/170) | `b8b820a7db0efa00c4b5655b74a6bf534d06a201` | Trustworthy bounded Wallet feed ingestion |
| [#171](https://github.com/PolySia-Systems/Platform/pull/171) | `8962c43520e5142f0b6048125a9986ad53326f52` | Fee-correct Paper Risk and recorded CLI economics |
| [#172](https://github.com/PolySia-Systems/Platform/pull/172) | `380b13f2477d8e6feda14511691574a4fddc4cb1` | Shared bounded v2 ingestion and source benchmark |
| [#173](https://github.com/PolySia-Systems/Platform/pull/173) | `b450b521a9c504d82d717aaf9146b5843e1f0864` | Causal Shadow opportunities, schema v8, frozen runtime periods |
| [#174](https://github.com/PolySia-Systems/Platform/pull/174) | `f2446cc7c9190d72cee27064e16602117d1d7e9b` | Compose and systemd runtime Spec wiring |
| [#175](https://github.com/PolySia-Systems/Platform/pull/175) | `b24d974809a47b14cb9b4e02c75bce9cf5257568` | Preserve Research v2 Spec runtime in the CLI loader |
| [#176](https://github.com/PolySia-Systems/Platform/pull/176) | `f5491133a17dfa8a84574c9fa73663ff28eb18a5` | Align current schema references with v8 |
| [#177](https://github.com/PolySia-Systems/Platform/pull/177) | `c07e04ff6da1094b9d87c82eabba9ead3543aac4` | Freeze three ranked Alpha wallets from the 148-member Stage 3 Shadow cohort; block new exposure on selection-read failure |
| [#178](https://github.com/PolySia-Systems/Platform/pull/178) | `08a387d62be856047a593c931600863d550c1548` | Run systemd Spec readability precheck as file owner |

All nine PRs merged with green required CI gates. CI runs for #170 and #171
were `36254869071` and `36256418056`; runs for #172–#176 were
`36281681524`, `36312957271`, `36314834174`, `36317319662`, and
`36323633382`; #177 and #178 were `36331687971` and `36332495598`.
The Windows Compatibility and supply-chain jobs skipped when the changed-file
classifier deemed them inapplicable; this is not a claim that they ran.

## Public source and Research evidence

- The 600-second source benchmark on the earlier green `f2446cc7…` image was
  `VALID`. Three public aliases and eight market tokens produced 138 matched
  unambiguous activity/trades identities per per-wallet route, with no
  incomplete, duplicate, gap, or unmatchable identities. The global route had
  57 incomplete attempts and zero accepted intervals, so it was not promoted.
  Report: `/var/lib/polysia/reports/source-benchmark-20260927b.json`.
- A first Canary was stopped after an incorrect custom state root conflicted
  with the container healthcheck. Its failure archive remains preserved and
  supplies no valid result. The corrected 20-minute Canary on exact image
  `f5491133…`, run `a4888cd57dd84affbf9631b9db70402f`, closed with two
  `VALID` windows and technical `PASS`. It had 10 eligible observations
  against 20 required and executable-evidence coverage `0.40` against `0.90`
  required. Six observations were `UNKNOWN` (four missing depth, two missing
  fee); economics is `INSUFFICIENT_DATA`. Two canonical replay outputs matched
  SHA-256 `9a0f09cd91bbe7a799486e95b5c3e4712de6282c28870ce73f32beed8c915792`.
  Verified bundle SHA-256:
  `90744785d96a4250b86e9df1da51282dd475d574f26592e1519b5c3b958e7655`.
- The owner explicitly authorized a bounded exploratory four-hour run despite
  this unmet data gate. That exception does not revise the standard Canary
  threshold, turn an insufficient result into `PASS`, or permit promotion.
  Main run `1de56e3e20ba442abb7977e059f04a03` started at approximately
  `2026-09-27T15:45:05Z` on the same `f5491133…` image. Its frozen T0 is
  `2026-09-27T15:45:39.791258Z`, collection deadline and valuation cutoff
  `2026-09-27T19:45:39.791258Z`, and limits 24 ten-minute windows,
  750,000 events, and 768 MiB. It remained `DATA_ONLY`. At the deadline,
  24 collection windows closed `VALID`, with zero persisted Wallet events.
  The required Trades and Activity routes ended with successful empty reads;
  the optional market stream had not started. The latest health report was
  `stale` because no event was persisted, while required-source research
  eligibility remained true. These facts do not establish upstream event
  completeness.
- The Runner closed `2026-09-27T19:45:39Z` with `technical=FAIL`,
  `evidence=INSUFFICIENT_ACTIVITY`, and `economic=INSUFFICIENT_DATA`. There was
  no valid **event-bearing** interval, so the canonical bundle lifecycle is
  `COLLECTED->ANALYSIS_FAILED->FAILURE_ARCHIVED`, `bundle_verified=false`.
  The archive is retained at
  `/var/lib/polysia/research-run/bundles/research-experiment-1de56e3e20ba442abb7977e059f04a03-failure`
  with database SHA-256
  `6c2009227e42a052e742bfbfabf2f1f6d67f929038e260acd1de419e73191aa3`.
  `systemd` exited successfully; that process result does not override the
  Runner's technical gate.
- Two independent canonical `prospective-replay` calls on the archived database
  produced byte-identical reports, each SHA-256
  `1566699b6ffa57031eff818eccb9953dd1c7a42dd74d68f5fe62862f1e0dc65d`.
  The replay result hash was
  `734d30fa1a2f2147eb1d09518c7f96d3da50d70097d503500281fa271ca06ac6`:
  zero eligible, evaluated, and unknown observations, execution-evidence ratio
  zero, and Control and Target net P&L both zero. These are empty-sample
  results, not a profitable or valid economic comparison. The reports do not
  turn the failure archive into a verified bundle.

## Continuous Shadow and recovery

- The exact `08a387d62be856047a593c931600863d550c1548` archive and image
  were checksum/build-identity checked (archive SHA-256
  `189c579c78f7aa3817d9c41f670a19a18e595f40fa697d58813f4f99ceb423fb`,
  image ID `sha256:48218ab6d12cdf517021fac6743a90916cc5a3d4fb8d23d590511e3e453d11f2`);
  container health reported `DATA_ONLY`,
  `live_trading_enabled=false`, and `live_trading_allowed=false`. The host
  release symlink and root-owned image pin select that SHA. The earlier
  `f2446cc7…`, `f5491133…`, and `c07e04f…` release/image history was retained.
- Current Stage 3 offered 50 Alpha wallets among 148 distinct Shadow members.
  The frozen three-wallet derived selection was started as Stage 4B experiment
  `0e63c6bf990b4d9394e09fefc7d68c87` at `2026-09-27T16:22:37Z`.
  A preceding `c07e04f…` experiment had no poll, position, or pending
  observation; it was formally drained and finalized before changing image
  SHA. The older record was preserved.
- At `2026-09-27T20:22:53Z`, the worker rolled over its first four-hour
  period and began experiment `557802211afd4f028c9e4a1c320e58bd` without
  a service restart. At `20:48:53Z` it was still active with `NRestarts=0`,
  successful polls, a `healthy` artifact, fresh selection, balanced ledger,
  zero duplicate processing, no failure code, zero events, zero evaluations,
  and zero open positions. This proves bounded runtime continuity but supplies
  no economic evidence. The worker is read-only-rootfs with all Linux
  capabilities dropped; no trading authority is in its command. Query the host
  for later state.
- The daily Stage 1–3 timer was re-enabled after the Research Runner closed.
  Its next scheduled activation was `2026-09-28T03:17:01Z`. The Stage 4A
  ten-minute timer remains uninstalled; this continuous service is Stage 4B
  polling on the frozen three-wallet selection, with Stage 3 daily refresh.
- An online three-store recovery bundle was created under
  `/var/lib/polysia/wallet-intelligence/backups/bundle-20260927T162435574452Z`.
  The official restore check passed for Wallet, Shadow schema v8, and latency;
  Shadow ledger was balanced. The complete seven-file bundle was copied to
  `C:\Users\Siamak\Documents\PolySia-backups\helsinki-f5491133-20260927`
  as `three-store-20260927T162435574452Z.tar.aesgcm`. Its source tar SHA-256
  was `cf8c2d14fb755095c7af4608ef467050b4b6dacb5cf31445e06ac3e647ce0445`;
  the encrypted file SHA-256 was
  `ea8eaeb1b073277eb9d26f44b18eec817f1281ae212fec33063d58c8e82597ab`.
  Decryption from the off-host copy reproduced that SHA; all three extracted
  SQLite files returned `integrity_check=ok` and no foreign-key violations.
  Plaintext restore-test copies were removed. The same destination retains
  the encrypted Canary bundle and the recovery helper.
- After the four-hour close, an online three-store backup was published as
  `bundle-20260927T204517190313Z`. Canonical `restore-check` passed Wallet,
  latency, and Shadow schema v8 with a balanced ledger, three Shadow
  experiments, 263 polls, and zero Shadow events. The complete bundle was
  encrypted off-host as `three-store-20260927T204517190313Z.tar.aesgcm` in
  the same Windows destination. The source tar SHA-256 was
  `3b5e16c802a064f4582ced411aa79bde41dc29fa925db8abc786d2e05d00a545`;
  encrypted-file SHA-256 was
  `420809e5983d1418a060ef9fa05097aaaff6689454f8fa915626fb4f4c0dc3e1`.
  Off-host decryption reproduced the source SHA and each extracted SQLite
  file passed integrity and foreign-key checks. Disposable plaintext was
  removed.
- The stopped Main root, failure archive, 24 window reports, manifest,
  receipts, and both canonical analyses were encrypted off-host as
  `main-1de56e3e20ba442abb7977e059f04a03-final.tar.aesgcm`. Source tar
  SHA-256 was
  `97eadc7cad8fafc93a44fa67f465d65fa13feb28e9c614d8c83bf10aacb7f7d4`;
  encrypted-file SHA-256 was
  `33a7bf458e30d2a5f3c5861ae4631ccd6e940b4933bfee9c2050199a8727d255`.
  Off-host decryption reproduced the source SHA and tar listing; disposable
  plaintext was removed.

The off-host format is AES-256-GCM with a random key wrapped by Windows DPAPI
CurrentUser. Recovery requires this Windows user profile; losing that profile
loses the wrapped key. This was a verified one-off transfer, not an automated
backup schedule. External alert delivery also remains unconfigured.

## Gate verdicts and next prerequisites

| Gate | Verdict | Evidence |
|---|---|---|
| Repository implementation through #178 | PASS | Merged green CI; final documentation closeout is a separate PR. |
| Source benchmark | PASS for the per-wallet route only | Matched 138 identities; global route remained incomplete. |
| Twenty-minute Canary | Technical PASS; data gate FAIL | Two valid windows, 10/20 eligible, 0.40/0.90 execution evidence. |
| Four-hour Research Main | Technical FAIL; economics INSUFFICIENT_DATA | 24 valid empty windows, no replayable event-bearing interval, failure archive unverified. |
| Continuous Shadow runtime at observed time | HEALTHY, no economic result | Period rollover without restart; zero events and evaluations. |
| Off-host recovery | PASS for the one-off tested copies | Final Research and three-store encrypted transfers verified; recurring transfer absent. |
| Next standard DATA_ONLY economic experiment | BLOCKED | A fresh Canary must meet frozen eligible-count, mapping, and executable-evidence thresholds and yield a verified replayable bundle; source activity and market evidence must be present. A separately authorized exploratory run can still be recorded as exploratory. |
| Profitability and Live promotion | NOT ESTABLISHED / BLOCKED | No measured economic sample or Live authorization. |

This is a data and evidence limitation with an explicit technical gate failure,
not a reason to stop the healthy Continuous Shadow service. Investigate the
selected-wallet activity and upstream/source-market evidence before any new
standard economic experiment. Do not relax frozen thresholds or reuse the
empty sample as a success.
