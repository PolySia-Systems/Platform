# ADR-0023: Bounded continuous financial session

- Date: 2026-10-25
- Status: Proposed; engineering implementation is authorized, continuous Live
  composition and operational approval are pending an explicit owner decision.
- Scope: Python modular monolith; one account and one active host.
- Related: [ADR-0016](ADR-0016-verified-live-state-approved-order.md),
  [ADR-0021](ADR-0021-independent-platform-shadow.md),
  [requirements](../../03-requirements/continuous-financial-session.md).

## Context and verified boundary

CURRENT: the research worker remains DATA_ONLY. Tiny Live retains its historical
102-candidate and three-cycle/attempt contracts. Existing exact ApprovedOrder,
verified-state, independent Risk, broker, cancellation-finality gate and Decimal
position accounting are reused. A market-order claim hook now has the same
placement as the existing limit-order hook: after final reapproval, immediately
before adapter submission. No existing experiment cap or CLI has been widened.

CURRENT engineering library: a source-neutral session coordinator, authority
carrier, private SQLite journal and redacted publication projection work with
deterministic accounts, including the existing LiveBroker bridge. This does not
establish an operationally commissioned continuous Live service. No production
composition root, authority issuer, account access or activation is created.

## Proposed operational decision

Use one bounded coordinator in the existing process, not a generalized OMS,
allocator, distributed scheduler or second trading service. A trusted operator
composition verifies an owner receipt and binds a versioned envelope to exact
release, configuration, policy, account and active host. Every field is required;
a false grant, missing evidence or mismatch denies execution. No example values
are operational permission. The Console cannot create authority or access the
private financial journal.

Discovery and selection produce prospective candidates only. Native and PolyCop
observations share the existing canonical identity and retain separate metrics,
times, completeness and confidence. A source trade must additionally identify
its canonical occurrence, wallet, instrument, side and finality. A transaction
hash or public market-price update alone cannot identify a leader action.
Missing occurrence proof is denied, even if discovery membership is known.

Serialize one account writer across awaits with the existing local exclusive
writer lock, rooted in the account's protected witness directory. Fence every
open. Atomically persist event, frozen decision, exact approved request,
attempt, worst-case reservation and uncertain-submit boundary before adapter
I/O. Reconciliation, confirmation and fee-aware fills own financial closure.
Neither a timeout, ACK nor cancellation acknowledgement refunds exposure.

The new session freezes a quantity-bound limit request before independent Risk,
including strategy/token/side/price/shares/expiration/post-only. LiveBroker
asserts that exact approved tuple after final revalidation. This avoids treating
spend divided by maximum price as an upper share bound: favorable execution can
otherwise receive excess shares. Existing market ApprovedOrder semantics and
historical experiment consumers remain unchanged. A confirmed SELL that cannot
replay against known holdings is durably quarantined, drains entries and makes
economics unknown; it never silently invents a short position or loses evidence.

Financial state and a separately retained rollback witness use SQLite rollback
journals and an attached-database transaction. This relies on the local
filesystem's SQLite atomic-commit guarantees. Both stores use full synchronous
writes. Restoring an older financial file against the witness fails closed.
Restart additionally requires an independently retained exact recovery
checkpoint, fresh independent supervision and complete account reconciliation.
No worker may derive its own recovery approval from restored files. Restoring
the journal, witness and independent recovery control together is outside this
local threat boundary and must never be an automated recovery operation.

Budgets are lifetime counters for the run. They survive midnight, restart and
ordinary financial-backup restore. Worst-case held capital consumes loss
authority as well as exposure authority; missing marks cannot free capital.
Request/response/cost bounds are reserved before reads and mutations, with
capacity reserved for cancellation and reconciliation. Port bounds must cover
all underlying requests, including connection/eligibility work and paging.

RUNNING, DRAIN, STOP and the existing independent kill switch are distinct.
Expired entry authority grants no exit, cancellation, redemption, approval or
transfer permission. Only explicitly listed protective actions before their
own deadline may proceed, with current venue eligibility, Risk, supervision and
account evidence. STOP/kill deny mutations; read-only reconciliation preserves
evidence. Mandatory supervision uses persisted UTC and process-local monotonic
timeouts; optional latency/report failure cannot change financial state.

## Alternatives and compatibility

- Raising historical Tiny Live constants would silently widen an old contract;
  rejected.
- Turning the DATA_ONLY research worker into a signer would break its approved
  isolation; rejected.
- Distributed locks, automatic second-host failover and a new database service
  lack measured need and increase the authority boundary; deferred.
- An independent general ledger/OMS migration is not necessary for this slice.
  Reuse PositionLedger with durable confirmed fills, alongside account truth.

The new session has its own versioned store; historical financial stores are
neither migrated nor rewritten. Bootstrap refuses nonempty accounts pending an
assessed migration. A different envelope cannot reuse an old store or witness.
Rollback stops the new composition and selects retained compatible code. Keep
STOP, consumed authority, financial state and witness; never downgrade a live
store or restore older allowance.

## Decision still required

Owner acceptance of this operational contract, trusted receipt-verification and
checkpoint custody, exact account reader/occurrence completeness, commissioned
supervisor and host eligibility, measured numeric budgets, and a separately
approved run envelope remain prerequisites to continuous Live operation.
Engineering tests and a draft PR do not approve those actions.
