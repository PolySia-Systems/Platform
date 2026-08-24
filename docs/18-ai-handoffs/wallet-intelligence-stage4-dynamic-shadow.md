# Wallet Intelligence Stage 4 Dynamic Shadow Handoff

## Delivery boundary

Stage 4 adds a new read-only research pipeline after Stage 3. It dynamically
loads the current Alpha and Stress memberships, removes overlap, resolves their
protected canonical addresses, reads official Polymarket trades for verified
event markets, and stores versioned historical-model and Forward Shadow
evidence per wallet.

This work does not deploy services, enable timers, create a signal or order
intent, send/cancel an order, or authorize Live trading. The retained Tiny-Live
experiment and fixed 102-wallet artifact are not deleted; the new path simply
does not depend on them.

## Main behavior

- Legacy `PolymarketCopyTradingSource` callers remain `BTC_15M` by default.
- Stage 4 alone opts into `ALL_VERIFIED` market evidence.
- The existing rate scheduler provides shared `/trades` pacing, bounded
  concurrency, retry behavior, 429 cooldown, and circuit telemetry.
- Historical results explicitly use a versioned cost/liquidity model because
  historical order-book evidence is not available in this path.
- Forward results walk current official book depth and record fee, slippage,
  total delay, liquidity, bounded size, and realized closed-position PnL.
- A shared persistent lease prevents concurrent Stage 1–4 runs.
- SQLite publication is atomic, idempotent for the full processing identity,
  address-free, retained for 365 days by default, and preserves last known good.
- Health and restore validation understand Stage 4.

## Main paths

- Specification: `docs/03-requirements/wallet-intelligence-stage4-dynamic-shadow.md`
- Domain: `src/polysia/domain/copytrading/dynamic_shadow.py`
- Ports/service: `src/polysia/application/ports/dynamic_shadow.py` and
  `src/polysia/application/services/dynamic_shadow.py`
- Official source: `src/polysia/adapters/polymarket/copytrading_source.py`
- Persistence: `src/polysia/storage/dynamic_shadow.py` and
  `src/polysia/storage/dynamic_shadow_schema.sql`
- CLI/operations: `src/polysia/cli_commands/wallet_intelligence.py`,
  `compose.yaml`, and `deploy/systemd/polysia-wallet-intelligence-shadow.*`

## Validation and read-only smoke

Final repository validation covered Standards, compileall, Ruff, Mypy (166
source files), the complete 780-test suite through pre-commit, pip check, secret
scan, build, Compose rendering, CycloneDX generation, and the strict OSV audit
of `locks/pip-py314.lock`. The locked audit found no known vulnerability. The
whole-workstation audit separately found an orphan `cryptography==48.0.0` that
is absent from project declarations and locks; it was not changed.

An owner-authorized, disposable, read-only smoke on 2026-08-24 observed:

- PolyCop: 21 pages and 2022 wallets;
- Stage 3: Alpha 50, Stress 100, overlap 1, Live review 0;
- Stage 4 unique candidate union: 149 wallets;
- one-hour Historical model: 139 events, 112 simulated, 27 unknown;
- 15-minute Forward current-book run: 51 events, 45 simulated, 6 unknown;
- 149 `/trades` reads in each mode, zero 429 responses, and a closed circuit;
- address-free Top-5 result output;
- successful real backup/restore with two Stage 4 runs and 190 evaluations.

The Historical PnL is model output, not a profitability claim. No authenticated
API, credential, order, cancellation, or external account mutation was used.
The disposable database, backup, report, and protected addresses were deleted
after the restore rehearsal.

## Next operator action

After merge, deploy Stages 1–4 in `DATA_ONLY`. Run one bounded Historical
backfill, start the Forward timer, inspect rate telemetry/health and restored
backup evidence, and collect enough observations before changing any selection
policy. Live still requires a separate review and explicit authorization.
