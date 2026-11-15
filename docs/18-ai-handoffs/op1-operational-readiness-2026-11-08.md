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

**Historical proposal before the type-3 follow-up below.** Use the existing bounded financial-session
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
eligibility. The attempt stopped before authenticated API access. A subsequent
official geoblock GET from the installed Helsinki image returned HTTP 200,
country `FI` and `blocked=false` after a bare-host check returned HTTP 403.
The cause of the earlier 403 remains undetermined. The Helsinki result applies
to that connection's egress. On November 8, 2026, the owner's authenticated
browser portfolio displayed available cash, no positions and no open orders.
This is a browser observation. The browser address was not independently
matched to the configured funder during that observation. Deployment, on-chain
owner status and authenticated CLOB opening evidence remain unverified. The
supported qualification still requires a separately approved finite read
window, a qualified Polygon RPC route and an eligible execution context.

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
   the explicitly designated test account, pre-existing account credential
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

## API-backed owner test commissioning checkpoint - 2026-11-15

This dated checkpoint supersedes the full-inventory/source-cohort acceptance
criteria above only for the owner-approved bounded API order-lifecycle test.
ACCOUNT operation retains its separate requirements. No full-wallet inventory,
lifetime P&L, archival scan, Alchemy onboarding or direct-RPC development is
required for this experiment. Unassessed inventory remains unassessed.

