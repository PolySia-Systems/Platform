# D2 pre-Live qualification and operator handoff

Date: 2026-10-28 UTC. Verdict: **BLOCKED_WITH_PREPARATION_COMPLETE**.
D2 independent authorized preparation is complete. Financial operational
readiness is BLOCKED; commissioning and Live remain unperformed and unauthorized.
This dated record is not live host truth and grants no subsequent action.

## Scope, resume and permission ledger

The owner activated Master Prompt D2 in chat
`01a18407-35a4-7840-ac81-7b0202691925`. Repository root was
`C:/Users/Siamak/Documents/PolySia`, clean at branch
`codex/d1-deployment-report`, HEAD `5b099155177fad6ac54c989b8be777ac7a2dc74d`.
Work continued on `codex/d2-readiness`, based on that exact commit; no main
update, merge, deployment or configuration change was performed.

Resume evidence is [D1 PR #234](https://github.com/PolySia-Systems/Platform/pull/234),
still open/draft at that HEAD, and its
[immutable handoff](https://github.com/PolySia-Systems/Platform/blob/5b099155177fad6ac54c989b8be777ac7a2dc74d/docs/18-ai-handoffs/console-d1-deployment-2026-10-28.md).
D1 owns the remaining archive, encryption and recovery identities; it is not
repeated here. PR #234 is a preserved dependency, not implicitly accepted/merged.

Authority search was confined to this activation, D1's actual owner messages
in chat `01a182dd-9777-73a0-a7c6-2b36ca87dfa7`, PR #234 and #230 discussions,
repository searches for D2/ADR-0023, relevant runbooks/requirements and the
dedicated installation's file inventory. Both PR discussions were empty;
the searches returned no new D2/ADR approval. D1's owner authorized installation
on the two hosts, then requested access instructions. No bounded account/source
grant, exact alert destination/test approval, human acceptance receipt or
operational ADR acceptance was found in these records. This is a scoped finding,
not a claim about every possible owner record. Old test allowances are inapplicable.

| Gate | State / category | Evidence, UTC observation / validity | Binding and next action |
|---|---|---|---|
| Installation identity / health | VERIFIED | Identity 19:43:31; samples 19:46:18–19:47:20; point observations only | Exact D1 source/package/config below; refresh before later work |
| Primary / recovery assignment | VERIFIED | Helsinki 19:43:31; Nuremberg 19:43:33 | One primary; no financial writer; recovery fenced |
| Private Console / API | VERIFIED | Normal TLS; all six canonical GETs passed in each of three samples | Same installed bundle; browser rendering reused from D1 |
| Desktop browser trust setup | PENDING / client participation | Dedicated public CA retained and hash verified; Firefox installed | Import only into separate Firefox profile, then log in |
| Human acceptance | PENDING / human evidence | No participant receipt as of D2 | Complete card below; automated checks cannot substitute |
| Real data / account completeness | BLOCKED / permission and inputs | No current read grant or qualified opening | Approve exact acquisition proposal; no provider/account probe ran |
| Copyability / cohort | BLOCKED / data | No installed cohort or causal follower sample | Retain causal samples and select native/PolyCop cohort under frozen policy |
| Operational capacity | BLOCKED / workload evidence | Zero approved real workload samples | Qualify exact granted workload; no real capacity receipt emitted |
| Alert delivery | BLOCKED / permission and integration | DELIVERY_NOT_COMMISSIONED; no exact test approval | Destination, bounded test and concrete sink/delivery receipt required |
| Independent custody / supervision | BLOCKED / commissioning | Real journal/witness/custody/signer absent; supervisor evidence unavailable | Reviewed deployment and separate exact commissioning authority |
| DATA_ONLY backup / restore | VERIFIED, scheduled cycles NOT_OBSERVED | D1 receipts retained; readback 19:43:33 | Daily first triggers 2026-10-29 00:15 / 00:45 UTC; no extra drill |
| Financial recovery | BLOCKED / commissioning | No commissioned financial state to recover | Exact journal/witness/checkpoint, off-host custody and authorized drill |
| Operational ADR decision | PENDING / owner decision | ADR-0023 still Proposed; no accepting owner record located | Explicit acceptance of operational contract and trust/failure-domain model |
| Inactive run specification | BLOCKED / missing values | Installed schemas captured under exact package | Review-only specification below; every missing field stays MISSING |
| External financial actions | NOT_APPLICABLE to D2 | None performed | Separate future exact authority required |

## Current installation and bounded observations

SSH used existing identities with BatchMode, StrictHostKeyChecking and explicit
`HostKeyAlgorithms=ssh-ed25519`. Both known-host Ed25519 fingerprints match D1:
Helsinki `doblcAu6vZyLzGiGOQSTfmP1YKJADU7GQLuiUlwRc3M`;
Nuremberg `S+OD2i3pABQhtFsGH54PDSmt2qchnDig5UX1HUaUNrM`.
No key was automatically accepted or changed. Both hosts reported
`NTPSynchronized=yes`; this is synchronization status, not a measured UTC error.

| Binding | Current verified identity |
|---|---|
| Runtime source | `8faa568ba3d2e03bac7cc758260b3e67626b23c4` |
| Source tree | `fd1ece91e43a04cda1a459f7c0730ad856ffcf7b` |
| Running OCI image | `sha256:c6b278e0df220185e9689b499ec36feaaae22c8cbbb5efaee6f1afd1866ad1cc` |
| Original manifest SHA-256 | `326da547fee4e3e42f0d14f80eb0b9872bc05ab26b82feceed6a7943556ef5e7` |
| Package digest / files | `b208e1071420c4d5a3581014e621855fa24677f1d3b6df936255d2885492c14f`; 330/330 files match retained D1 wheel binding |
| Wheel SHA-256 | `2d8ca8ec415d0d94946908245e0ce533c6b16c856f8e2a8454f84f473a5612be` (reused D1 wheel identity) |
| Console source digest | `486d16d75740e939912fee9d86a1e9176b1c21e258d14b014b76c1854a598277` (same verified package) |
| Installed configuration inventory | `c589f0d816217c85a13703395c40e164d60cbcf288e11a79fe2b3f094267e800`; every D1 inventory path/hash/UID/GID/mode matches |
| OS fence digest | `7cb6403b37504a392de0db6a4afad9213c6f6990d6566bc5ce189589000dd8d1` |
| Runtime | Python 3.14.8; DATA_ONLY; LIVE_TRADING_ENABLED=false |

Shipped `platform_admin.py status` was inspected before execution: it reads only
installation/maintenance JSON. The backup script's `status` fetch writes a local
partial file, so D2 read already retained status receipts instead of invoking it.
The manifest-bound admin/bootstrap/backup script hashes also match D1.

Three lightweight observations span **61.806664 seconds**,
19:46:18.443608–19:47:20.250272 UTC, at irregular intervals. All **18/18**
authenticated canonical Console GETs returned 200, **53,445 response bytes**,
per-request elapsed **0.0061–0.0372 seconds** on host loopback. These are Console
read timings, not provider latency, follower execution latency or production capacity.
Minimum free primary disk **26,655,297,536 bytes**; available RAM
**3,096,756,224 bytes**. Web/gateway restart counters stayed 0; pending or claimed
commands stayed 0; dedicated service error records in each preceding ten-minute
journal view were 0. These overlapping views are not independent ten-minute soaks.

Helsinki web/gateway remain active. The web container is UID/GID 10102:10102,
network none, read-only root, ALL capabilities dropped, bounded local logs
(two 5 MiB files); mounts exclude financial stores, signer, custody and Docker.
Research/financial worker service and timer are inactive; acquisition is false,
admission empty, installation UNCONFIGURED. No real financial authority, journal,
witness, custody, cohort or sample exists in the inspected dedicated state.
The only control command is revision **1**, `stop`, **APPLIED**,
key `d1-data-only-stop-20261028`; SQLite quick_check is `ok`.
Nuremberg has only unrelated `3x-ui` running, no Platform web/worker, and retains
`recovery-fenced`. No service was restarted, stopped or reconfigured in D2.

At identity observation, backup receipt age was **14,107.697 s**; independent
restore receipt age at recovery observation was **14,061.031 s**. The latest
generation is `platform-20261028T154802Z.tar.age`, **77,453,976 bytes**, SHA-256
`6269a7187ac5517e17cf6612421c1a58d4661dc0516dfdf65286a63e84404757`,
matching destination bytes. Two ciphertext generations total **154,907,952 bytes**;
canonical retention is two, generation ceiling 512 MiB, backup allocation 2 GiB,
and free-space check reserves 8 GiB plus two generation ceilings. Recovery free
disk was **27,198,025,728 bytes**, RAM **2,891,694,080 bytes**.
Latest publisher, certificate-health and restore-status-fetch units report success.
Backup/restore timer LastTrigger is empty; default service Result=success is not
evidence of scheduled execution. First daily cycles remain NOT_OBSERVED.

Reuse D1's actual isolated restore: measured RPO **56.286 s**, RTO **43.758 s**,
and the 22-file independently encrypted configuration checkpoint verified at
18:25:18 UTC. No relevant drift/failure justified another restore. These prove
that unconfigured installation drill only; daily scheduling neither guarantees
56-second RPO nor qualifies financial recovery. Different hosts provide a
host-failure boundary, while common root administration/provider dependence
remain. The recovery key stays outside upload credentials; no financial signer
or issuer key was provisioned or copied.

## Console access and human acceptance card

The six GETs cover Overview snapshot, Investigate wallet records, Operate,
Evaluate, System / Setup, and receipt history. Wallet records are an authoritative
empty page (`total=0`, no next cursor), not proof of zero account holdings.
Evaluate remains `UNKNOWN_RECONCILIATION_BLOCKED`. The exact historical STOP
receipt is APPLIED/OBSERVED; it is not an unresolved active command.
Publication/publisher evidence was AVAILABLE at the last sample and valid until
19:48:11 UTC. Worker evidence expired at 15:47:47 UTC; financial/supervision
evidence is UNAVAILABLE. Refresh cannot renew those observations.

The unconfigured Console truthfully renders configured/recorded session mode
UNKNOWN. It does not currently expose the independently verified process DATA_ONLY
setting as a configured financial session. Operators must use the host receipt
above for process mode, and must not interpret UNKNOWN as Live or account zero.
The Overview's source/publication freshness is publication-envelope freshness,
not a qualified real account/source observation. D1 desktop/mobile screenshots
and five-workspace browser evidence were reused after package/config equality;
the retained Overview screenshot was inspected again. No synthetic evidence was
injected and no preview/apply/POST command was submitted.

Access preparation retained only the public CA at local ignored
`artifacts/d2-20261028/gateway-ca.crt`, SHA-256
`c02dd499c6ae0cd578690568105c65409126c5992d710638851067adb8e0b4f4`,
matching the SSH-verified host file. Firefox is installed at
`C:/Program Files/Mozilla Firefox/firefox.exe`. Complete these local user steps:

1. Keep a PowerShell window open with the pinned existing SSH forwarding:

   ```powershell
   ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o HostKeyAlgorithms=ssh-ed25519 -o ExitOnForwardFailure=yes -N -L 127.0.0.1:8443:127.0.0.1:8443 Hetzner-Finland-Helsinki-01
   ```

2. In Firefox `about:profiles`, create a separate `PolySia-private` profile and
   launch that profile. In its Settings > Privacy & Security > Certificates >
   View Certificates > Authorities, import the hash-verified public CA above
   and trust it to identify websites. Keep this trust within that profile;
   do not import into Windows/global trust or bypass a certificate error.
   [Mozilla CA guidance](https://support.mozilla.org/en-US/kb/setting-certificate-authorities-firefox)
   explains private CA trust; this procedure chooses a separate browser profile.
3. Open `https://localhost:8443`. Use username `owner`; retrieve only its password
   in a private terminal through verified SSH from root-only
   `/etc/polysia-platform/gateway-credentials.json`. Do not paste values into
   chat, reports, commands, browser URLs or tracked files. Reader access uses
   the existing `reader` reference. No authentication/token creation is required.

The forwarding, CA import and human login have not been performed on the owner's
behalf. Server-side normal TLS operator/reader GETs returned 200; anonymous GET
returned 401. Private origin only; public origin commissioning is not claimed.

Human card, to be completed by an actual operator without command submission:

- Open all five workspaces; state host DATA_ONLY/Live-disabled and explain the
  unconfigured session UNKNOWN fields. Identify revision-1 acquisition STOP and
  explain why absent financial authority is a separate fact.
- Compare publication age, stale worker age and missing account/supervisor dates.
  In Investigate identify empty retained wallets and the missing source/cohort
  limitations; there is no real source detail to invent.
- Explain Evaluate's unknown cash/P&L/costs and why historical/synthetic returns
  cannot qualify current economics or follower edge.
- Inspect the exact D1 receipt in Operate; explain history versus pending request,
  response loss/recovery by original key, and exact operation/target confirmation.
- Locate independent SSH administrative STOP and the financial emergency-stop
  procedure in the [runbook](../10-operations/continuous-financial-session.md#recovery-and-incidents).
  Acquisition STOP does not assert financial closure; financial STOP can halt exits.

Receipt fields still MISSING: participant identity, UTC, exact source/bundle and
generation, each card result, feedback, unresolved concerns, explicit acceptance.
HUMAN_ACCEPTANCE=PENDING. Missing source data is reported as such, never staged
to impersonate a real source journey.

## Real inputs, provider compatibility and acquisition proposal

Dedicated installation inventory/publication contains no retained market database,
cohort, follower samples or complete account opening. Local
`data/polysia.sqlite3` is **258,048 bytes**, SHA-256
`76e95c4384b38f555ee53f967e45f1969b48e5add0bece67fe8b05249ce6c4fb`.
A bounded read-only table/count inventory found empty market/book tables and
nonempty legacy financial/development rows; provenance and completeness are
UNQUALIFIED, not presumed synthetic or current account facts. No raw rows were
exported or qualified. The explicitly referenced historical backup
`PolySia-backups/helsinki-final-20260906T175930Z/continuous-shadow.sqlite3`
is absent. D1's two unavailable private historical fixtures remain unverified.
No broad personal-file search, account database dump or secret-store scan ran.

Official documentation was read without market/account API calls. The installed
SDK's production constants match the documented chain **137**, standard CTF
exchange, CTF, pUSD and collateral adapter. CURRENT supported session route is
`ctf-exchange-v2-standard`, EOA signer=funder, signature_type=0, six-decimal
pUSD/CTF and the existing two-decimal share quantum. The installed session SDK
scope rejects other contracts/protocols. The
[official contracts](https://docs.polymarket.com/resources/contracts) separately
list PositionManager/ExchangeV3; those namespaces are unsupported here. The
[wallet documentation](https://docs.polymarket.com/trading/wallets-auth) describes
Deposit Wallet as the default and distinguishes EOA=0. Therefore an arbitrary
owner account cannot be assumed compatible. The
[Data API migration](https://docs.polymarket.com/migrate/data-api-v1-to-v2)
documents v2 cursor envelopes and retired v1 routes. Installed v2 adapters and
SDK-scope guards were inspected; no live route/account compatibility was proven.
Recheck official contracts and exact selected instruments before later approved
I/O. An incompatible account/namespace is a blocker, not authority for an adapter
expansion, wallet migration or credential creation.

Non-executable acquisition proposal (all unspecified values are MISSING):

| Required owner binding | Prepared scope / missing input |
|---|---|
| Purpose / grant record | MISSING: exact bounded read-only account qualification and causal source/Shadow workload, issuer and approval identity |
| Account / routes | MISSING: approved dedicated account, EOA identity, exact instruments/tokens/chain/CTF route and credentials references; no provider changes |
| Endpoints / transport | MISSING: exact allowed CLOB read paths, Data API v2/native/PolyCop paths, qualified historical RPC HTTPS path and read-method set; no guessed RPC/provider |
| Immutable workload | D1 source/image/package/bundle above; MISSING: workload/scopes/artifact/config/policy hashes and frozen source/candidate universe |
| UTC / aggregate bounds | MISSING: starts/expires, total and per-window underlying requests/pages/bytes/cost/storage, per-response/timeouts, retries charged to the same allowance |
| Resource / safety reserves | MISSING: memory/CPU/cadence/cohort count/disk floor/retention/backup bounds, queue/backpressure and separate reconciliation/protective reserves/shared egress allocation |
| Protected review paths | RECOMMENDATION only: `/etc/polysia-platform-review/d2/` for unsigned review inputs; `/var/lib/polysia-platform-review/d2/read/` for independent allowance and opening/raw evidence; neither created nor approved |
| Canonical execution owner | Installed `session qualify-account` with explicit read flag; source acquisition via existing bounded lab/native paths and one durable allowance; existing financial worker remains fenced |
| Completion / failure | All pages within caps; orders/trades/fees/cash/all token balances and finalized canonical occurrences, observed_at/expires_at; partial/empty/stale/conflicting/over-limit evidence UNKNOWN/BLOCKED; no replenishment or automatic retry campaign |

No provider/account probe, authenticated account read, networked Shadow, new
allowance or unattended acquisition ran. No copyability/cohort selection or real
capacity artifact could be supported. Causal follower size, delay, executable
entry/exit depth, fee/slippage, calibration and nonoverlapping selection/evaluation
windows remain required; ranking/leader P&L/wallet count are insufficient.
Goldsky stays deferred. Provider costs, edge and net economics remain UNKNOWN.
The 10,000-wallet synthetic benchmark was not rerun or relabeled as capacity.

## Incidents, custody and remaining commissioning sequence

`monitoring/session_incidents.py` implements local allowlisted incident kinds,
stable deduplication, durable pre-I/O delivery claims, five-minute default rate
limit, UNKNOWN on response loss and isolated sink failures. Existing exact-source
CI covers the fake-sink authority/dedup/failure/rate-limit regression in
`tests/integration/test_session_policy_controls.py`; Console uses allowlisted
redacted projections rather than raw incident stores. That unchanged local
behavior was reviewed and its passing D1 CI reused. It is not real alert delivery.
The sink is a protocol, not a commissioned production destination/transport.
No sink was configured and no alert was sent. A later chosen sink may need a
focused integration; destination authorization alone does not create one.

The installed `session` schemas, receipt verifier, journal/witness, independent
supervisor and isolated recovery implementation provide a concrete software path.
D1's separate-process synthetic proof covers mechanics only. Proposed deployment
must bind dedicated UID/ACLs, worker-only journal/witness/outbox writes,
supervisor-only custody/STOP/ACK, read-only worker custody access, issuer outside
runtime, signer excluded from research/web, finite supervisor lifetime and
checkpoint/backup age limits. Existing DATA_ONLY timers do not install this
financial deployment. Common root administrator and same-volume rollback are
outside its protection; off-host checkpoints and owner-controlled recovery are
still uncommissioned. No financial stores, keys, units or permissions were added.

Future sequence, descriptive only; no activation command is supplied:

1. Accept ADR-0023 and assess exact account/route compatibility. Approve bounded
   reads, collect complete fresh evidence and qualified causal cohort/capacity.
2. Complete every field below, review deployment/ACL/egress/recovery/failure
   domains, obtain human acceptance and actual authorized alert delivery proof.
3. Freeze exact release/config/policy/cohort/sample/capacity/opening identities.
   Owner signs the version-2 authorization externally with a separately installed
   public trust reference. Validate the receipt; validation alone is not authority
   issuance, provisioning or readiness.
4. Only with separate specific commissioning authorization, use installed
   `session provision` on fresh unused protected stores and a complete fresh
   flat opening. Retain consumed receipt custody. Never reset/reidentify a prior
   store or invent a new run to evade STOP or consumed counters.
5. Qualify isolated financial recovery with exact independent checkpoint/witness
   and off-host protection; do not restore active witness/custody. Establish
   measured financial RPO/RTO under approved objectives and recovery authority.
6. Run independent bounded supervision under a reviewed deployment. Its
   commissioning release applies only to custody reason `commissioning_stop`
   and exact healthy checkpoint; explicit/revocation/supervision STOP stays latched.
7. D1's revision-1 acquisition STOP and OS restart fence are separate from that
   initial financial custody STOP. No supported explicit-STOP-clearing transition
   was identified: the installer retains the fence and custody release rejects
   later STOP reasons. This is a commissioning blocker requiring an explicit
   owner transition decision and a separately reviewed supported procedure; no
   file deletion, SQL edit, reinstallation or new run is a permitted shortcut.
8. Only later, after all exact gates and separate run-specific Live authority,
   may the installed financial worker be activated. D2 performs none of steps 3–8.

## One inactive run specification

This is a Markdown review artifact, not a loadable config, signature, receipt or
financial authority. Candidate host is the existing Helsinki primary; recovery
remains Nuremberg/fenced. Every MISSING value must be owner-supplied/qualified,
never filled from examples or implicit defaults. Existing installation config
digest above is not a future SessionRuntimeConfig fingerprint. Frozen source,
image, wheel and bundle are bound above; future config/policy/cohort/source and
financial-store identities remain MISSING. No review input was installed.

The following complete top-level inventories come from the actual installed
schemas. Nested objects marked MISSING include all their nested required values.
Optional reserve/default values remain MISSING until explicitly reviewed.

### Installed config contract

| Field | Review value |
|---|---|
| `version` | 1 (installed schema contract only) |
| `release` | `8faa568ba3d2e03bac7cc758260b3e67626b23c4` (candidate only) |
| `package_tree_digest` | `b208e1071420c4d5a3581014e621855fa24677f1d3b6df936255d2885492c14f` |
| `host` | Helsinki / `Hetzner-Finland-Helsinki-01` (existing primary, no run grant) |
| `policy` | MISSING |
| `account_mapping` | MISSING |
| `financial_path` | MISSING |
| `witness_root` | MISSING |
| `custody_path` | MISSING |
| `outbox_path` | MISSING |
| `publication_path` | MISSING |
| `cohort_path` | MISSING |
| `follower_samples_path` | MISSING |
| `cohort_file_digest` | MISSING |
| `follower_samples_file_digest` | MISSING |
| `source_wallets` | MISSING |
| `rpc_url` | MISSING |
| `exchange` | MISSING |
| `ctf` | MISSING |
| `collateral_adapter` | MISSING |
| `maximum_pages` | MISSING |
| `maximum_response_bytes` | MISSING |
| `maximum_queued` | MISSING |
| `request_timeout_seconds` | MISSING |
| `per_action_requests` | MISSING |
| `private_key_reference` | MISSING |
| `api_credentials_reference` | MISSING |
| `minimum_free_disk_bytes` | MISSING |
| `egress_allocation_receipt` | MISSING |
| `opening` | MISSING |
| `risk_limits` | MISSING |
| `maximum_order_shares` | MISSING |
| `estimator_confidence` | MISSING |
| `incident_path` | MISSING |
| `commands_path` | MISSING |
| `capacity_evidence_path` | MISSING |
| `capacity_evidence_digest` | MISSING |
| `maximum_backup_age_seconds` | MISSING |
| `checkpoint_handshake_seconds` | MISSING |
| `tick_interval_seconds` | MISSING |

### Installed authority contract

| Field | Review value |
|---|---|
| `version` | 2 (required future contract only) |
| `run_id` | MISSING |
| `owner_receipt` | MISSING |
| `granted` | MISSING |
| `binding` | MISSING |
| `starts_at` | MISSING |
| `expires_at` | MISSING |
| `protective_until` | MISSING |
| `wallets` | MISSING |
| `instruments` | MISSING |
| `strategy` | MISSING |
| `exit_policy` | MISSING |
| `max_order_all_in` | MISSING |
| `max_open_exposure` | MISSING |
| `max_turnover` | MISSING |
| `max_total_loss` | MISSING |
| `max_daily_loss` | MISSING |
| `max_market_exposure` | MISSING |
| `max_wallet_exposure` | MISSING |
| `max_positions` | MISSING |
| `max_concurrent_orders` | MISSING |
| `max_attempts` | MISSING |
| `fee_rate` | MISSING |
| `max_evidence_age_seconds` | MISSING |
| `supervision_timeout_seconds` | MISSING |
| `max_holding_seconds` | MISSING |
| `dust_shares` | MISSING |
| `max_requests` | MISSING |
| `protective_request_reserve` | MISSING |
| `max_response_bytes` | MISSING |
| `max_storage_bytes` | MISSING |
| `max_source_cost` | MISSING |
| `restart_policy` | MISSING |
| `protective_actions` | MISSING |
| `protective_attempt_reserve` | MISSING |
| `protective_turnover_reserve` | MISSING |
| `protective_byte_reserve` | MISSING |
| `protective_cost_reserve` | MISSING |
| `protective_storage_reserve` | MISSING |
| `protective_order_reserve` | MISSING |

### Installed acquisition contract

| Field | Review value |
|---|---|
| `policy_id` | MISSING |
| `host` | Helsinki (proposed bounded workload only) |
| `starts_at` | MISSING |
| `expires_at` | MISSING |
| `endpoints` | MISSING |
| `maximum_requests` | MISSING |
| `maximum_bytes` | MISSING |
| `maximum_response_bytes` | MISSING |
| `timeout_seconds` | MISSING |
| `minimum_free_disk_bytes` | MISSING |
| `cohort_limit` | MISSING |
| `cadence_seconds` | MISSING |
| `retention_days` | MISSING |
| `backup_generations` | MISSING |
| `memory_max_bytes` | MISSING |
| `cpu_quota_percent` | MISSING |
| `window_seconds` | MISSING |
| `window_maximum_requests` | MISSING |
| `window_maximum_bytes` | MISSING |
| `closure_request_reserve` | MISSING |
| `closure_byte_reserve` | MISSING |

### Installed policy contract

| Field | Review value |
|---|---|
| `version` | MISSING |
| `sizing` | MISSING |
| `fixed_debit` | MISSING |
| `capital_fraction` | MISSING |
| `exit_preset` | MISSING |
| `net_take_profit` | MISSING |
| `stop_loss` | MISSING |
| `maximum_holding_seconds` | MISSING |
| `reentry` | MISSING |
| `quantity_quantum` | MISSING |

`account_mapping` must bind account_id, signer, funder, signature_type=0, venue,
collateral and settlement_route; the actual account remains MISSING. `binding`
must match exact release/configuration/policy/account/host. All protected paths,
signer/API/public-trust/issuer references, opening observed/expiry times,
capital/exposure/order/loss/turnover/attempt limits, protective-action scope and
deadline, recovery objectives and escalation recipient are MISSING. No issuer
private key belongs on either runtime host or in Git. Recommended protected
review paths above remain unapplied. An incompatible selected route requires
owner assessment before this specification can advance.

### Later limited-Live evaluation protocol (unexecuted)

Freeze the hypothesis, causal native/PolyCop cohort, policy, cost model,
selection/evaluation split, account/instruments and exact release before the
approved start. Owner duration, end UTC, all caps and numeric acceptance/stop
thresholds remain MISSING; no monetary threshold is selected here. Measure net
follower P&L with actual fees, executable depth, delay and slippage; separately
record provider/infrastructure costs without double-counting spread already in
fills. Retain opportunity/eligible/Risk/submission/fill denominators, exclusion
reasons, stale/UNKNOWN fraction, latency sample/missing/censored counts,
reconciliation differences, reserves, requests/bytes/cost, storage/headroom,
backpressure and incidents. Review estimator calibration and selection bias.

Entry must stop on expiry/exhaustion, exact identity drift, stale/incomplete
account evidence, reconciliation ambiguity, supervision/checkpoint/backup
failure, duplicate writer, lost response or storage/resource floor breach.
Follow the existing independent Risk/emergency states; preserve uncertain
submission reservations and consumption and reconcile without resubmitting.
At end UTC, no new entries. Retain unresolved orders/holdings and UNKNOWN cash
until authoritative evidence. No automatic extension, cap increase, liquidation,
cancellation, redemption, restart or allowance renewal follows elapsed time.
Future authority must explicitly enumerate permitted protective actions,
their deadlines/reserves and incident escalation. If no permitted action remains,
preserve evidence and escalate instead of manufacturing closure or recovery.

## Consolidated owner-action table

Rows are dependent gates for a future authorized phase, not questions or pending
work silently running under D2. No secrets or raw account evidence belong in PRs.

| ID | Missing decision / evidence | Why / exact scope | Secure input method | Unlocks |
|---|---|---|---|---|
| OA-1 | Actual operator card receipt and local profile trust | Named human, D1 bundle, exact current generation/UTC and each card result; complete dedicated-profile CA import | Hash-verified public CA via existing SSH; retrieve owner reference privately; record nonsecret feedback/acceptance on this PR | Human usability acceptance |
| OA-2 | Exact bounded read/acquisition approval and compatible account/source inputs | Purpose, dedicated EOA account/instruments, each endpoint/RPC method, source/artifact/workload hash, UTC start/expiry, finite requests/pages/bytes/cost/storage/resources and protective reserves; no signer issuance | Owner nonsecret approval record plus protected account/scopes/policy/credential-reference files outside Git | Fresh account completeness, causal cohort and sampled real capacity |
| OA-3 | Alert destination/test approval and production sink choice | Exact destination, transport, payload, UTC window, finite attempts/bytes/cost, delivery failure rule and receipt | Protected destination/secret references; nonsecret owner approval and redacted delivery receipt | DELIVERY_COMMISSIONED after bounded authorized test; focused integration if needed |
| OA-4 | ADR-0023 operational acceptance / trust model | Restricted CTF V2 EOA route, independent custody/ACK/issuer boundaries, common-administrator/failure-domain limitations | Explicit owner decision linked to ADR/PR; public trust key ID only in review | Operational design acceptance |
| OA-5 | Complete reviewed financial run values and external signature | Every MISSING config/authority/policy field above, exact host/account/code/artifacts, capital/exposure/loss/attempt/time and protective limits; no example-derived limits | Protected unsigned review files; external owner signer; signed envelope and public trust installed only under later separate authority | Gated commissioning review, never D2 activation |
| OA-6 | Reviewed deployment/custody/recovery authority and STOP transition decision | Dedicated identities/ACLs/egress, independent supervisor lifetime, exact off-host checkpoint protection and financial RPO/RTO objectives/drill; supported handling of explicit D1 STOP/fence without reset | Nonsecret reviewed deployment/transition plan and exact later commissioning approval; key references only, private keys remain protected | Real financial commissioning/recovery; may require a separately authorized supported transition change |

Minimum next step: review this PR and provide OA-1/OA-2 nonsecret acceptance and
bounded read scope, keeping D1 source/config/STOP pinned. OA-3–OA-6 remain required
before financial commissioning review can be declared ready. No subsequent phase
was started; no scheduled follow-up or ongoing D2 monitor exists.

## Validation, reused evidence, limitations and review

Read-only commands executed: strict pinned SSH; `date -u`, `hostname`,
`timedatectl show`, dedicated `systemctl list-units/list-timers/show/cat`, bounded
dedicated `journalctl`, file inventories/hashes, read-only SQLite quick_check and
command/count queries, reviewed administrative `status`, `docker ps/inspect`,
and `docker exec ... python -B` for installed file hashes/schemas/SDK constants.
Host-local HTTPS used explicit CA trust and finite GET time/response limits.
Local helper entry points were:

```powershell
.venv/Scripts/python.exe artifacts/d2-20261028/collect.py
.venv/Scripts/python.exe artifacts/d2-20261028/contracts.py
.venv/Scripts/python.exe artifacts/d2-20261028/inspect_local.py
.venv/Scripts/python.exe artifacts/d2-20261028/sample.py
.venv/Scripts/python.exe artifacts/d2-20261028/sdk.py
.venv/Scripts/python.exe artifacts/d2-20261028/summarize.py
```

`sample.py` ran three times only. Helpers/evidence are ignored local task outputs,
not installed services. A redundant second full identity probe exceeded its
25-second docker-exec tooling deadline during concurrent schema work; no sample
or success was claimed for it. It was replaced by the lightweight observations;
the first completed package/config identity check remains valid. A guessed SDK
symbol and an unsupported `kind=source` query failed locally/read-only; corrected
`PRODUCTION` and canonical `kind=wallet` passed. These were task probe defects,
not product patches. No destructive retry or production tuning occurred.

Native runtime acceptance was reused from exact-source
[CI 40714695972](https://github.com/PolySia-Systems/Platform/actions/runs/40714695972),
reconfirmed success for `8faa568ba3d2e03bac7cc758260b3e67626b23c4`.
The connector's PR-trigger-only workflow lookup returned no runs for that main
commit; a bounded `gh run view 40714695972 --json headSha,status,conclusion,updatedAt`
confirmed completed/success at 15:43:06 UTC. D1 records Linux 1,948 passed/28
configured skips, Windows 1,944 passed/32, installed browser 26 passed, required
quality/supply-chain/image/recovery gates passing. Configured skips, including two
unavailable historical fixtures, remain skips. No runtime/test/dependency/build
source changed, so those suites, H1/H2, ten-minute soak and restore were not rerun.

Local documentation validation passed:

- `.venv/Scripts/python.exe scripts/check_changed_docs.py --local`:
  changed-file links, repository hygiene and architecture consistency passed.
- `.venv/Scripts/python.exe scripts/validate_standards.py --mode full`:
  blocking=0, total=0; passed.
- `.venv/Scripts/python.exe -m polysia.security.secret_scan`: passed.
- `git diff --check` and `git diff --cached --check`: passed; final content,
  document sizes, complete schema-field inventory and retained-evidence hashes
  were reviewed. No runtime, test, dependency or executable configuration changed.

Private local evidence is retained under
`C:/Users/Siamak/Documents/PolySia/artifacts/d2-20261028/`.
Its 13-file `evidence-manifest.json` was sealed at 19:53:01.234855 UTC,
SHA-256 `e04469e92e5fc80856e211d6c225e392c42542195da7604a848814a07f3ce5ed`.
It binds the primary/recovery snapshots, three health samples, metrics summary,
local retained-data inventory, installed SDK constants, public CA and four
installed schema snapshots. Evidence remains outside Git and is retrievable
locally by exact identity; it is not an account evidence publication.
Schema snapshot SHA-256 values:

| Installed contract | SHA-256 |
|---|---|
| config | `889b180915e028882a77f958eb861fa895505835f1bfa94311911c33fbfb164c` |
| authority | `45ca479022fa0b633bfee453748a10adeee5839a7c3c62e37a98e80d1cb51bca` |
| acquisition | `a988586935c7b8652d957ef3cb8fe14b5d87040994df22992857cba536939b3e` |
| policy | `4aaf74145f884c3850ecc8c7c0c1362ed5adf180a8cd3b8564a71d2cbeb8f9dc` |

The D2 draft PR is stacked on `codex/d1-deployment-report` to preserve #234;
retarget it only after that dependency is resolved through its own review.
The PR's exact commit and native checks are the ordinary resume inputs; no
candidate documentation check replaces the deployed-source runtime CI above.

The deliberate second pass reviewed authority/expiry/identity, exact STOP and
zero pending outcomes, no duplicate writer, custody/failure domains, response
loss/idempotency, absent optional inputs, exhausted budgets, package/config
custody, redaction, rollback and missing financial values. No demonstrated
product defect requiring an undeployed corrective change was found. Existing
explicit-STOP transition and uncommissioned sink/custody remain disclosed gates,
not permission to clear STOP or broaden D2.

Rollback impact: documentation only. Revert this report/index change if needed;
runtime, protected configuration, keys, backups, counters and STOP were unchanged.
Retain this branch, PR #234 and ignored evidence. No D2 remote temporary container,
service, forwarding process or acquisition campaign was created; none remains
to stop. Human profile setup remains an owner action, not an automated acceptance.
