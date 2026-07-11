# Research Evidence Register

| ID | Question | Official source | Reviewed | Finding | Impact / next trigger |
|---|---|---|---|---|---|
| EVD-001 | What is the unified Python SDK status? | https://docs.polymarket.com/dev-tooling | 2026-07-11 | Unified Python SDK remains beta. | Keep behind adapter; re-review at stable release. |
| EVD-002 | What is the official SDK repository? | https://github.com/Polymarket/py-sdk | 2026-07-11 | Package is `polymarket-client`, import namespace `polymarket`; repository uses lock-based development. | Add contract tests and lock. |
| EVD-003 | Is baseline SDK current? | https://github.com/Polymarket/py-sdk/tags | 2026-07-11 | Baseline b11; official b12 tag dated 2026-07-02. | Do not upgrade during rename; test b12 separately. |
| EVD-004 | Has CLOB infrastructure materially changed? | https://docs.polymarket.com/v2-migration | 2026-07-11 | CLOB V2 is live and legacy V1 SDKs are unsupported. | Verify unified SDK adapter semantics before controlled live validation. |
| EVD-005 | Does pinned unified SDK b11 still support public discovery? | Runtime check: `polysia discover-markets --limit 1` | 2026-07-11 | Passed with one active market and normalized outcomes. | Public compatibility evidence only; does not validate authenticated order semantics. |

Limitations: official pages are time-sensitive. Re-review on any SDK tag,
production error, signing/funder conflict, or controlled-validation phase.
