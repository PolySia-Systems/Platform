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
