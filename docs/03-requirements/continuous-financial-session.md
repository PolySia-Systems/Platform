# Bounded financial session and operator evidence

Status (2026-10-26): CURRENT default-disabled engineering composition and operator
controls under review in PR #230; TARGET commissioned financial operation.
Live authorization: absent. Architecture decision: [ADR-0023 is Proposed](../04-architecture/adrs/ADR-0023-bounded-financial-session.md).

## Required contracts and implementation

| Capability | Owner / acceptance |
|---|---|
| Authority | `domain/financial_session.py`: required version, owner receipt, release/config/policy/account/host binding, UTC windows, wallets and exact instrument/collateral/route scope, strategy/exit policy, all-in order/open/market/wallet exposure, turnover, attempt/loss/concurrency, fee, request/response/storage/cost and restart/protective bounds. Missing values do not grant permission. |
| Identity and qualification | Existing canonical wallet/source-link tables; `application/services/source_cohort.py` retains native/PolyCop provenance. Comparable follower evidence precedes deterministic ranking. Selection/evaluation windows do not overlap. Provider rank is neither skill nor executable edge. Disappeared/excluded identities remain visible. |
| Decision | `SessionOpportunity`: final attributable occurrence, fresh ordered timestamps, exact scope/side, conservative fair value minus uncertainty/cost, entry/exit depth and venue eligibility. Missing fees, reorg ambiguity, mapping mismatch or nonpositive entry edge reject with a durable reason. |
| Financial writer | `storage/financial_session.py`: account-rooted local exclusive lock held over I/O, increasing fencing, versioned private journal and independently retained witness. No automatic migration, account bootstrap after loss, cross-host failover or authority rollover. |
| Risk and submit | `application/services/financial_session.py`: independent Risk approves the canonical economic request, atomic attempt/reservation, final account refresh and exact Risk reapproval, then durable uncertain-submit claim. `execution/financial_session.py` reuses LiveBroker and its existing safety gates. |
| State and finality | Reserved, uncertain submission, accepted/rejected, partial/full fill evidence, cancel pending, cancellation and confirmed finalization. The existing cancellation gate uses checkpoints inside the same financial journal. An ACK alone releases nothing. Uncertain submissions never automatically resend. |
| Account truth | Complete cash, positions, open orders and cumulative-fee observations bind the exact account. Confirmed unique fills replay through existing PositionLedger; duplicate conflicting evidence denies changes. Unmatched external activity remains an incident and drains entries. |
| Exit advice | Partial follower size and available depth; authorized leader reduction or explicit maximum-holding policy. Expiry waits for settlement evidence. Redeemable holdings and dust remain visible; neither creates redemption/transfer authority or fictitious cash. |
| Recovery | Explicit independently retained recovery checkpoint, unchanged envelope, current account reconciliation and fresh independent supervision. Consumed attempts/turnover remain cumulative across midnight/restart. An older financial backup cannot refund a witness. |
| Evidence | Existing latency-intelligence recorder receives monotonic decision/Risk/account/submit/ACK/fill/finality durations. Source UTC age has an explicit unverified-clock flag; absent/restarted spans stay missing/censored. Financial persistence is mandatory; optional telemetry may degrade. |
| Human View | Existing protected Console: overview/authority/incidents; searchable paginated discovery; actual order/health timeline; economics/source value. 1,000 available discovery rows are not 1,000 subscriptions. UNKNOWN and stale publication remain explicit. |

The new composition defaults to DATA_ONLY. Historical Tiny Live CLI registrations,
caps, source-score policy, replay contracts and research worker behavior remain
unchanged. Test-only fake authority is not operational configuration.

## Financial and economic semantics

Attempts, turnover and uncertain reservations do not reset at UTC midnight or
restart. Entry limits include worst-case held cost and active reservations, not
just the next order. A SELL cannot exceed known unreserved follower holdings.
Final Risk evaluates the same exact economics immediately before adapter I/O.

Session orders use an immutable quantity-bound limit request, including its
expiration and post-only flag. A favorable BUY price can reduce cash spent but
cannot increase the approved shares. Historical market ApprovedOrder contracts
remain available to their original consumers; spend/max-price is not treated
as a maximum share quantity for the new session. Confirmed evidence that cannot
replay safely, including a SELL overfill, is retained in a private quarantine;
entries drain and economics remain UNKNOWN until explicit reconciliation.
Held and remaining pending BUY quantities share the independent Risk token and
market limits and consume position slots atomically. Confirmed partial fills
reduce the pending remainder; pending SELLs do not free future BUY capacity.
This single-cash-ledger slice refuses envelopes spanning different collateral
assets rather than adding incomparable amounts.

Cancellation of a partial order passes the remaining quantity and matched
baseline to the existing finality gate. Incremental fill-price calculation
subtracts a verified matched-notional baseline; missing positive-baseline cost
or an old terminal checkpoint without it returns UNKNOWN, never an invented
price. Existing zero-baseline checkpoints remain compatible. Fee-aware fills
and complete account evidence still own the financial ledger.

Confirmed fill prices already include spread/slippage. The reused ledger charges
recorded fees once. Report realized/unrealized values separately, plus explicit
mark method/time, open/censored holdings, rejected opportunities and
leader/follower price divergence where the leader price is known. Missing marks
make total net economics partial/unknown. No fills means no observed trading
result, not a profitability measurement of zero. Marked drawdown reports its
checkpoint denominator. Provider and infrastructure cost remain separate; a
reserved request cost is not an invoice or an actual source-value measurement.

The funnel distinguishes discovered, qualified, monitored, attributable timely
events, eligible decisions, Risk approval, submission, fills and finalization.
Only actual evidence populates a stage. Source overlap is shared provenance,
not independent confirmations or duplicated account P&L. Source-removal replay
is counterfactual and cannot establish causal provider returns.

