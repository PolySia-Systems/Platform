# Configurable DATA_ONLY Shadow readiness — 2026-09-29

This is dated Helsinki operational evidence. Query the host for current state.
The owner authorized the conditional path for exact release
`579f5c5d56ae38bfaa6321f39fcb0a973e26b18d`; the required data and
capacity gates did not pass. No Live mode, order, trading-account read or
mutation, Nuremberg access, or `3x-ui` change occurred.

## Recovery and release staging

- At 2026-09-28 20:44 UTC, the existing `621b3d6926f8358ad25a1770279e28cb57dc9bf4`
  image produced three-store bundle `bundle-20260928T204406230656Z`.
  `restore-check` succeeded on all three snapshots: Wallet schema 1, Shadow
  schema 9, latency schema 1, SQLite integrity, and balanced Shadow ledger.
  It restored 1,691 Shadow polls, nine retained experiments, and zero Shadow
  events. The Wallet, Shadow, and latency SHA-256 values were respectively
  `ecffaad0d6c0916ffde83242325cad09e53af273ae54577c5787a8c99a4c4787`,
  `1db957788417ad2565fc66d3528c6af43a103329a0aeee86dd286e84538615ac`,
  and `fea7548902b28b6cdd130d7f0e035ea224dceaaa0753c95fa4d096da7d7006f1`.
- The complete bundle was archived and encrypted off-host as
  `C:\Users\Siamak\Documents\PolySia-backups\helsinki-579f5c5-20260929\pre-deploy-three-store.tar.aesgcm`.
  The source tar SHA-256 was
  `eafd729d144d17ef52ed26d3b1f346f3771feadebdf0a5cf3cf264e5f5f5e07c`;
  encrypted SHA-256 was
  `470cff2db8a3ff38cb13020fba8e5672fff56c54a84a7b56eb9415fdce09a58f`.
  Off-host decryption reproduced the source hash and ten tar entries; the
  disposable plaintext was removed. The AES-GCM key is DPAPI CurrentUser
  wrapped and needs the same Windows user profile for recovery.
- A trusted Git archive of exact SHA `579f5c5…` was transferred in verified
  chunks after intermittent SSH resets. The uncompressed archive SHA-256 was
  `370691edc5769937b0d73b398ff740174867ab7e4084664e78e50b794846731a`.
  It was extracted into read-only
  `/opt/polysia-releases/579f5c5d56ae38bfaa6321f39fcb0a973e26b18d`.
  The tagged image ID is
  `sha256:374a92bfb7d4fd9cf0355fdaf7392ef29dffc9b8d6d536d5a9f12f18a9de4553`.
  Its `BUILD_COMMIT` matched the tag; an isolated image check returned
  `DATA_ONLY`, `live_trading_enabled=false`, and
  `live_trading_allowed=false`.

## Bounded preparation and host measurement

- The reviewed preparation policy was installed privately with adaptive
  range 3–5, candidate pool 100, scan limit 80, total Data API request limit
  1,000, market token limit 500, at most three attempts, and 180 seconds per
  attempt. The first bounded attempt refreshed the public candidate source,
  screened 80 of 100 Alpha candidates, found four eligible wallets and 20
  recent observable events, and returned `PENDING_CAPACITY`. The unread 20
  candidates were explicitly recorded; upstream data-as-of remained unknown.
- A 90-second four-wallet full-path probe under image `579f5c5…` completed
  three polls with zero new or persisted events, zero simulations, zero market,
  book, and fee reads, no rate limits, balanced disposable ledger, peak process
  RSS 106,512,384 bytes, and 8,192 bytes of storage growth. It returned
  `INSUFFICIENT_NONEMPTY_EVIDENCE`. Shared-IP other consumers, total host
  memory, and future market mix were not measured. This cannot support a
  `wallet-capacity-v2` PASS record.
- During the mixed-image transition, the old source unit republished Alpha=50
  on the same Stage 2 run. Replaying the wider policy returned its earlier
  successful run while leaving the current pointer at Alpha=50. A controlled
  public `sync --force-new` followed by `ensure` under `579f5c5…` restored a
  new current Alpha=100 selection; the source accepted 704 records at
  2026-09-28 21:07:52 UTC. The related idempotent replay pointer correction
  and regression test are delivered with this record.