- Engineering: [PR #287](https://github.com/PolySia-Systems/Platform/pull/287)
  merged as `7b8298e4019d2dd7658e5eff63a1deaff01e5044`. Its exact-main
  [CI 43649532836](https://github.com/PolySia-Systems/Platform/actions/runs/43649532836)
  passed, including Windows. Explicit owner intent passes through independent
  Risk, Execution, type-3 signing semantics, four durable mutation slots and
  owned-order accounting. Synthetic transport proves partial fills, uncertain
  submissions, cancellation and restart behavior; it does not prove a trade.
- Deployment: native artifact `14135233159` passed ZIP, canonical manifest,
  archive and installed commit checks. Image
  `sha256:2473b9e713b87fb20ef58bd24b63190feba5e4181d767512351fc7d84a039f8c`
  is installed in the existing `polysia-op1` containerd namespace under STOP.
  Installed API/owner-intent imports and configuration-schema smoke passed.
  Original shared N3 image was unchanged. The prior approved image is retained
  as `docker.io/library/polysia:op1-rollback-38042e6`. No financial worker is active.
  Receipt: `/var/lib/polysia-op1/releases/7b8298e4019d2dd7658e5eff63a1deaff01e5044/deployment-receipt.json`.
- Current account observation: Helsinki GET-only API qualification at
  `2026-11-15T01:28:34.146596Z` verified the designated type-3 signer/funder
  mapping through the supported SDK and authenticated account path. Venue
  eligibility returned FI/unblocked. Usable collateral was 10.213845 pUSD;
  wallet-wide open orders, credential-visible pending trades and selected-token
  balance were zero. This proves scoped account connectivity, not a complete
  account verification or a trading result.
- Protective permission: a separate affected GET-only check confirmed existing
  conditional-token exchange allowance sufficient for five shares. No token
  approval or wallet transaction was made. Follow-up engineering adds this fact
  to the API evidence and blocks entry/final reserved-buy refresh if exit
  permission is missing or insufficient, while preserving post-submit reads.
- Technical candidate at that observation: exact instrument identity is retained
  in `/var/lib/polysia-op1/api-read-20261115-r1-resume/proposal.json`.
  Ask 0.08 with 1,482.35 shares; bid 0.07 with 2,712.12 shares; minimum five;
  negative risk false; official zero-fee evidence matched. The technical
  proposal is five shares at a limit of 0.08, gross 0.40 pUSD, with the original
  2.675 pUSD total loss/debit ceiling and four mutation slots. It proposes a
  60-second entry window, separate GTD expiry at T0+195 seconds, 120-second
  holding limit and protective deadline at T0+600 seconds. These are dated
  proposal inputs, not a signed active window or an alpha estimate. Recheck
  current quotes, funds and permissions before freezing an owner packet.
- Resource accounting: the single current-read campaign used 19 charged
  attempts and 828,188 charged bytes, including one fully charged uncertain
  connection failure from a container without network access. The changed
  network configuration used Helsinki host networking; no other location,
  proxy or endpoint bypass was used. Continuation ceilings deducted all prior
  consumption; original stopped ledgers were not reopened. Its total ceiling
  remains 32 attempts/12 MiB, 60 attempts/minute, 512 KiB/response and 15-second
  sockets, within the original broader ceilings. Absolute maximum window ends
  `2026-11-15T03:25:11.674433Z`. All child ledgers are stopped. Temporary credential
  files were removed; API credentials and auth response bodies were not retained.
  Final receipt: `/var/lib/polysia-op1/api-read-20261115-r1-permission/receipt.json`.
- Independent controls: both original host fences remain. An offline live-WAL
  OS-role probe proved read access and denied SQL mutation, replacement and
  directory writes through a read-only control mount. Empty worker/supervisor
  directories use distinct owners, shared read group 981 and no cross-role
  directory write permission. Process umask 0027 and writer-owned mode-0640
  journal/custody files are the prepared deployment contract. This is OS
  preparation, not a commissioned real-run supervisor or recovery receipt.
- One authorized redacted email test used the connected Gmail account whose
  profile matched the verified owner mailbox. Provider message
  `1a1dcdbacc250829` had SENT/INBOX/UNREAD evidence. Human receipt remains pending.
  This manual transport test does not configure the Platform incident sink and
  is not authority for another alert attempt.
- Owner signing: the encrypted offline issuer tool is available at the owner's
  local `artifacts/op1-type3-20261108/op1-owner-issuer.py`. No issuer private key
  was installed in a worker or created on the owner's behalf. The owner public
  registry was absent at this check. A trusted external owner signature, fresh
  frozen opening and actual workload/custody/recovery commissioning evidence
  remain prerequisites. Do not substitute a synthetic capacity PASS or fixture
  signature. Real signing, submission and cancellation counts remain zero.

### Final affected-release verification - 2026-11-15

This addendum advances the dated checkpoint above; it grants no financial
authority and does not report a real-money lifecycle test as completed.

- [PR #288](https://github.com/PolySia-Systems/Platform/pull/288) merged as
  `6ab9c08907c76ed20e893c657c67b9dc55d9f023`. It preserves the selected-token
  exit allowance in scoped evidence and rejects entry when the existing
  allowance cannot cover five shares. Fourteen affected Windows tests passed.
  The exact release's full [CI 43665217457, attempt 2](https://github.com/PolySia-Systems/Platform/actions/runs/43665217457)
  passed. Windows, container, installation, browser, quality and supply-chain
  results were reused; only the failed dependency-health job was rerun.
- Dependency-health repair used the supported scheduled producer/publication
  workflow. Obsolete, behind-main bot PR #280 was closed without rewriting its
  history. Fresh publication run `43665586907`, attempt 2, passed and
  [PR #289](https://github.com/PolySia-Systems/Platform/pull/289) merged the
  development-only filelock lock refresh. Runtime SDK and authentication
  dependencies were unchanged. Other Dependabot proposals remain independent.
- Verified artifact `14141766819` has ZIP SHA256
  `34613db9544b764e5f06d87d02057cdc96d342b1ffb1b78fe3cb2be9a4ce049c`.
  Helsinki and the fenced Nuremberg recovery namespace hold image
  `sha256:b4123688105b86154b9c3408e4577bc8c3e32434da8a430680a71d6348963520`.
  Installed package-tree digest is
  `0813d30fda08759c1ccc6661f4fc5eb2f79bda1229b906ae634827cbd668c01e`.
  Source release remains `6ab9c089`; later development-lock/documentation
  commits are not represented as separately deployed runtime artifacts.
  Helsinki receipt:
  `/var/lib/polysia-op1/releases/6ab9c08907c76ed20e893c657c67b9dc55d9f023/deployment-receipt.json`.
  Recovery receipt: `/var/lib/polysia-op1-recovery/preparation-receipt.json`.
- A cross-host age-encrypted nonfinancial fixture was encrypted on Helsinki,
  transferred and decrypted on Nuremberg with matching plaintext digest.
  The recovery private key stayed root-only on Nuremberg; no wallet credential
  was copied. This proves transport/decryption, not real financial restoration.
  Receipt:
  `/var/lib/polysia-op1-recovery/recovery-transport-probe-20261115/receipt.json`.
- At `2026-11-15T02:44:15.941014Z`, a final GET-only continuation exercised the
  installed SDK's actual Gamma keyset lookup, order book and scoped account
  reader. All 13 HTTP responses were 200, largest 14,709 bytes. Under a fixed
  0.25 CPU / 512 MiB allocation, the measured account/market sample took
  0.809793 seconds; peak process RSS was 112,664,576 bytes. The host/workload
  digest and bounded read-capacity record passed `validate_capacity_record`.
  It has one actual sample and expires at `2026-11-15T03:14:15.940291Z`.
  This qualifies only this limited read workload; it does not establish global
  capacity, production readiness or financial-mutation performance.
- Usable collateral remained 10.213845 pUSD. The selected token balance,
  wallet-wide visible open orders and credential-visible pending trades were
  zero; existing five-share exit permission remained sufficient. The selected
  market still had a 0.08 ask, 0.07 bid, minimum five and explicit zero-fee
  evidence. The observed quote was about 28.3 seconds old: this dated proposal
  must not substitute for the runtime Risk freshness check or a fresh signed
  opening. No full-account inventory or lifetime P&L claim is made.
- The same read campaign is now closed at **32 charged attempts, 846,858 charged
  bytes and one retained uncertain connection attempt**. No allowance was
  reset. Final response cap was 64 KiB, stricter than the earlier 512 KiB cap;
  15-second sockets and the original absolute campaign deadline remained.
  Final receipt and limited capacity evidence are in
  `/var/lib/polysia-op1/api-read-20261115-r1-capacity/`.
- Final host checks found both original fences present, original services
  inactive, no OP1 tasks, no temporary credentials and all read ledgers stopped.
  Helsinki remains `STOP / UNISSUED`; Nuremberg remains recovery-only with a
  financial writer forbidden. Original N3 history and financial state were not
  provisioned, reset or modified. No unmanaged test was left running.

### Concrete owner input and remaining commissioning

The supported owner-entry CLI is implemented and tested. There is no issued,
fresh, commissioned run packet to execute yet. The real prepared files are
`/var/lib/polysia-op1/owner-packet-6ab9c089-inputs/read-config.json`,
`authority-inert.json`, `scopes.json` and `readiness.json`. They deliberately
retain an incomplete opening, false authority and pending capacity binding;
do not run them in Live or interpret them as a signed action. Their older
resource counters are dated inputs; any future frozen packet must retain the
final aggregate consumption above. The observed capacity artifact is separate
and expires; it must not be silently promoted or renewed.

At the final check, both the owner's local issuer public file and the host
trust registry were absent. The next actual owner action is local issuer
initialization, with a passphrase typed only into the local terminal:

```powershell
& 'C:\Users\Siamak\Documents\PolySia\.venv\Scripts\python.exe' 'C:\Users\Siamak\Documents\PolySia\artifacts\op1-type3-20261108\op1-owner-issuer.py' init
```

This creates the encrypted authorization issuer under
`C:\Users\Siamak\Documents\PolySia-Owner`; it does not create a wallet or place
an order. The existing test-wallet key is not this independent issuer.
After enrollment of its public key, a fresh exact packet must be generated,
reviewed and signed with the same tool's `sign` action over the real
`op1-owner-message.bin`. Do not invoke `sign` before that reviewed message
exists. Existing `receipt-message`, `attach-receipt`, `validate`, `provision`,
`verify-recovery` and independent `supervise` commands then perform the
documented checks. Actual custody, financial restore, supervisor STOP release
and a configured incident transport remain commissioning work bound to that
real signed packet; the offline probes do not satisfy them.

The owner's remaining inputs are the private local issuer/passphrase step,
review/signature of the resulting exact bounded packet, and honest human
receipt of the already-sent alert test. No second email test is authorized by
this record. Real trading signatures, submissions, cancellations and observed
trading P&L remain **not performed**.

### Owner enrollment and explicitly renewed read - 2026-11-15

The owner created the encrypted issuer locally. Its public key was enrolled as
`op1-owner-v1`; the raw public-key SHA256 is
`99ead818b2eeb2f0fd1ed81cc0b1dab374d24dcb8a44f1a7a7d85a796c8666dc`.
No issuer private key or passphrase was read by the commissioning agent or
copied to a host. The host remained STOP / UNISSUED.

After the previous read deadline elapsed, the owner expressly authorized a new
GET-only qualification with at most 100 requests in two hours. Its initial
sample at `2026-11-15T05:29:29.184735Z` used 14 requests / 305,378 bytes,
zero uncertainty. Usable collateral remained 10.213845 pUSD; selected-token
balance, visible open orders and credential-visible pending trades remained
zero. The selected standard-market ask remained 0.08, bid 0.07, minimum five,
with explicit zero-fee and existing exit-allowance evidence. Full wallet
inventory remains unassessed and no trade is inferred.

The new absolute deadline is `2026-11-15T07:28:59.663412Z`; the prior closed
32-attempt / 846,858-byte campaign is preserved separately. Root-only evidence:
`/var/lib/polysia-op1/api-read-20261115-r2-initial/receipt.json`.
The 14 consumed attempts must be deducted from any continuation, not reset.

The one-session owner receipt tools are `scripts/op1_owner_commission.py`,
`scripts/op1_packet_host.py` and `scripts/op1_bounded_read.py`. They address the
concrete 30-second fresh-opening handoff gap without weakening freshness or
using a fixture issuer. The protected local profile is
`C:\Users\Siamak\Documents\PolySia\artifacts\op1-type3-20261108\owner-commission-profile.json`.
Once the reviewed helpers are installed, the owner's actual command is:

```powershell
& 'C:\Users\Siamak\Documents\PolySia\.venv\Scripts\python.exe' 'C:\Users\Siamak\Documents\PolySia\scripts\op1_owner_commission.py' --profile 'C:\Users\Siamak\Documents\PolySia\artifacts\op1-type3-20261108\owner-commission-profile.json'
```

The owner enters the local issuer passphrase, reviews the exact proposal and
types `SIGN` within its displayed deadline. The proposal has a 20-minute entry
window and 30-minute protective deadline, fixed five-share / 0.08 price and
unchanged monetary/mutation limits. It remains a proposal until that real
signature exists. Successful invocation returns `PROVISIONED_STOPPED` under
`/var/lib/polysia-op1/owner-packet-r2-20261115`; it places no order. The remaining
independent supervision, real financial recovery and incident acceptance must
then be completed before the owner's separate financial entry. Neither these
tools nor their offline fixture tests constitute a completed real-money test.

### Human review timeout correction - 2026-11-15

The first owner invocation reached review at 06:17:27 UTC, but its 25-second
window expired before signature upload. Inspection found no uploaded signature,
signed authority, custody database or financial journal. Repeated invocations
stopped at exclusive directory creation without additional provider reads.
This was an operator-tool design defect, not missing wallet access or a venue
401. Existing directories and the local review copy remain intact. The renewed
grant has consumed 27 attempts / 324,118 bytes with zero uncertainty; its
original absolute deadline is unchanged.

The corrected protocol gives five minutes for exact owner review, then performs
an official-API qualification after the signature. All financial opening facts
must match the signed baseline and the actual commissioning opening must still
meet the 30-second freshness gate. Fourteen requests and their full byte reserve
are subtracted before signing. The new isolated attempt continues from the
retained 27-attempt receipt; no ledger or failed packet is reopened or replaced.
The amendment requires a verified new runtime artifact, because the core
commissioning contract changed. No financial action was performed.

The corrected core merged in PR #292 as
`5732aad254117f47e3506d13bcf26d1428623f61`; its exact-main CI `43687409499`
passed. Verified native artifact `14150138491` was installed on Helsinki and
the fenced recovery namespace. Image identity is
`sha256:2fb0a7fc7804136cb04b19ac38c598570c2e292ed57e9468ce774b2940fc378b`;
package digest is `149df8300b807b0466b7e4cc99fc4e4c9b0efdef388478cdb08cf5f921c87e57`.
Installation receipts remain under each host's `releases/5732aad254117f47e3506d13bcf26d1428623f61/`.
The disabled refreshed template is
`/var/lib/polysia-op1/owner-packet-reviewed-refresh-inputs/read-config.json`.
Both original fences and STOP remain; no financial worker was started.

The read window elapsed while required CI completed. The owner then explicitly
renewed the bounded GET-only qualification. The protected renewal file is
`/etc/polysia-op1/owner-read-renewal.json`; it must name the retained prior
campaign and carried 27-attempt receipt. Its 100-request ceiling includes those
carried attempts, so at most 73 additional requests are admitted, with a new
explicit two-hour window. No stopped allowance is reopened or overwritten.
The new owner attempt is `api-read-20261115-r2-owner2`, and its future packet
is `owner-packet-r2-reviewed-refresh-20261115`. Historical failed paths are
preserved. The new local profile is `owner-commission-profile.v2.json`; only
the owner's genuine local signature can advance this prepared path to STOP
provisioning. Real-run recovery and supervision remain dependent on that receipt.

### Genuine owner receipt and STOP commissioning observations

The owner successfully signed and provisioned
`owner-packet-r2-reviewed-refresh-20261115`. The post-signature API read matched
the reviewed baseline and satisfied freshness. Custody consumed the genuine
receipt; the financial journal remains STOP with zero mutation attempts,
orders and fills. The signature/failed packet history was not replaced.
Entry authority expires at `2026-11-15T10:06:15.299385Z`; protection expires at
`2026-11-15T10:16:15.299385Z`. No implicit renewal is permitted.

- Actual financial backup and isolated primary restore passed for checkpoint
  sequence 1 under the supervisor OS identity. Receipts are in
  `/var/lib/polysia-op1/recovery/owner-packet-r2-reviewed-refresh-20261115/`.
- A single worker-role commissioning publication and independent supervisor
  inspection passed at `2026-11-15T09:51:09.021255Z`, without STOP release.
  This was a one-shot control check, not a running financial worker or ongoing
  supervision. No surrogate heartbeat process was left alive. Continuous
  supervision and fresh backup maintenance are still required for entry.
- The actual financial backup was age-encrypted, transferred and decrypted
  on fenced Nuremberg. Installed `verify_recovery` passed artifact checksums,
  logical restored content and the same sequence-1 checkpoint. Receipt:
  `/var/lib/polysia-op1-recovery/owner-packet-r2-reviewed-refresh-20261115/offsite-restore-receipt.json`,
  observed `2026-11-15T09:55:23.973704Z`. Custody was excluded, authority was
  not reissued and no restored witness was installed as active authority.
  The recovery private key stayed on Nuremberg. This is a genuine financial
  snapshot/restore check, not the earlier nonfinancial transport fixture.
- The renewed read campaign totals 53 charged requests / 361,724 bytes,
  including the carried 27 attempts. It has zero uncertainty and stopped
  child ledgers. The earlier closed 32-request campaign remains separate.
  The financial image remains verified release `5732aad`; operator tooling
  additionally includes the protected read-renewal fix from PR #293.

Final observation: both original host fences retained, no active financial
tasks, no trading-order signatures/submissions/cancellations by the agent.
This milestone is receipt/STOP commissioning evidence, not a completed
real-money test. The existing consumed receipt and its timestamps must never
be deleted or reset to make a later entry appear authorized.

### Finite owner startup and continuous-control commissioning - 2026-11-15

Engineering merged in PR #295, runtime commit
`ad7365871ed5da0d77024d59efe30a41ad04f215`. Exact-tree PR CI `43707298348`
passed Linux quality, Windows, browser, native image and installation acceptance.
Windows recorded 2,187 passed / 37 skipped. The main and reviewed Git trees are
identical. Exact-main artifact `14160425111` from CI `43709494518` was downloaded
directly to both hosts and its ZIP digest verified:
`f937068bfd0d1b788f24931685ed1f76c4ea279179903bd8e26762c935c74122`.
The installed image is
`sha256:894b2a3772100a465df1593c86f607e427077df983b94012b91376ed15dabe99`;
package digest is `e9161d12c56e6554702f418e5b0028bc824830c1ef1f99699b91f1662ae28870`.
Both installations remain under STOP; retained rollback tag is
`docker.io/library/polysia:op1-rollback-5732aad`. Original Docker image inventories
and fences were preserved. Exact-main CI status remains independently queryable;
the passed reviewed-tree Windows evidence is not an invented main-CI result.

Actual commissioning exposed a timing defect: quarter-CPU backup helper startup
made one serial cycle take about 70 seconds, incompatible with the unchanged
60-second backup freshness gate. PR #296 merged the measured correction as
`c0f474d61da155ee759a16d3ec9693e11fa66509`; its required incremental CI
`43710145503` passed. The native runtime is unchanged. Existing Windows/image
evidence was reused under the supported change classifier. Twenty-five focused
controls tests passed. Both existing hosts have two CPUs and low observed load;
backup helpers now have a one-CPU / 256 MiB ceiling. A real snapshot/encryption
probe took 3.893 seconds. Financial worker limits remain quarter-CPU / 512 MiB;
no hardware, subscription, freshness exception or financial authority was added.

Four actual financial generations were encrypted, transferred through the
pinned-host-key forced-command receiver, decrypted and verified in isolated
Nuremberg restores. The final three observations were
`2026-11-15T11:46:51.522621Z`, `11:47:10.552724Z` and `11:47:29.966793Z`;
their intervals were 19.030103 and 19.414069 seconds. Every generation retained
the genuine old receipt's sequence-1 checkpoint. The same durable transport
ledger retained all four confirmed transfers and 394,080 reserved bytes,
including the initial slow cycle. No uncertain transfer was resent. The finite
backup-only process ended; no surrogate heartbeat or financial worker ran.
These observations qualify the backup mechanism, not a future Live grant.

Actual installed-container permission probes passed: UID 999 can write only
the worker slice; custody and commands are read-only. UID 995 can write custody
and commands but cannot write the financial journal. Neither role sees the
backup transport identity. The external issuer stays on the owner's laptop;
the existing recovery private key remains root-only on Nuremberg. Its original
owner SSH keys were preserved; the added key permits only the bounded receiver.
Both recovery fences and the inactive recovery financial service were verified.
Genuine expired receipt signature verification passed; ENTRY and CANCEL were
correctly denied without custody mutation or fabricated authority.

At 11:50 UTC, financial and custody file digests exactly matched the before
observation. The original receipt remained STOP, with zero mutation attempts,
orders and fills; no new receipt or read renewal was issued. No new Polymarket
request was made during this technical completion. Closed consumption remains
32 requests / 846,858 bytes in the first campaign, and 53 requests / 361,724 bytes
including carried attempts in the later campaign. Current account facts require
the fresh scoped API read in the owner workflow; this is not full-account or
lifetime reconciliation and is not a completed real-money test.

Protected host receipts:

- Helsinki: `/var/lib/polysia-op1/releases/ad7365871ed5da0d77024d59efe30a41ad04f215/continuous-control-commissioning.json`.
- Nuremberg: `/var/lib/polysia-op1-recovery/releases/ad7365871ed5da0d77024d59efe30a41ad04f215/continuous-restore-commissioning.json`.
- Financial generations and unchanged transport ledger:
  `/var/lib/polysia-op1/recovery/owner-packet-r2-reviewed-refresh-20261115/continuous-commissioning-ad736587/`.

The exact installed helper hashes and package/account/instrument bindings are
in the local `owner-commission-profile.continuous.json`. Both local wrappers
were parsed without execution. The owner-operated action is:

```powershell
& 'C:\Users\Siamak\Documents\PolySia\artifacts\op1-type3-20261108\Start-OP1OwnerTest.ps1'
```

This is a real financial start interface, not the old receipt-only script.
It requires honest `RECEIVED` attestation for the existing redacted alert,
explicit `READ100` for the finite GET-only renewal including all carried
consumption, local issuer passphrase, exact proposal review, then
`SIGN AND START`. It retires only the expired unused receipt with custody
history retained. After genuine signing and matching fresh API qualification,
the owner invocation warms up three new actual offsite generations and starts
finite independent supervision and the genuine financial worker. Only that
worker's fresh publication and exact independent ACK can release commissioning
STOP. Fault/operator STOP cannot be cleared by healthy observations. The N3
fence and all original financial caps remain unchanged.

Inspect the result without resubmitting:

```powershell
& 'C:\Users\Siamak\Documents\PolySia\artifacts\op1-type3-20261108\Inspect-OP1OwnerTest.ps1'
```

The inspection reports the actual run's orders, fills, equity, reconciliation,
uncertainty, resource counters and control/service state. Absent provisioning is
reported as absent, not an empty successful trade. Prior start markers, unknown
responses or residual inventory require inspection, never blind repetition.
The owner must still provide the genuine fresh signature and any uncompleted
human receipt. Continuous positive Live admission and actual trade outcomes
remain owner-operated observations; preparation and balance reads do not prove
that a trade occurred.
