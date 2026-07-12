# POLYSIA-LIVE-002 Final Handoff

## Outcome

`POLYSIA-LIVE-002` ended in a fail-closed `SAFETY_STOP`. One live FOK entry
submission was attempted and rejected by the venue. No fill, exit order,
task-created position, ledger event, or actual task fee was recorded.

## Approved scope

- One controlled BTC Up/Down 15-minute live entry attempt.
- Maximum all-in bounded loss: `10.00`, including the expected entry fee.
- One GTC exit at the tick-normalized actual fill price times `1.10`, only after
  a confirmed entry fill.
- No entry retry or replacement order.

## Safety adjustment

- Pull Request #14 increased the hard-capped venue timestamp lead tolerance
  from 3 seconds to 5 seconds after a preflight measured a 3.95-second lead.
- Strategy version advanced from `0.3.0` to `0.4.0`.
- The maximum stale-book age remains 5 seconds. The notional cap, geoblock,
  allowlist, kill switch, acknowledgement, synchronized-main, green-CI,
  one-attempt, Risk, reconciliation, and exit controls were not weakened.
- Runtime merge commit: `ec5cfc5033b8cd52260163600cd5cb479a9a5481`.

## Validation

- Local: compile, Ruff, Mypy over 113 source files, 420 Pytest tests, `pip
  check`, secret scan, and source/wheel build passed.
- Pull Request #14: quality checks passed on Python 3.11 and 3.13, and both
  strict supply-chain checks passed.

## Live evidence

- Tradeable dry-run preflight:
  `2383af60-4116-4a18-acb1-b1e91dcafabd`.
- Authorized live run: `a9bae88d-14d2-4771-a7f0-7548179582fb`.
- Strategy, portfolio admission, and independent Risk all approved the bounded
  entry before submission.
- Proposed entry price: `0.78`; size: `12.626071`; notional: `9.84833538`;
  expected entry fee: `0.15166`.
- The venue rejected the FOK entry submission after the persistent one-attempt
  claim was recorded. The sanitized adapter evidence did not expose a more
  specific venue rejection reason.
- Live entry attempt count: one. Confirmed fill: none. Exit attempt: none.
- Reconciliation completed with `states_match`: zero observed open orders, no
  task-created position, no manual intervention, and no safety pause.
- Ignored local evidence:
  `release-artifacts/tiny-live-round-trip/a9bae88d-14d2-4771-a7f0-7548179582fb/`.
- JSON SHA-256:
  `D3EED47CECF53642E4E34DDD31506F61568EEEB012746420F33362522B3BEFF5`.

## Closure and recovery

This authorization is consumed and must not be retried automatically. Any new
live submission requires a new explicit owner authorization and a new bounded
authorization identifier. Reverting Pull Request #14 restores the 3-second
clock-lead cap but must never remove or reuse the persistent attempt evidence.
