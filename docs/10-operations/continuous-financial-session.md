# Continuous financial session: preparation and gated commissioning

Date: 2026-10-25. Status: engineering preparation, not deployment or Live authority.
The [proposed decision](../04-architecture/adrs/ADR-0023-bounded-financial-session.md)
and [requirements](../03-requirements/continuous-financial-session.md) own the
new contract. Existing [delivery/rollback](delivery-and-rollback.md) and
[installation](independent-platform-shadow.md) remain the operational entrances.

## Immutable prerequisites and handoff

CURRENT engineering entry point: `polysia ops session`. All commands below are
future operator procedures. This engineering task ran only deterministic fakes,
local help/schema/rehearsal and temporary store tests. It authorized no real
provider or account acquisition, commissioning, deployment, Live run or alerts.

1. Integrate only after separate approval. Retain PR #230's dependency on #229,
   exact final source/native CI receipts, source-bound wheel/image hashes and
   release manifest. Local Python 3.14.7 is not a 3.14.8 release receipt.
2. Accept ADR-0023's operational contract and the restricted standard CTF V2 EOA
   route. No negative-risk/V3, proxy/Safe/deposit wallet or nonempty migration is
   supported. The pinned SDK's exchange/collateral contracts must match.
3. Assign one eligible active host and dedicated account. Review native OS ACLs
   and filesystem atomicity, trusted issuer key installation, egress ownership,
   disk floor and failure-domain protection. Keep the second host fenced.
4. Separately authorize bounded public Shadow acquisition and read-only account
   qualification. Verify all-or-error historical RPC completeness, real canonical
   occurrence identity, account orders/trades/fees/cash/holdings and timing. A
   public positions inventory is insufficient. Freeze independently reviewed
   numeric request/page/byte/cost/storage/latency bounds from actual samples.
5. Produce retained causal follower samples and a frozen SharedCohortSelection
   using the existing source-cohort service. Qualify estimator calibration,
   stationarity and independence assumptions; missing estimates block selection.
   Do not substitute provider rank or synthetic samples. No viable Live cohort
   has been established here.
6. Install the exact config/schema/policy/sample/cohort/capacity identities. The
   owner signs the version-2 envelope externally. No private issuer interface is
   supplied. Provision only a fresh complete flat opening, still under STOP.
7. Verify isolated recovery and run the independent supervisor. Release only the
   initial commissioning STOP after exact proof. Explicit/supervision STOP is
   latched and cannot be cleared by that commissioning flag.
8. Obtain separate run-specific account/financial authority and operational
   acceptance before any Live tick. A test, draft PR or document grants none.

### Identity and privilege matrix

| Principal | Necessary access | Excluded access |
|---|---|---|
| External owner issuer | Exact envelope and immutable release/config identities, private signing key outside runtime | Browser/research issuance |
| Commissioning operator | Public trust registry, unused financial paths, consumed-receipt custody, complete approved opening | Automatic allowance reissue or counter reset |
| Financial worker | Signer/API secret references; write own journal/witness/outbox; read independent custody | Issuer private key, modifying STOP/ACK/revocations |
| Independent supervisor | Read journal/witness/outbox/backup; write independent custody and status; execute restrictive STOP | Signer, venue client, strategy or authority issuance |
| Research/Shadow | Its own stores and one bounded acquisition allowance | Signer, financial journal/custody writes |
| Console/gateway | Redacted publication, protected scoped command queue and role/target registry | Secrets, financial journal, financial issuance/provisioning |

Install actual ACLs under a separately authorized reviewed deployment. File
modes do not establish Windows process isolation. Custody must remain writable
only by its privileged owner; worker verification uses read-only SQLite access.
The same administrator controlling every store is outside this local rollback
threat model. No new privilege/service configuration was installed here.

### Contracts and exact command sequence

Use the installed release's schemas rather than copying test authority:

```powershell
polysia ops session schema config
polysia ops session schema authority
polysia ops session schema policy
polysia ops session schema shadow
polysia ops session schema acquisition
polysia ops session schema tape
polysia ops session inspect --config C:\protected\session.json
polysia ops session run --config C:\protected\session.json --mode DATA_ONLY
polysia ops session rehearse --tape C:\review\tape.json --policies C:\review\policies.json --output C:\review\comparison.json
```

`inspect` reports config/policy/package-tree identities and secret *references*,
not credential values or verified authority. The config binds absolute protected
paths, package-tree digest, release, host, account mapping, policy, input-file
SHA256s, RPC/contracts, per-action upper bounds, cadence, risk and backup limits.
The owner receipt signs canonical `session-owner-receipt/v1` over the entire
SessionAuthorization (version 2), key/receipt IDs and exact binding. Trust JSON
maps key ID to base64 Ed25519 public bytes only. CopyPolicy fingerprint freezes
its version and all parameters. The `schema` command grants no authority.

