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
2. Accept ADR-0023's operational contract and the restricted standard CTF V2
   route. The type-3 extension requires the bound owner key and its
   deterministically derived deposit wallet, plus explicit operational review.
   Negative-risk and V3 markets, proxy and Safe wallets, deposit-wallet session
   keys, and nonempty migrations remain outside this scope. The pinned SDK's
   exchange and collateral contracts must match.
3. Assign one eligible active host and dedicated account. Review native OS ACLs
   and filesystem atomicity, trusted issuer key installation, egress ownership,
   disk floor and failure-domain protection. Keep the second host fenced.
4. Separately authorize bounded public Shadow acquisition and read-only account
   qualification. Verify all-or-error historical RPC completeness, real canonical
   occurrence identity, account orders/trades/fees/cash/holdings and timing. A
   public positions inventory is insufficient. Type-3 account reads also walk
   wallet-wide orders to the terminal cursor and require agreement with the
   credential order view. Budget both reads and retained condition checks.
   Freeze independently reviewed
   numeric request/page/byte/cost/storage/latency bounds from actual samples.
5. Produce retained causal follower samples and a frozen SharedCohortSelection
   using the existing source-cohort service. Qualify estimator calibration,
   stationarity and independence assumptions; missing estimates block selection.
   Do not substitute provider rank or synthetic samples. No viable Live cohort
   has been established here.
6. Install the exact config/schema/policy/sample/cohort/capacity identities. The
   owner signs the version-2 envelope externally. No private issuer interface is
   supplied. Provision only a fresh complete opening with no orders, still under
   STOP. An assessed opening can retain holdings in mapped, finalized resolved
   conditions outside all executable markets. Retained quantities must continue
   to match the account. They confer no authority and contribute no run P&L.
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

Prepare a version-2 draft with `granted=true` and `owner_receipt="UNSIGNED"`.
Write the canonical bytes with `polysia ops session receipt-message --authority
DRAFT --key-id KEY_ID --receipt-id RECEIPT_ID --output MESSAGE`. The owner reviews
those exact bytes and signs them with the trusted Ed25519 issuer outside the
worker. An offline OpenSSL issuer can use `openssl pkeyutl -sign -rawin -inkey
OWNER_KEY -in MESSAGE -out SIGNATURE`. Attach the 64-byte signature with
`polysia ops session attach-receipt --authority DRAFT --key-id KEY_ID
--receipt-id RECEIPT_ID --signature SIGNATURE --trust PUBLIC_KEYS --output SIGNED`.
This verifies the signature. Use `validate` for the exact host binding and time
window before provisioning under STOP.

For a reviewed single-entry run, bind config "exact_entry" to the fixed share
quantity and price ceiling. In ACCOUNT scope the regular strategy and fresh
qualified source supply the candidate. In ORDER_LIFECYCLE_API scope the explicit
owner command supplies an OwnerTestIntent, without a leader occurrence or
claimed profitable edge. The local owner adds "--owner-entry" explicitly to
the installed "polysia ops session run" command after commissioning, using
"--mode LIVE --live-enabled --owner-entry" with the signed config, authority and
public trust registry. This foreground invocation follows the signed
protective deadline instead of the ordinary tick count. Leave the option out
for protective-only operation on an
exact-entry session. Risk may deny the entry. A smaller Risk size, a price above
the signed ceiling or any prior durable buy reservation blocks submission.
Inspect the redacted session publication and the independent supervisor status
before taking any further action. An absent qualified candidate does not
constitute a submission.

Separately authorized read-only qualification uses the same concrete account
reader with an independent AcquisitionPolicy, no financial custody or signing
operation. Supply exact instrument scopes and already installed credential
references. Keep the protected account evidence outside web paths.

### OP1 owner-operated API order lifecycle

This test has a narrower acceptance scope than continuous financial operation.
Its evidence is available collateral and allowance, the selected token's CLOB
balance, wallet-wide open orders, authenticated credential trade visibility,
and order details and confirmed fills tied to the test's own order IDs.
Complete wallet inventory and lifetime cash, fees and P&L are outside this
test's evidence. Unknown fees, pending fills, absent details and unrelated
positions are not inferred from wallet balance changes.

The protected read-only entry point is `qualify-account --read-account
--order-lifecycle`. Use one standard type-3 market and a separate finite
allowance whose exact endpoints are the venue eligibility check, CLOB
orders, wallet-open-orders, trades, balance-allowance, fee-rate and exact
clob-markets path, plus the Gamma markets endpoint. Pass a protected
`--lifecycle-orders` JSON mapping exact order IDs to BUY or SELL to include
the corresponding order-detail paths. The qualification mode uses only GETs
and never creates a complete-account opening receipt or financial authority.
An absent order detail does not establish cancellation.

