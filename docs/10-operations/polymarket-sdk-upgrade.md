# Polymarket SDK Upgrade and Rollback

## Current engineering baseline

- Distribution/import: `polymarket-client==0.13.0` / `polymarket`.
- Runtime: CPython `3.14.8`, supported `>=3.14,<3.15`; host Python is unchanged.
- Frozen validation stack: Pydantic `2.14.1`, core `2.50.1`,
  pydantic-settings `2.15.0`, WebSockets `15.0.1`.
- Migration and exact-source delivery evidence:
  [PR #200](https://github.com/PolySia-Systems/Platform/pull/200).
  Passing code compatibility does not authorize Live or qualify a real account.

The reviewed [official tag](https://github.com/Polymarket/py-sdk/releases/tag/polymarket-client-v0.13.0)
is `f1e2ab2c86d04573c304ca7afe8f1e36fcbd6237`. The PyPI wheel SHA-256 is
`923e691a4bcb1f816852420db0db4abca3d1dda3d08c5384669ae0fac94f5c13`.
The former 0.7.1 deferral is superseded by this scoped migration, not by a
pin-only approval. PR #169 is superseded after verified integration.

## Consumed semantics and boundaries

The adapter uses canonical SDK `asset_id`/`asset_ids` requests and maps books to
stable domain `token_id` values. Gamma outcomes still use the SDK's actual
`token_id` field. Stream models/specs use canonical asset fields while emitted
Platform events retain their token identifiers. Historical wire fixtures remain
useful because the consumed CLOB wire keys and mixed cancellation results are
still supported; they do not require the old SDK package.

Secure position reads use `condition_id`, include archived rows and explicitly
request a zero token filter. They consume the entire cursor walk. A positive
Platform `size_threshold` is applied with Decimal to current shares locally;
it is never assumed equivalent to a cash-value filter. A missing threshold means
unfiltered current inventory. `AccountPosition.size` maps `current_size`, never
historical `total_size`; redeemable zero-value holdings are retained. Closed
zero-size rows cannot invent holdings. Missing, nonfinite or negative current
inventory fails closed. Marks and end dates remain unknown when absent.

The SDK's `list_closed_positions` method has no Platform caller and is removed
from the required-surface assertion. No compatibility wrapper or second data
collector is introduced. Existing bounded Data API v2 research ingestion stays
in place. Account positions/orders/trades reject repeated or absent cursors,
SDK depth limits and walks beyond 1000 pages; no partial account becomes complete.
Trade and maker contributions must match the requested asset before finality
mapping. Actual model/HTTP fixtures cover Decimal values, serialization,
404 versus malformed detail, mixed cancellation and linked maker/taker fills.

SDK `create`, `_create` and wallet-readiness implementations are unchanged
between the verified 0.7.1 and 0.13.0 wheels. Signer/funder selection and existing
risk/allowlist/geoblock/acknowledgement controls remain intact. Client creation
can deploy an undeployed default Deposit Wallet in the SDK; it is not an
inherently read-only operation. Offline tests intercept bootstrap before any
key parsing/signing/network setup. Installed DATA_ONLY services have no provider
credentials and never create a secure client.

Upstream trading-approval state now comes from `/v2/approvals` without RPC
fallback and may lag grants/revocations. Platform does not consume that new
indexed method or treat it as conclusive chain authorization. Consumed CLOB
balance/allowance reads remain distinct and are covered by actual SDK transport
tests. Perps, analytics extras, wallet setup and other unused SDK surfaces are
not integrated.

## Dependency decision

Pydantic 2.14.1/core2.50.1 have cp314 Linux/Windows wheels. Financial/config,
SDK model, serialization and settings regressions determine acceptance; exact
versions are locked together. pydantic-settings2.15.0 remains compatible without
a justified update. WebSockets15.0.1 is retained because SDK0.13 requires
`>=13,<16`; 17.2 is outside that contract. This is a resolved compatible hold.
Only SDK, Pydantic and core changed in the generated runtime/development locks.
No Python upgrade or repeat 3.15 assessment is part of this migration.

The image reports its actual Python and five reviewed package versions in
`runtime-packages.json`. Release-manifest generation compares them with the
runtime lock and refuses mismatches before publication. Wheel/image provenance,
full CI and release receipts identify the tested source; package metadata alone
is not behavior evidence.

## Upgrade procedure

1. Review official tagged source/metadata for every consumed path and record
   the compact impact map in the PR. Characterize changed behavior before pinning.
2. Exercise actual SDK models/methods with deterministic wire transports, plus
   existing gated execution/reconciliation, stream and financial/config tests.
3. Synchronize SDK pin, reviewed Tiny Live version constants, generated locks,
   version/configuration metadata and current guidance as one change.
4. Run the required PR and exact-main CI, including full Linux/Windows,
   supply-chain, container, browser and installation/recovery gates. Verify the
   actual installed wheel/image versions and review trust/accounting boundaries.
5. Publish retained immutable artifacts and use the shipped administrative
   lifecycle. Keep acquisition/admission absent and durable STOP. Actual venue
   reads, signing or mutations need separate authorization; they are not required
   to prove offline compatibility or complete a DATA_ONLY release.

## Rollback and stop conditions

Retain the old immutable v0.3.0 artifact as historical software rollback evidence;
its stack used SDK0.7.1 and Pydantic2.13.5/core2.46.5. Revert an SDK migration only
as a coherent pin/constants/locks/adapter/contracts/documentation set, recreate
the environment and rerun relevant gates. Never mix new adapter code with the
old installed package or downgrade financial data/spent authority.

A fresh installation has no invented previous working configuration checkpoint.
Use protected STOP, retain its data and exact artifact, and repair the failed
boundary. Open inventory, pending observations or incompatible identity/schema
still refuse ordinary upgrades. The owner's clean-server decision supersedes
the historical two-observation deployment blocker; it does not weaken that gate.

Stop the affected action for a genuine missing contract, wrong asset or wallet,
ambiguous external state, failed redaction, dependency conflict or weakened Live
gate. Preserve evidence and fix the responsible boundary; never substitute empty
results, drop filters silently or use trial-and-error keyword fallbacks.