Separately authorized read-only qualification uses the same concrete account
reader with an independent AcquisitionPolicy, no financial custody or signing
operation. Supply exact instrument scopes and already installed credential
references. Output contains protected account evidence and must not be a web
path:

```powershell
polysia ops session qualify-account --config C:\protected\session.json --scopes C:\protected\scopes.json --policy C:\protected\read-policy.json --allowance-store C:\readonly\allowance.sqlite3 --output C:\readonly\opening.json --read-account
polysia ops session lab-init --config C:\shadow\lab.json --commands C:\control\commands.sqlite3
polysia ops session lab-poll --config C:\shadow\lab.json TARGET --acquire
polysia ops session qualify-retained --database C:\shadow\shadow.sqlite3 --experiment EXPERIMENT --selection-start UTC_START --selection-end UTC_END --evaluation-start UTC_EVALUATION --available-at UTC_AVAILABLE --horizon-seconds 60 --tolerance-seconds 5 --output C:\review\qualification.json
```

Replace uppercase tokens with approved actual IDs/ISO-8601 UTC windows. The
qualification output's `samples` array is the bound follower-sample input; its
qualification records feed `SourceCohortService.select` with retained discovery
snapshots and explicit policy. Preserve selection/evaluation separation and
review exclusions; the composition recomputes evidence. Shadow configuration
binds candidates' actual addresses, source contracts, policies and acquisition
allowance. At most four slots; no automatic cohort rollover or parameter search.
A capacity artifact must be `financial-session-capacity/v1`, actual host/workload
digest from `capacity_workload(config)`, synthetic=false, PASS, measured sample
count and observed/expiry UTC. It is reviewed qualification evidence, not a
self-authorizing editable capacity setting; the signed config binds its SHA256.
No universal numeric production capacity is claimed.

After all commissioning authority exists, the protected local sequence is:

```powershell
polysia ops session validate --config C:\protected\session.json --authority C:\protected\authority.json --trust C:\protected\public-keys.json
polysia ops session provision --config C:\protected\session.json --authority C:\protected\authority.json --trust C:\protected\public-keys.json --commission
polysia ops session verify-recovery --config C:\protected\session.json --authority C:\protected\authority.json --destination C:\recovery\UNUSED_GENERATION
polysia ops session supervise --config C:\protected\session.json --authority C:\protected\authority.json --trust C:\protected\public-keys.json --backup C:\recovery\UNUSED_GENERATION\receipt.json --release-stop --ticks 100000
polysia ops session run --config C:\protected\session.json --authority C:\protected\authority.json --trust C:\protected\public-keys.json --mode LIVE --live-enabled --ticks APPROVED_TICKS
```

Supervision runs independently (50 ms checks, bounded tick count); arrange a
separately authorized process lifetime before starting a worker. It performs no
venue I/O. Worker cadence is frozen at 1-30 seconds and at most half the evidence
age bound. Refresh backups under approved operations before maximum age; stopped
or expired supervision blocks the worker. `verify-recovery` makes isolated
copies and restore checks, never installs an active witness/custody or releases
STOP. An actively changing capture rejects; retry only the read-only capture
under an approved quiescent window. Verify real restore duration and recovery
objective separately. Local separate paths are not offsite protection.

Use existing scoped controls for Shadow and restrictive session STOP:

```powershell
polysia control scoped-preview shadow.create TARGET --database C:\control\commands.sqlite3 --registry C:\protected\operators.json --arguments '{"policy_digest":"FROZEN_DIGEST"}'
polysia control scoped-apply PREVIEW_ID EXPECTED_REVISION UNIQUE_KEY --database C:\control\commands.sqlite3 --registry C:\protected\operators.json
polysia ops session lab-execute --config C:\shadow\lab.json --commands C:\control\commands.sqlite3
polysia ops session lab-publish --config C:\shadow\lab.json --output C:\publication\shadow-lab.json
polysia ops session emergency-stop --custody C:\custody\custody.sqlite3 AUTHORITY_FINGERPRINT
polysia ops session revoke --config C:\protected\session.json --receipt-id RECEIPT_ID
```

The native registry is `scoped-operator-registry/v1`, exact host, `roles` mapping
native username to `operator`, and explicit `targets`. Gateway role/target scope
is independently protected. Preview TTL is at most 300 seconds. Accepted requests
remain REQUESTED until the owning executor records the actual effect. Crashed
CLAIMED requests become failed/UNKNOWN, never automatic replays. Other typed
operations are clone/start/drain/resume/finalize/archive/compare and policy.stage;
staging changes only an unstarted slot. Financial STOP target is exactly
RUN_ID:stop; no browser run/resume/provision/issuer operation exists. The Console
reads independent `supervisor-status.json` and optional `shadow-lab.json` beside
the redacted worker report; a missing/stale sidecar cannot imply readiness.

## Recovery and incidents

STOP/kill denies mutations. DRAIN prevents new entries; it does not itself grant
exits. Entry expiry permits only separately scoped protective actions, before
their own deadline and with all venue/account/Risk/supervision checks intact.
Redemption, approval and transfer require separate authority. If closure is
ineligible, retain evidence and report the incident; do not bypass restrictions.

