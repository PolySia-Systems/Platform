# OP1 operational readiness and unsigned Live proposal

**2026-11-08. PREPARATION_COMPLETE_WITH_LISTED_DEPENDENCIES.** Public Console
cutover and private rollback are verified. Actual financial commissioning
remains pending. No real orders, cancellations, transactions, signatures,
transfers or money movement occurred. No OP1 acquisition process or timer remains.

## Readiness and coverage

| Journey | Evidence and cutoff (UTC) | Result and next check |
| --- | --- | --- |
| ACCESS | Public cutover and private rollback verified on 2026-11-08. See [cutover evidence](#public-console-cutover). | **PUBLIC VERIFIED / PRIVATE ROLLBACK VERIFIED.** The owner session reached the application, APIs and exact installed assets. Anonymous edge and origin protection passed. |
| HUMAN_ACCEPTANCE | Dated private browser evidence and current automated checks. | **PENDING.** The operator completes the card below. |
| ACCOUNT_ROUTE_COMPATIBILITY | Installed source and pinned SDK `0.13.0`; current contract docs list the same Polygon 137 standard CTF Exchange V2, CTF, pUSD and collateral adapter. Actual pinned-SDK deterministic signature/read tests passed. Public geoblock returned allowed for the Helsinki egress at 12:21:41. | **DOCUMENTED ROUTE MATCH / ACTUAL ACCOUNT UNKNOWN.** Helsinki's point-in-time IP result cannot establish account or owner eligibility. Verify the designated signer/funder, signature type 0 and exact standard token route at activation. |
| ACCOUNT_STATE | The protected report still exposes no authenticated financial snapshot. No current approved account designation or pre-provisioned account/RPC bindings were established. | **UNKNOWN.** Use the supported read-only qualification on exact instruments and approved account. Require complete pagination, finalized cash and CTF positions, open orders, fills/fees, canonical occurrences and no unexplained balances or orders. Start flat only. |
| SOURCE/COPYABILITY | Original N3 checkpoint through 2026-11-07 00:14:46.901 UTC. 61 opportunities with historical schema `1.0`, 54 retained follower samples, zero complete canonical forward pairs at a 60 s horizon and 5 s tolerance. OP1 public sample at 12:21:41â€“12:21:42 is described below. | **ENTRY NOT QUALIFIED.** Historical source IDs and fees do not supply canonical paired entry/exit evidence. Freeze selection before evaluation and require confirmed native occurrence, attributable fills, usable depth and fresh fees/quotes for the exact token and proposed shares. |
| CAPACITY | 12:17:23 Helsinki read had 21,193,957,376 free disk bytes and 3,022,778,368 available RAM bytes. Public diagnostic took 0.980 s across four requests in the capped container. | **HEADROOM AT OBSERVATION / FINANCIAL CAPACITY UNKNOWN.** Qualify actual bound workload, paging and reserve costs, latency, failure modes and expiry. No production percentile follows from four requests. |
| CUSTODY/SUPERVISION | Protected acceptance/revocation, checkpoint ACK, lost supervision and single writer passed in isolated fixtures. No corresponding Helsinki financial session unit or provisioned authority was established at 12:22. | **FIXTURE PASS / UNCOMMISSIONED.** Review ADR-0023 trust and native ACLs, one active writer, independent supervisor lifetime and off-host checkpoint ownership. |
| PROTECTIVE_EXIT | Tests cover accepted/rejected/partial orders, lost reply and no resend, DRAIN/STOP, cancellation/finality, reserved capacity, stale/unknown evidence and fee-aware reconciliation. Public book lacked an ask. | **FIXTURE PASS / REAL EXIT UNPROVEN.** Freeze per-run protection, validate closeability and dust outcomes, and assign the owner for residual exposure. |
| FINANCIAL_RECOVERY | N3-R1 encrypted independent restore 2026-11-08 06:13:29 UTC was fenced and preserved the virtual ledger and consumption. Isolated financial tests deny stale restored journal, missing independent checkpoint, refunded attempts and a second writer. | **FIXTURE PASS / ACTUAL FINANCIAL RECOVERY UNCOMMISSIONED.** Drill the new financial state/ACL/checkpoint delta on isolated copies. Never install a restored witness or signer on a second active host. |
| ALERT_DELIVERY | Local incident sink test covers durable deduplication, failed delivery and rate limiting. | **NOT_COMMISSIONED.** No external message sent. See owner packet for proposed destination and exact test. |
| ENGINEERING_DELIVERY | Installed N3-R1 runtime source and [full runtime CI](https://github.com/PolySia-Systems/Platform/actions/runs/42452378743). 166 focused tests passed for OP1. [Exact CI attribution correction](https://github.com/PolySia-Systems/Platform/issues/208#issuecomment-6720505713). | **OP1 DOCUMENTATION AND DIAGNOSTICS.** No source or host service configuration changes. #264 remains closed/unmerged and #208 remains open. |
| LIVE_AUTHORIZATION | No version-2 financial receipt or commissioned opening was issued or used. | **NOT_AUTHORIZED / NOT_PERFORMED.** Revisit only after prerequisites and a frozen run can be reviewed. |

## Installed access and retained state

Helsinki serves release `0.4.0`, source
`96ddb5d887003423c10d9b118f6a9c0f1b53f0d7`, image
`sha256:5d804d55caa770dc0367d0868244d5dd4e34475d8e2fb69bacfd2db02b222d26`.
The private web config SHA-256 was
`7ac34d88de2b4b766d953217316da7b5195a7c098cde4619703bf56410c2de82`.
The private CA fingerprint still matches the
[D2 handoff](console-d2-readiness-2026-10-28.md#console-access-and-human-acceptance-card).
SSH forwarding and the separate browser trust context are the usable access
procedure. Keep them available through any future public transition.

Six private Console API reads returned 200. The HTML and JS/CSS returned 200.
The served JS and CSS hashes matched the exact installed source
(`b05a8dd955473e0adcb8304583ae62b0f044addb40e9265dc02e20cce7bc90ce`
and `1f16834e3489f82de4efb9b7d9cfb37230079a1316763445411f3c1bbe3b820a`).
Anonymous report was 401. Reader health was 200. Reader POST, wrong-origin
POST and missing-CSRF POST each returned 403 for their intended guards. The
queue stayed at five historical commands through revision five and zero pending
or claimed. The publisher wrote at 12:21:11 UTC and correctly reported
`STALE_WORKER_RECEIPT`, retaining the virtual cutoff of 2026-11-07 00:14:45.901
UTC. The v1 financial view returned UNKNOWN with no commissioned session.

Read-only N3 authority at 12:15:41 UTC and 12:25:37 UTC showed STOP, the restart fence, an inactive
acquisition timer, one historical grant and 2,290 attempts / 5,417,306 bytes /
zero uncertain reservations. The old campaign phase is retained historical
metadata. Nuremberg remains recovery-fenced. The 19h 17m 06s of historical
observation and later installed recovery proof are separate evidence. See
[N3-R1 closure](nonlive-n3-health-2026-11-06.md#n3-r1-incident-closure).
Original N3 remains `48H_NOT_QUALIFIED`.

## Public Console cutover

2026-11-08, 15:31â€“15:36 UTC. The owner activated Zero Trust Free. The existing
self-hosted Access app and its sole owner email policy were verified. The
canonical [public Console](https://console.movafegh.com/) serves the existing
dedicated tunnel and a loopback HTTP origin at 127.0.0.1:8765. A terminal 404
ends ingress. The public web unit uses the installed N3-R1 image and supported
Cloudflare profile with independent RS256 issuer, audience and role checks.
The existing private Caddy/web pair stays active on 127.0.0.1:8443. The two
web units use separate identity settings and CSRF secrets, read the same
publication and use the existing authorized command queue. Neither mounts
worker financial or authority stores. The public web config SHA-256 is
b01afc0063fc698e5d99f58e003482eeb7acb7eccb3e0b755bba255425374e63.

- Helsinki runs one enabled dedicated connector with four edge connections.
  Pinned cloudflared 2026.10.1 matched the recorded binary checksum. systemd
  supplies the dedicated runtime token through a root-only credential file.
  No management token or shared tunnel change was required.
- After connector restoration, the existing owner browser session reached the
  origin and initially received identity_required. The role map was restricted
  to the verified Gmail mailbox and its lowercase spelling. The next browser
  reload rendered the Console. This resolved the observed application denial.
  The earlier reported redirect loop did not recur. Its original cause was
  not independently isolated.
- The authenticated browser returned 200 for HTML, the exact installed CSS
  and JavaScript hashes above, /api/report and /api/console/v1/snapshot.
  The report still shows STALE_WORKER_RECEIPT and real_orders=false. Anonymous
  public requests for those five paths redirected to the verified Access
  issuer under normal TLS. Direct loopback requests without assertion
  returned 403 for all five paths. Wrong-role, signature, origin and CSRF
  behavior is covered by the focused tests and the earlier installed private
  denial checks. A second public identity was not enrolled or used.
- Stopping both public units left authenticated private TLS returning 200.
  Both public units were restarted and the owner browser reached the Console
  again. Emergency rollback over verified SSH stops only the public units
  with systemctl disable --now polysia-platform-tunnel.service followed by
  systemctl stop polysia-platform-edge-web.service. The private SSH/CA
  route and its independent emergency procedure remain available.
- After the rollback rehearsal and public recheck, removed only the unused
  platform.polysia.movafegh.com A record. The rollback values are 37.27.8.79,
  proxied, TTL Auto and comment CoreOS service - PolySia. The canonical tunnel
  record and unrelated resources were preserved. The old shared management
  credential rotation status remains unverified and outside this cutover.
- At 15:35:57 UTC Helsinki showed the N3 STOP and restart fence, the worker
  timer inactive, 2,290 historical attempts, 5,417,306 bytes and zero unknown
  reservations. Nuremberg remained fenced. Six private authenticated API
  reads passed at 15:36:02 UTC with zero pending commands. No additional
  grant, provider acquisition or financial action was performed.

Affected checks used systemd-analyze verify and the installed tests above.
The focused gateway/Console suite passed 19 tests during staging. The three
identity, CSRF and exclusive-profile tests were rerun on cutover and passed.
The unrelated host xfs_scrub unit warnings about removed CPUAccounting were
unchanged. The human operator card is still pending.

## Bounded public diagnostic and historical replay

One Helsinki container on the installed image used an isolated, stopped-on-exit
durable acquisition store with pre-I/O reservations. Its fixed scope was the
official geoblock, Data API v2 trades, Gamma markets and CLOB book. The tighter
local caps were three minutes, eight total and hourly requests, 8 MiB total and
hourly bytes, 1 MiB per response, 10 s socket timeout, one observed public
identity and a 9 GiB disk floor. Container limits were 256 MiB RAM and 0.25 CPU.
No RPC, authenticated account access, ongoing scheduler, or old grant reuse.
First I/O was 12:21:41.756 UTC. The run stopped at 12:21:42.734 UTC after **four
attempts / 9,728 bytes / zero uncertain**. Its policy expired at 12:24:41.739 UTC.
This used the one OP1 finite exercise. Its unused capacity is closed.

A complete available-page walk of a frozen 20-minute public window returned two
rows for one retained watch. Latest source event was 12:16:10 UTC. The mapped
book was dated 12:21:40.205 UTC with a 5-share minimum, 0.001 tick, standard
non-negative-risk flag and 0.07 taker fee parameter with exponent 1. Bid was
0.999 and the ask was absent. This token was ineligible for entry. No forward
pair, canonical on-chain occurrence, fresh next-run input or valid cohort was
established. Protected raw evidence is under
`/var/lib/polysia-platform/op1-qualification-20261108.ANLV48vn`.

Offline replay used isolated SQLite snapshots with networking disabled. The
post-transition snapshot was rejected by the retained follower reader with
`retained_follower_evidence_binding_changed`. All 61 original rows match their
payload/selection hashes but retain the original config/code identities.
The pre-transition checkpoint verified those original identities and yielded
the 54 samples and zero complete pairs above. Retain both states and use the
original checkpoint for historical replay. Fresh source acquisition is needed
for canonical pairs. Rebinding the historical rows would erase provenance.

## Human operator card

1. Open the [private Console](../10-operations/independent-platform-shadow.md)
   at `https://localhost:8443` through the verified SSH forward and the
   dedicated CA profile. Use the protected owner reference from the runbook.
2. In Operate and System, explain the host DATA_ONLY/Live-disabled state, stale
   worker versus fresh publisher, and missing financial and supervisor evidence.
   Identify the cutoff and distinguish simulated fills from real balances,
   positions, fees and costs. Explain the unknowns in Evaluate and Investigate.
3. Read an existing command receipt. Explain REQUESTED versus APPLIED, loss of
   response and lookup by the original key. Compare command history to current
   durable STOP. Exercise this card without submitting a command.
4. Locate protected SSH STOP for acquisition and the separately privileged
   `polysia ops session emergency-stop` for an actual commissioned run. Explain
   that STOP does not cancel venue orders. Record who responds on loss of public
   route, TLS or credential expiry, failed timers, disk floor or supervisor loss.
5. Record participant, UTC, exact release/bundle and report generation, each
   result, concerns and explicit acceptance. Automated checks above are separate.

## Unsigned Live proposal for later review

**RECOMMENDED, inert, ungranted.** Use the existing bounded financial-session
composition. Prefer Helsinki as sole writer, one explicitly designated flat
EOA with signer = funder, one corroborated frozen leader, one active standard
CTF condition and one outcome, one entry attempt, one open position and one
concurrent order. Prefer the native source plus already approved canonical
Polygon corroboration. Keep PolyCop separate until its incremental evidence
is qualified. No compatible designated account, instrument or cohort is bound
here. The sampled token is excluded.

The official contract map matches the pin: standard exchange
`0xE111180000d2663C0091e4f400237545B87B996B`, CTF
`0x4D97DCd97eC945f40cF65F87097ACe5EA0476045`, pUSD
`0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB`, CTF collateral adapter
`0xAdA100Db00Ca00073811820692005400218FcE1f`.
Recheck the [contracts](https://docs.polymarket.com/resources/contracts),
[pinned SDK release](https://pypi.org/project/polymarket-client/0.13.0/),
[book rules](https://docs.polymarket.com/api-reference/market-data/get-order-book),
[fees](https://docs.polymarket.com/trading/fees) and
[venue eligibility](https://docs.polymarket.com/api-reference/geoblock) against
the selected instrument and activation cutoffs. Existing data is historical.

- **Size and loss.** Start at the greater of the verified entry and exit share
  minima, rounded up to the legal quantity quantum, with sufficient two-sided
  depth at that quantity. The observed 5 shares and 0.001 tick are reference
  values for the excluded token. For the eligible token use Decimal limit price
  times exact shares plus worst-case entry fee as the all-in order and exposure
  cap. Reserve verified exit fee, executable spread/slippage, rounding and
  reconciliation costs separately. Capital and maximum daily/total loss must
  cover the single entry's full worst-case debit plus nonrecoverable reserves.
  Set a total turnover cap that includes one reduction. Reject if residual
  partial-fill dust or the worst case exceeds the owner's cap. Current pUSD
  amounts are unbound pending an eligible book, actual account and owner loss
  ceiling. For a later eligible market with the same 5-share minimum and 0.07
  exponent-1 schedule, recommend an execution-only screening ceiling of 5.175
  pUSD: 5 pUSD maximum gross debit plus up to 0.0875 pUSD per leg before
  venue rounding. The maximum fee follows 5 Ã— 0.07 Ã— 0.25. Reduce the actual
  cap to the selected quote-based worst case, include any rounding and separately
  verified non-venue costs, and reject higher-minimum or higher-fee candidates
  for this first run. The July tiny-run limits were scoped to its own account and SDK.
- **Actions and deadlines.** Cap at four unique mutation slots across the run
  for one bounded limit entry, one exact entry cancellation if needed, one
  risk-checked inventory reduction, and one cancellation of a resting exit
  if needed. Reserve the last three slots for protection and require an exact
  implementation/authority mapping for that ceiling. No automatic retry on
  ambiguous results. Bind an exact entry UTC window, maximum holding time,
  venue-valid order expiry and later protective UTC cutoff, with enough time
  left for authoritative finality and reconciliation. Derive those intervals
  from measured end-to-end timings and venue order rules. No entry if the
  available window cannot cover the protective reserve or the market ends first.
- **Reads and limits.** Use one lifetime aggregate of per-action worst-case
  HTTP/RPC charges, including eligibility, clock, source and book freshness,
  full authenticated pagination and finality. Deduct a separately sized
  protective read/byte/storage/cost reserve before admitting entry. Bind exact
  maxima using the measured authenticated page and recovery workload. The four
  public reads provide no defensible financial budget. Candidate configuration
  and exact times remain unsigned and unset until those inputs exist.
- **Stop and closure.** DRAIN entry at its cutoff or on stale data, divergence,
  source uncertainty, risk or reserve exhaustion. Use only signed `CANCEL`
  and `REDUCE` within their own deadline with current eligibility, Risk and
  supervision. STOP or kill blocks mutations including protection. Reconcile
  open orders, finalized fills/fees, cash and holdings. An ACK is pending until
  finality. Escalate unknown submission, unresolved venue orders, residual
  holdings or dust to the named owner through the approved channel. Keep STOP,
  reservations and immutable evidence. Separately authorize any residual manual
  action. No automatic liquidation, redemption, approvals or transfers.

The [financial session runbook](../10-operations/continuous-financial-session.md)
owns config, schemas and commands. Prepare inactive review bindings for public
trust, pinned package tree/config/policy, candidate universe and frozen
selection/follower/capacity/opening artifacts. Keep worker-only journal/witness
and outbox, supervisor-only custody and ACK, and independently retained
off-host checkpoint. Web and research may read redacted publication and queue
authorized requests. They have no signer or financial store writes. The issuer
private key stays external. Keep the second host fenced. Do not copy any
Shadow inventory or signing material into financial state.

At activation refresh exact config/bundle digests, clock and geoblock, account
and CTF route identity, allowances and complete flat opening, finality, verified
fees/quotes/depth and canonical source evidence, actual capacity expiry,
supervisor ACK, independent checkpoint/backup freshness and STOP disposition.
Use the bounded `qualify-account`, `inspect` and `validate` paths. Release
only a later explicitly authorized commissioning STOP through its exact gate.
An explicit/supervision STOP remains latched. No old fence or counters are reset.

## Owner-designated test account follow-up

The pinned SDK 0.13.0 deterministically classified the protected local account
as a deposit wallet with an owner signer and signature type 3. No address or
credential value is recorded. The laptop's bounded geographic preflight did
not return an affirmative allowance. A direct retry also failed to establish
eligibility. The attempt stopped before authenticated venue access. Deployment,
on-chain owner status, CLOB credentials, collateral, open orders and fills
remain unverified. A qualified Polygon RPC route and an eligible approved
execution context are required for the finalized opening read.

The historical Tiny Live workflow uses consumed, run-specific authorizations.
It is not the OP1 financial session. The scope extension in ADR-0023 adds an
owner-derived type-3 account to the same standard CTF V2 composition. It
reuses its risk, custody, per-action bounds and cancellation/finality gates.
The pinned SDK signs the deposit-wallet order and the adapter verifies its
exact wire maker, signer, economics, exchange and wrapped owner signature.
Qualification uses the same account binding for authenticated CLOB and
finalized chain evidence. This is a code candidate for review, with no rollout
or real signature, order, cancellation or transaction.

The candidate tiny run is conditional on a qualified instrument with a
five-share minimum and the verified fee schedule. Propose one entry of
exactly five shares at a limit of 0.50 pUSD per share or less, with a 2.50 pUSD
maximum gross entry. Use a worst-case taker fee reserve of 0.08750 pUSD per
leg at rate 0.07 and exponent 1. The proposed maximum total loss is 2.67500
pUSD, including both fee reserves. Reject the candidate if independently
verified rounding, other charges or share minimums cannot fit the cap. There
is no funded amount or approved order until eligibility, cash, allowances,
quotes, finality and source evidence are measured and bound.

A later grant may permit one entry, one exact cancellation of its resting
remainder, one bounded reduction of confirmed run-created inventory and one
exact cancellation of that exit if it rests. Keep one open order and one
position at a time. An unknown response consumes the attempt and requires
reconciliation. Quote age, order expiry and the separate protective cutoff
require measured activation inputs. No retry, replacement, wallet creation,
approval, redemption or transfer is included. Residual exposure is reported
under the existing incident and custody procedures.

## Consolidated owner packet

1. Complete the operator card using the verified public Console or private
   rollback route. Confirm disposition of the historical shared and dedicated
   management credentials separately from financial readiness.
2. Decide [ADR-0023](../04-architecture/adrs/ADR-0023-bounded-financial-session.md)
   operational acceptance. Accept or revise the sole-writer, independent
   supervisor, external issuer and off-host witness/checkpoint failure domains
   and define the financial recovery objectives. Supply protected references for
   the explicitly designated eligible EOA, pre-existing account credential
   references and owner-approved RPC/read method scope. A later qualification
   needs its own finite approved window because this OP1 exercise is closed.
3. For alerts, propose one redacted synthetic incident via an existing approved
   email transport to the verified Console owner's mailbox. Confirm exact
   address and transport privately, the UTC test window, one attempt, no
   automatic retry, and owner receipt acknowledgement. If no approved transport
   exists, keep external delivery pending. The owner is primary responder
   through verified SSH. Route/certificate expiry alone confers no authority.
   Missing supervisor, timers or headroom block activation or lead to STOP
   according to their existing policies.
4. Review and separately sign one frozen run only after the missing account,
   source, capacity, custody, recovery and exit evidence are supplied. No Live
   authorization is requested by OP1.

## Validation record

Focused command on the isolated base, Python 3.14.10, SDK 0.13.0:

```text
python -m pytest -q tests/integration/test_financial_session.py tests/integration/test_operational_session.py tests/integration/test_session_custody.py tests/integration/test_session_sources_and_resources.py tests/integration/test_session_policy_controls.py tests/integration/test_retained_follower_qualification.py tests/unit/storage/test_acquisition_authority.py tests/contract/test_polymarket_sdk_behavior.py
166 passed in 64.65s
```

Protected installed GET/denial checks and one metered public sample were
performed separately. The human operator exercise, authenticated financial reads and actual financial
recovery remain pending. The public installed journey is verified above. Existing runtime-main gates were reused for unchanged code and
artifact. OP1 documentation uses the changed-docs, Standards and secret gates.
The #264 correction was verified against [attempt 2, installation-acceptance](https://github.com/PolySia-Systems/Platform/actions/runs/42472604797/job/128711442287?attempt=2).
Backup replacement/nonempty recovery passed. The ACME step failed while reading
the Pebble release download. The download timeout cause remains unknown.