- A second bounded preparation against that current selection screened 80 of
  100 candidates and found four eligible wallets with 19 recent observable
  events. It returned `LOW_OBSERVABLE_RATE` and
  `INSUFFICIENT_OBSERVED_RATE`; raising the approved scan limit was not done.
  The non-PREPARED artifact is not an admission to a new v2 period.

## Continuous Shadow and gate disposition

The source unit is pinned to the staged `579f5c5…` image with a 20-hour
refresh threshold and Alpha pool 100. Its persistent timer was changed to
00:15, 06:15, 12:15, and 18:15 UTC; the previous timer file is retained under
the protected host config directory for rollback. The root release symlink
and the persistent Shadow worker remain on `621b3d6…`: switching the worker
to the new preparation-aware command with a non-PREPARED artifact would stop
automatic v1 continuation at a later boundary. The old release and image are
retained. At 2026-09-29 00:16 UTC the old worker was active with zero restarts,
its 23:28 UTC rollover period was `RUNNING`, the latest poll succeeded, health
was healthy, selection was fresh, ledger balanced, and open positions, events,
and evaluations were zero. The separate candidate health warning
`dynamic_shadow_behind_selection` concerns the older Stage 4 artifact; it is
not a successful current dynamic Shadow evaluation.

Operational v2 capacity is **unvalidated**. The required observable-rate gate
is below 20 after the current source refresh, and the probe lacks nonempty
execution evidence. The fixed Canary gates (20 observations, 0.95 mapping,
0.90 executable evidence) were not attempted; no new four-hour economic run
or reminder was started. A software limit of 40 wallets does not establish
host capacity. Profitability remains unestablished.

Next prerequisites are a freshly observed cohort meeting the unchanged data
gate within an approved bounded scan, a nonempty full-path host/shared-IP
capacity measurement with an operator-reviewed matching v2 PASS record, then
the unchanged Canary. Only after those gates may a separately authorized
exact-SHA economic run begin. Later code SHAs require their own operational
authorization; this record does not extend the `579f5c5…` approval.

## Authorized continuation through 2026-09-29 19:52 UTC