Preserve the private financial file, witness and externally retained checkpoint.
On restart require the exact envelope and checkpoint; refresh independent
supervision and reconcile complete cash/positions/orders/fees before explicitly
resuming entries. An uncertain submission retains attempt and reservation until
authoritative reconciliation; never retry a submission because a timeout,
empty page or 404 looks like failure. A cancellation ACK remains pending until
the existing bounded finality gate and fee-aware account evidence agree.

The active witness is excluded from ordinary financial backup restore.
Isolated witness snapshots are allowed only for integrity verification, never
for replacing active custody or refunding allowance. Restoring the
financial database alone against an advanced witness is rejected. Restore of
both files and external checkpoint control cannot be detected by a purely local
process; it is prohibited as automatic recovery and needs an independent owner
reconciliation decision. Never run two hosts with copied signer/authority state.

Rollback stops the new composition and chooses retained compatible code. Keep
STOP, consumed authority and both state files. There is no database downgrade,
counter reset, automatic schema migration or automatic wider cohort.

## Goldsky value gate: DEFER

Current official documentation was checked on 2026-10-25. Goldsky provides
managed indexing/query/streaming capabilities, and Polymarket lists it as a data
resource. That establishes neither a usable endpoint/schema nor measured
incremental coverage for this account/cohort. Third-party schemas may lag venue
contracts. No account, subscription, endpoint probe, acquisition or integration
is authorized or performed here. The first two-source slice does not require it.

A later authorized bounded experiment must freeze: common chain/contract/schema
versions, exact cohort/window, canonical transaction/occurrence keys, venue
collateral/settlement-route compatibility, pagination/cursor start/end and
history completeness, finality/reorg handling, timestamp/clock quality and
request/byte/storage/cost ceilings. Retain every exclusion and missing interval.

Compare native/PolyCop overlap and exclusive usable observations on the same
window, earliest attributable delivery and delay distributions, confirmed-event
coverage, follower-size/exit feasibility and source-removal replay. Label replay
counterfactual. Record request/storage/infrastructure costs separately from
actual trade cashflow. Report terms/access constraints and provider quotes with
their dates. Predeclare minimum useful exclusive coverage, freshness and
cost-benefit thresholds before acquisition; no post-hoc threshold selection.

Decision choices: ADD only with demonstrated marginal value and authority;
LIMITED_USE for a bounded proven role; REJECT for incompatible contracts or
negative value; otherwise DEFER. Missing evidence now: approved access/budget,
current endpoint-specific schema/contract coverage and terms, overlapping raw
observations, finality/history/cursor completeness, usable attribution,
latency/resource/cost measurements and frozen acceptance thresholds.

Official references:

- [Polymarket order lifecycle](https://docs.polymarket.com/concepts/order-lifecycle)
- [IP limits and separate signer limits](https://docs.polymarket.com/api-reference/rate-limits)
- [Data resources and schema caveat](https://docs.polymarket.com/resources/blockchain-data)
- [Geographic restrictions](https://docs.polymarket.com/api-reference/geoblock)
- [Authenticated account order stream](https://docs.polymarket.com/trading/realtime-order-updates)
- [Goldsky managed product overview](https://docs.goldsky.com/introduction)
- [Goldsky subgraph contract family](https://docs.goldsky.com/subgraphs/introduction)

## Performance and acceptance reporting

The existing request scheduler remains instance-local. The composed session's durable
budget owns actual SDK/RPC HTTP requests, queue admission, pages, bytes and cost; it does not establish a
global IP budget for unrelated processes. Actual installed worker sharing and
IP/signer tiers require the separately authorized host inspection. Native
diagnostic cap 10 and software cohort envelope 40 remain software facts, not
vendor limits or observed capacity. Discovery-row fixture tests do not measure
hot subscriptions. No new broker, database service or language is introduced.

Use monotonic local stage durations and source UTC clock-quality flags. Missing
and restart-censored spans stay unknown. Existing latency-intelligence policy
requires 20/100/1,000 samples for P50/P95/P99 respectively. No credible production
percentile or 99% supervision claim exists from deterministic fixtures. Report
queue pressure, expiry and resource costs with explicit windows/denominators;
do not infer low pressure merely from absence of 429s.

The PR must distinguish LIBRARY_ENGINEERING, COMPOSED_ENGINEERING, INTEGRATION,
DEPLOYMENT, AUTHORIZATION, OPERATIONS and ECONOMICS. Fixture-tested actual
collaborators establish connected engineering, not real provider qualification.
Integration remains pending; deployment is not performed, Live is not authorized,
operations are not commissioned and economics are not observed.
Human operator acceptance, host performance and sustained economic observation
remain separate receipts. No removal of legacy working behavior is required;
only proven unreachable task-owned code may be retired with compatibility proof.
