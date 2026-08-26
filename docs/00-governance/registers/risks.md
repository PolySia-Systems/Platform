# Risk Register

| ID | Risk | Likelihood | Impact | Control / owner-visible gate |
|---|---|---:|---:|---|
| RSK-001 | Rename breaks imports, CLI, or operator workflows. | Low | High | Migration tests, canonical naming checks, preserved legacy recovery. |
| RSK-002 | Polymarket SDK drift changes signing or responses. | High | High | Exact `polymarket-client==0.6.0` pin, contract tests, upgrade/rollback runbook. |
| RSK-003 | Venue types leak into core. | Low | High | Architecture tests and adapter-boundary review. |
| RSK-004 | Live action runs during ordinary validation. | Low | Critical | DATA_ONLY CI, explicit authorization, Risk, allowlist, cap, acknowledgement, geoblock, kill switch, and one-attempt gates. |
| RSK-005 | Credential value reaches Git or an artifact. | Low | Critical | Ignore rules, redaction, secret scan, sanitized handoffs/exports. |
| RSK-006 | Historical documents are mistaken for current truth. | Medium | Medium | Authority order, archive labels, current status and handoff. |
| RSK-007 | Windows-only lock is treated as portable. | Medium | Medium | Keep platform label; require portable lock before cross-platform release. |
| RSK-008 | One profitable round trip is mistaken for strategy evidence. | High | Critical | Keep strategy experimental/unrated; require historical, backtest, and large Paper/Shadow evidence before Tiny-Live promotion. |
| RSK-009 | Conflicting canonical and deprecated funder variables create ambiguous authenticated identity. | Present | Critical | `configuration-status` fails closed; owner-reviewed removal of deprecated `POLYMARKET_WALLET_ADDRESS` before future authenticated/live use. |
| RSK-010 | Continuous local monitoring is mistaken for production-grade supervision. | Medium | High | Managed Docker restart/health and Wallet Intelligence timers are CURRENT; external alert delivery and high availability remain absent. |
| RSK-011 | Venue terminal order details are unavailable after a fill. | Medium | High | Match durable identifiers, confirmed fills, and venue position; warn and fail closed on unexplained mismatch. |