The owner separately authorized this task's exact verified release. The
earlier 20-event preparation-rate statement above was the disposition at
00:16 UTC; [PR #186](https://github.com/PolySia-Systems/Platform/pull/186)
subsequently made that uncertain historical estimate advisory after a
matching measured capacity record exists. It did not change the standard
Canary thresholds. The PR's source commit was
`9af25f184689a9be97727400c2b3224808826949`; its squash merge and
verified main commit was `ecee30881ebea64a36529fd3a3bcb019178c014f`.
The [PR CI](https://github.com/PolySia-Systems/Platform/actions/runs/36507885345)
and [new-main CI](https://github.com/PolySia-Systems/Platform/actions/runs/36508183276)
passed their required quality, container, and CI Gate jobs. The local full
suite passed 1,328 tests with one skip. The project lock audit found no known
vulnerabilities; a separate audit of the workstation's global environment
found `cryptography 48.0.0`, which is absent from the project lock.

The host policy was changed privately to adaptive 1–10, pool 100, scan 100;
its previous version was retained under the protected config directory.
The 1,000 Data API request, 500 market-token, 180-second preflight, and
three-attempt limits remained. A first scan of all 100 Alpha candidates found
three eligible wallets and 13 recent observable events. One preparation on
the final `ecee308…` image reused the bounded source state and found three
eligible wallets, 12 recent observable events, 95 confirmed inactive
candidates, and two with missing fee evidence. Screening was complete, with
zero unread Alpha candidates. The proposed protected wallet IDs, in selection
order, were `73b413a18659947d60f4ff3ad0f0f926d6bc83f456fdb97f21af580540e25b24`,
`91fae364d25821783d20711c9fc6a545a8af408a810978cd267f7ce02fb37a89`,
and `65e6440dfaa0f4144b44ecd946c08f3bdbe7ad6133020660ffe2a071a3908808`.
Its `LOW_OBSERVABLE_RATE` artifact had `INSUFFICIENT_OBSERVED_RATE` and
unverified capacity. No cohort was admitted to a v2 period.

The trusted archive of `ecee308…` matched SHA-256
`88ee81afe1f61972d47c7be4dfba9ea17dcb51c73fce56ad890efbd81c9eb0a2`
before and after transfer. The read-only release was staged at
`/opt/polysia-releases/ecee30881ebea64a36529fd3a3bcb019178c014f`.
The tagged image's `BUILD_COMMIT` matched, and its isolated default check
returned `TRADING_MODE=DATA_ONLY` and `LIVE_TRADING_ENABLED=false`. The root
symlink and persistent Shadow worker were not switched.

One isolated, systemd-bounded full-path probe ran from 01:36:44 through
02:06:52 UTC under `ecee308…`, with a 30-minute observation window and
explicit 1,000 source-request and 500 market-token caps. It completed 30
polls, 94 counted public-source attempts, two new and persisted events (at
polls 7 and 24), two book reads, two fee-schedule reads, zero simulations,
and six `UNKNOWN` evaluations. The writer count matched source events and the
disposable ledger was balanced. No request budget or timeout was exhausted;
peak probe RSS was 122,994,688 bytes, process CPU 6.142 seconds, and storage
growth 69,632 bytes. The result was
`INSUFFICIENT_NONEMPTY_EVIDENCE`, not capacity `PASS`. The diagnostic JSON
does not retain per-evaluation UNKNOWN reasons after removing its isolated
SQLite store; no cause beyond the observed evaluation stage is established.

The 31 host samples over that same window showed at least 2,625 MiB available
RAM, maximum one-minute load 0.45, 729,088 bytes host-disk growth, 2,239,158
received and 903,036 transmitted bytes on `eth0`, and at most five
established TCP connections. These are aggregate load observations, not
endpoint attribution for every consumer of the shared IP. The probe JSON
still lists `shared_ip_other_consumers` and future market mix as unmeasured.
The retained host reports are
`/var/lib/polysia/wallet-intelligence/reports/capacity-probe-ecee308-20260929.json`
(SHA-256 `b0cfc94a58ca4ea22ec81dd5cb204974196b67bb5e365fe8f300e18161bd6a4b`)
and `capacity-host-ecee308-20260929.log`
(SHA-256 `77ad5b78335af607562991da4fbf2bcde0259104da2e018310f445aeab4de2fa`).
The probe process exited zero; that is not an admission verdict.

At 19:52 UTC the accepted v1 Shadow worker remained active with zero
restarts. Its current, separately capitalized period
`6ea932b8948b48018fc21cc06a169601` began at 19:28 UTC under the old
`621b3d6…` image. Its latest poll succeeded, health was healthy, selection
fresh, ledger balanced, with zero events, evaluations, and open positions.
The source timer remained enabled; the v2 preparation timer was not installed.
The earlier verified three-store backup and off-host encrypted copy remain
the recovery evidence; this change had no persistence migration, so no
repeat backup or restore rehearsal was performed.

| Gate | Outcome | Evidence or prerequisite |
|---|---|---|
| Repository correction | PASS | PR #186, focused tests, local gates, PR and main CI. |
| v2 runtime transition | NOT RUN | Probe had 0 simulations and 6 UNKNOWN evaluations; no matching reviewed capacity PASS record or safe v2 boundary application. |
| Standard Canary | NOT RUN | v2 full-path capacity gate remains unmet; fixed 20 / 0.95 / 0.90 criteria were not tested. |
| New four-hour economics | NOT RUN | No eligible Canary and no new economic T0; Control/Target opening capital, gross P&L, fees, net P&L, return, and relative result are UNKNOWN. |
| Profitability | NOT ESTABLISHED | Technical health and the older empty-sample zero-net report do not show profitable economics. |

No new economic period ID or T0 exists. The requested current-period
comparison is therefore unavailable:

| Measure | Control | Target |
|---|---:|---:|
| Opening capital | UNKNOWN | UNKNOWN |
| Gross P&L | UNKNOWN | UNKNOWN |
| Fees and costs | UNKNOWN | UNKNOWN |
| Net P&L | UNKNOWN | UNKNOWN |
| Return | UNKNOWN | UNKNOWN |

Target-minus-Control net P&L is also UNKNOWN. The distinct historical
2026-09-27 failure archive reported zero eligible observations and net P&L
of zero for both sides, but had no event-bearing interval or verified economic
bundle; those empty-sample figures are not a result for this task.

The next bounded step requires preserved per-evaluation reason diagnostics,
then a genuinely new observation showing a nonempty simulated writer path
with matching code/workload, attributable shared-IP load, and a reviewed
capacity record. Only then can a fresh complete preparation, safe v2 period,
unchanged Canary, and conditional economic run proceed. Do not infer an
UNKNOWN reason, loosen the Canary gates, or promote the staged image on this
probe result alone.
