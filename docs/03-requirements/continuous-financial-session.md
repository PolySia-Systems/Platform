# Bounded financial session and operator evidence

Status: CURRENT engineering library; TARGET continuous operational composition.
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

The new library defaults to DATA_ONLY. Historical Tiny Live CLI registrations,
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

Operational activation is TARGET. No account/provider acquisition, deployed
performance, sustained supervision coverage, real order or economic result is
claimed. The active PR owns exact commands/results and remaining engineering
findings. See [operating and deployment prerequisites](../10-operations/continuous-financial-session.md).
