# Research Evidence Register

| ID | Question | Official source | Reviewed | Finding | Impact / next trigger |
|---|---|---|---|---|---|
| EVD-001 | What is the unified Python SDK status? | https://docs.polymarket.com/dev-tooling | 2026-07-11 | Unified Python SDK remains beta. | Keep behind adapter; re-review at stable release. |
| EVD-002 | What is the official SDK repository? | https://github.com/Polymarket/py-sdk | 2026-07-11 | Package is `polymarket-client`, import namespace `polymarket`; repository uses lock-based development. | Add contract tests and lock. |
| EVD-003 | Is baseline SDK current? | https://github.com/Polymarket/py-sdk/tags | 2026-07-11 | Baseline b11; official b12 tag dated 2026-07-02. | Do not upgrade during rename; test b12 separately. |
| EVD-004 | Has CLOB infrastructure materially changed? | https://docs.polymarket.com/v2-migration | 2026-07-11 | CLOB V2 is live and legacy V1 SDKs are unsupported. | Verify unified SDK adapter semantics before controlled live validation. |
| EVD-005 | Does pinned unified SDK b11 still support public discovery? | Historical runtime check: `polysia discover-markets --limit 1`; current replacement: `polysia market discover --limit 1` | 2026-07-11 | Passed with one active market and normalized outcomes. | Public compatibility evidence only; does not validate authenticated order semantics. The historical flat command remains a hidden compatibility alias. |
| EVD-006 | Is SDK 0.6.0 a compatible stable successor to 0.2.0? | https://github.com/Polymarket/py-sdk/releases/tag/polymarket-client-v0.6.0 and the official 0.2.0...0.6.0 comparison | 2026-08-21 | Stable releases 0.3.0 through 0.6.0 add activity defaults, isolated-margin and perps surfaces, metadata caching, combo RFQ, and sparse-last-trade handling. PolySia's consumed methods, models, bounded-order parameters, signer/funder creation inputs, and dependency set remain compatible. | Historical evidence; superseded as the current pin by EVD-007. |
| EVD-007 | Is SDK 0.7.1 a compatible stable successor to 0.6.0? | https://github.com/Polymarket/py-sdk/releases/tag/polymarket-client-v0.7.0 and https://github.com/Polymarket/py-sdk/releases/tag/polymarket-client-v0.7.1 | 2026-09-03 | 0.7.0 adds scoped session keys, typed trading-restriction errors, trading-approvals state, typed notifications, and Poly-RateLimit surfaces. 0.7.1 patches session-key expiration. Consumed adapter methods, signer/funder inputs, and Tiny Live safety gates remain compatible after updating `APPROVED_SDK_VERSION`. | Keep 0.7.1 pinned behind the adapter; Tiny Live constants must match the pin. |

Limitations: official pages are time-sensitive. Re-review on any SDK tag,
production error, signing/funder conflict, controlled-validation stage, or
future data-provider integration.