## Verification and operational limits

`tests/integration/test_financial_session.py` exercises complete entry/exit,
exact LiveBroker requests with a fake adapter, stale/missing/mismatched evidence,
overlap/distinct occurrences, source outage/queued work, partial/cancel races,
uncertain submit, restart/restore, expiry, STOP/kill, loss/exposure/resource caps,
two writers, account changes and financial-store/telemetry failure isolation.
Property tests exercise occurrence identity across sources and Decimal input
representations. Existing broker/finality/accounting tests remain applicable.

`tests/integration/test_source_cohort.py` exercises shared canonical identity,
retained qualification/exclusion and 100/500/1,000 offline discovery records.
`tests/browser/test_console_browser.py` exercises the four operator tasks and
loading/empty/stale/error cases on desktop/mobile. Automated fixture acceptance
does not establish actual human comprehension within 60 seconds.

Operational activation remains TARGET. The concrete entry point is
`polysia ops session`; non-Live construction returns before any signer, financial
store, account reader or network is constructed. No account/provider acquisition, deployed
performance, sustained supervision coverage, real order or economic result is
claimed. The active PR owns exact commands/results and remaining engineering
findings. See [operating and deployment prerequisites](../10-operations/continuous-financial-session.md).


## E2 connected contracts (CURRENT engineering)

| Acceptance | Implemented owners and constraint |
|---|---|
| A1 | Adapter `position_inventory` and V2 public readers walk bounded cursor envelopes; legacy offsets reject. OPEN and REDEEMABLE_LOST/CLOSED views deduplicate exact condition/token pairs. Public inventory is not an exact account balance. |
| A2 | `deployment/financial_session_runtime`, adapter `session_composition`, `session_account`, `session_network`, `security/session_authority`, and `deployment/session_supervision` connect the existing coordinator, Risk and LiveBroker. Ed25519 owner receipts bind release/code/config/policy/account/host/run/scope. Custody consumes receipts and starts STOP. No issuer exists in worker/web. |
| A3 | V2 rows discover transactions; finalized canonical CTF Exchange V2 receipts prove wallet occurrences by transaction plus actual block log index. Retained Shadow quotes produce causal follower samples, cost/delay/depth metrics and an experimental bounded forward-price estimate. Missing estimates remain unknown. |
| A4 | `financial_allocation` projects account/token/leader/policy ownership from confirmed fills and actual redemption cash in the existing financial owner. Pending quantities reserve ownership. PositionTrigger is separate from leader events. Unexplained transfers, unsupported settlement and contradictory finality drain entries. |
| B1 | Immutable CopyPolicy supports FIXED_DEBIT/CAPITAL_PROPORTIONAL and MIRROR/NET_TAKE_PROFIT/HYBRID. Stop/time parameters require HYBRID; reentry defaults off. Two-decimal share quantum matches the pinned SDK. Exact signed economics and exchange are checked before submission. |
| B2 | `deployment/shadow_lab` uses existing ContinuousShadow stores, lifecycle, leases, event application and one acquisition allowance. At most four slots/templates; separate virtual capital. Same-tape policy comparison is stateful, never a summed return. |
| B3 | `monitoring/capabilities` and `operational_session` distinguish evidence, configuration and authorization, including expiry, scope and next action. Independent supervision publication is separate from worker health. |
| B4 | Existing ControlService/ConsoleCommandStore handle typed scoped previews, revisions, expiry, targets, native/gateway roles, idempotency and terminal receipts. Browser/CLI cannot issue financial authority. Legacy Shadow commands retain their meaning. |
| B5 | One durable request/byte/cost owner confines actual SDK/RPC HTTP traffic. Entry admission reserves requests/bytes/cost/attempts/turnover/storage for protection. Optional source work sheds within the frozen envelope. Local deduplicated incidents and fake notification receipts require separate delivery authority. |

The composed route is deliberately limited to chain 137, standard legacy CTF
Exchange V2, six-decimal pUSD/CTF, EOA signer=funder, signature type 0, and the
pinned SDK's exact contract addresses. Negative risk, V3 token namespaces,
proxy/Safe/deposit wallets, builders and nonempty baseline migration reject.
Actual account completeness depends on a qualified all-or-error historical RPC
provider, complete bounded authenticated orders/trades, canonical finalized
headers, cash and all token balances. Large accounts that exceed any bound
remain blocked; empty public inventory never establishes completeness.

Ownership uses deterministic pooled average cost and proportional remaining
fees, with residual cost assigned to the last sorted owner. Chronological fills
include chain block/log ordering at equal timestamps. Redemption is actual
confirmed token removal plus cash movement, not permission to redeem. A
redemption at or before the last fill timestamp remains quarantined rather
than guessing within-block cash order. Dust stays owned and visible. Policy
trigger precedence is stop, holding time, net take-profit, then evidenced
proportional leader reduction. Depth is rounded down before Risk; a trigger is
an attempted eligible exit, never a guaranteed price. Existing holdings retain
the original policy and exit monitoring after entry exclusion.

The qualification estimator's independent bounded-sample/stationarity assumptions
are experimental and require later calibration. Provider ranks never become
probabilities. Selection samples precede availability/evaluation; the operational
root recomputes evidence from the bound sample artifact. No real acquisition,
qualified Live cohort or economic result was produced by this engineering.

Version-1 financial journals/receipts keep their old identity. Version-2 journals
add bounded raw network evidence and protective reserves; no implicit migration
or reinterpretation is permitted. New optional Shadow policy fields preserve
legacy consumers; scoped commands use additive tables. Changing a Live binding
requires a new separately authorized run/receipt; staging does not alter active
holdings. See the runbook for custody, qualification and rollback.