A fee rate is not a charged fee. The scoped report recognizes zero fees only
with explicit official market evidence. An unpriced fee leaves run fees and
P&L unknown. A reported round-trip P&L uses only the confirmed run fills and
requires a flat run inventory and verified order terminal evidence.

The observation carrier records its evidence scope. The default remains
ACCOUNT. A scoped journal must be provisioned explicitly with an
ORDER_LIFECYCLE_API opening and its signed configuration. Its selected-token
opening and run fees start at zero; complete wallet inventory remains
unassessed. A default full-account provision rejects this observation.
The API session adapter requires fresh explicit zero-fee evidence and compares
the tested token's current balance and owned fills. Current collateral and
allowance constrain available spending. Cash changes never enter test P&L.

Exact-entry sessions durably consume one ENTRY, CANCEL_ENTRY, EXIT and
CANCEL_EXIT slot. A reserved or uncertain submission consumes its slot.
Restart and older-state migration preserve consumed slots conservatively.
The reporting counter includes cancellation slots.

The API composition uses no RPC endpoint, cohort or follower sample files:
set rpc_url and both input digests to empty strings, both input paths to null,
and source_wallets to an empty list. Historical/RPC options must be absent.
The authority's sole allocation alias is owner-test. This is an operator test
request, not fabricated source evidence. Unknown edge is passed to Risk; a Risk
policy that requires positive edge still rejects it. The API capability profile
omits source/alpha qualification but retains all independent financial controls.

Bind exactly five shares and a price ceiling at most 0.50. Freeze the distinct
entry window (authority.expires_at), GTD expiry (exact_entry.order_expires_at),
holding limit and protective deadline. The GTD expiry must follow the entry
window and leave four socket timeouts before the protective deadline. The
protective window must additionally accommodate the holding limit. One position
and one simultaneous order are mandatory: the entry must have verified finality
before the single exit can be reserved. A partial fill below venue minimums may
remain owner-managed exposure; it never authorizes a replacement order.

The GET-only qualification emits scoped_opening only when the selected token is
flat, collateral/allowance are usable, no order or pending trade is present and
zero costs are explicitly established. It never emits a complete-account
opening. Bind that exact scoped_opening into the signed configuration and
validate freshness during commissioning. During a pending settlement the
foreground worker drains entry and continues bounded reads; it grants no interim
account clearance or resend authority. Hard errors still stop the affected run.

After current API qualification, capacity/recovery evidence and the external
owner signature exist, the owner uses the existing command:
`polysia ops session run CONFIG --authority SIGNED --trust PUBLIC_KEYS
--mode LIVE --live-enabled --owner-entry`. This is a command interface, not a
claim that this account has an installed packet or is commissioned. Inspect the
same run's publication for order IDs, fills, fees, inventory and unknowns. The
scoped diagnostic alone cannot start a financial session. No real order is
signed, submitted or cancelled by ordinary tests or deployment.

Initial qualification walks the authenticated trade view to its terminal page
to establish no visible pending trade. The commissioned API runtime then freezes
its trade filter at the signed opening time minus the evidence freshness bound.
It continues full wallet-wide open-order checks and selected-token balance checks;
it does not repeatedly download lifetime trades. The report records this window
and retains credential-limited visibility. Its journal enforces a durable ceiling
of 60 HTTP admissions per rolling minute, at most 1,000 requests, 64 MiB total
response reservations and a two-hour maximum authority. API polling is no faster
than ten seconds. Deferral retains consumption. A verified terminal and flat
lifecycle exits the foreground command early; unknown state or residual inventory
does not satisfy that completion condition.

The optional `historical_instruments` configuration adds account reconciliation
scope. Bind each observed token to its exact supported condition, collateral and
settlement route. Unmapped or incompatible history blocks qualification. Trading
and source discovery use the instruments in the signed authority. The
`rpc_log_block_span` option divides finalized log scans into contiguous inclusive
ranges and charges every request to the active allowance. A range limit may be
handled with smaller pages when the complete scan fits the allowance and timing
limits. Missing archival access or a failed page blocks account qualification.

For an account with substantial history, set `rpc_checkpoint_path` to a dedicated
protected SQLite file and use `qualify-account --prime-history` during the bounded
opening read. Bootstrap scans use the same allowance as the final observation.
The final observation starts its normal freshness clock after priming. Later reads
verify the stored finalized block hash and scan only the next contiguous range.
CTF balances remain pinned to the new finalized block and are read in batches.
Keep the checkpoint outside the financial, custody, witness and publication stores.
Allow only one bootstrap or worker to write it at a time. An incomplete page or
conflicting block hash blocks qualification. Retain the evidence on a conflict.

For an approved Alchemy Polygon Mainnet route, use the exact URL
`https://polygon-mainnet.g.alchemy.com/v2` and set `rpc_bearer_token_reference`
to the dedicated protected environment variable name. The bearer value is sent
only to the RPC transport. Keep the value out of URLs, configuration and evidence.

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
