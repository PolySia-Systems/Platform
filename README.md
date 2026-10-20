# PolySia

PolySia is a risk-controlled, extensible trading and prediction-market
platform. Polymarket is the first venue adapter and practical MVP, not the
identity of the core platform.

The current implementation is a Python modular monolith with venue-neutral
domain and application boundaries, deterministic financial arithmetic,
independent risk authority, explicit execution state, persistent reconciliation,
and conservative operating defaults.

> **Safety boundary:** Live trading is disabled by default, no new Live run is
> authorized, and the current Control Kernel is limited to deterministic
> SHADOW operation for `stale-price@0.1.0`.

## Current capabilities

- Public Polymarket market discovery and normalized realtime market data.
- An in-memory event bus, Decimal order book, market features, and strategy
  framework.
- Strategy Registry records with versioned definitions, lifecycle state, run
  evidence, and explicitly unrated performance summaries.
- Independent pre-trade Risk decisions, a conservative paper broker, position
  and P&L accounting, SQLite persistence, and fail-closed reconciliation. Stage
  4B also rejects accounting-invalid publication before commit or progression.
- Guarded authenticated reads and bounded Live tooling that remains dry-run by
  default. Live-capable submission requires fresh verified state and sends only
  the immutable economic request approved by Risk.
- Deterministic replay backtesting, paper/shadow reporting, deployment checks,
  sanitized operator reports, and a single-host read-only deployment profile.
- A SHADOW-only Control Kernel slice with immutable desired-state revisions,
  optimistic concurrency, idempotency, observed state, and append-only audit
  history.

A bounded private [PolySia Console and independent Shadow profile](docs/10-operations/independent-platform-shadow.md) provide retained reports, native/PolyCop discovery, durable STOP and encrypted recovery tooling.
Software implementation, secure deployment and real-observation usefulness have
separate acceptance receipts; no continuous admission or public access is implied.

These capabilities do not establish strategy profitability, generalized
multi-strategy orchestration, production readiness, or authorization for
broader Live use. Generalized allocation, OMS/Transaction Manager, execution
routing, adapter registry, and additional venues remain
TARGET or FUTURE work.

## Safety contract

- Runtime defaults to `TRADING_MODE=DATA_ONLY` and
  `LIVE_TRADING_ENABLED=false`.
- Strategies emit signals or pre-risk intents; they never call a venue, wallet,
  chain, broker, or protocol directly.
- Executable intents follow Strategy -> Risk -> Execution -> Adapter. Risk has
  final authority to approve, reject, reduce, pause, or block.
- Financial prices, quantities, fees, exposure, and P&L use `Decimal` or an
  approved fixed-point representation.
- Live-capable paths retain allowlists, hard caps, geoblock checks, kill switch,
  explicit acknowledgements, one-attempt controls, redaction, and
  reconciliation.
- External mutation is never part of ordinary tests. Network validation is
  explicit and opt-in.
- Secrets, wallet/account identifiers, runtime databases, and generated Live
  evidence must remain outside Git.
- Material uncertainty stops mutation and requires reconciliation; safety gates
  must not be weakened to make a check pass.

See the [operator runbook](docs/OPERATOR_RUNBOOK.md) and
[server deployment runbook](docs/10-operations/server-deployment.md) before any
operational work.

## Architecture

The CURRENT deployment is one Python modular monolith:

```text
CLI / deployment composition
        |
Strategy signals and pre-risk intents
        |
Independent Risk authority
        |
Execution state and reconciliation
        |
Canonical venue ports
        |
Polymarket adapter and official SDK boundary
```

Domain and application modules remain venue-neutral. Polymarket identifiers,
SDK models, signer/funder semantics, and venue errors are translated at the
adapter boundary. CURRENT, TARGET, FUTURE, and EXTERNAL claims are maintained in
the [architecture documentation](docs/04-architecture/README.md).

## Requirements and installation

- CPython `3.14.8` (`>=3.14,<3.15` supported)
- Git
- A local virtual environment or the existing `PolySia` Conda environment

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r locks/requirements-dev-py314.txt
python -m pip install --no-deps -e .
```

Dependency maintenance, scan/preflight commands, publication permissions and
review boundaries are documented in [supply-chain controls](docs/05-security/supply-chain.md).

On Linux activate with `source .venv/bin/activate`. Initial dependency bootstrap
downloads packages; the fixture commands below then run without provider access
or secrets. The explicit Windows Conda bootstrap remains available through
`environment.yml` and `locks/conda-win-64.lock`; install the pip lock afterward.
See the [developer entry and change map](docs/03-requirements/developer-context-packet.md#developer-entry).

For a destination server, use the [guided administrative installation](docs/10-operations/independent-platform-shadow.md#release-and-isolated-roots)
instead of a development environment. The immutable `v0.4.0` release and
fresh disabled installation are recorded in [PR #200](https://github.com/PolySia-Systems/Platform/pull/200).
The owner's server reset supersedes the historical activation blocker; exact
release and installation evidence belongs in the
[dated operational record](docs/18-ai-handoffs/platform-independent-shadow-2026-10-16.md).


Copy `.env.example` to an ignored `.env` only when local overrides are needed.
Never commit or display the resulting values.

## Quick start

Inspect the complete command surface:

```powershell
polysia --help
polysia control --help
```

Run local health and paper-only examples:

```powershell
polysia system health
polysia research paper-trade --token-id YOUR_TOKEN_ID --order-size 1
python -m pytest -q tests/integration/test_native_drain_transport.py tests/unit/monitoring/test_console.py
```

`research paper-trade` uses a
deterministic local simulation and does not call Live trading APIs. Its output
is marked not economically ready because the demo has no recorded fee or
terminal evidence. `research backtest --input EVENTS.jsonl --evidence EVIDENCE.json`
accepts [versioned, recorded Paper economics evidence](docs/10-operations/paper-backtest-economics.md).
Commands
that read an authenticated account or can mutate external state have
additional explicit gates; their presence does not grant authorization to use
them. See the [CLI capability migration](docs/10-operations/cli-capability-migration.md)
for canonical paths and the bounded flat-alias removal policy.

## Validation

Run the fast, cross-platform pre-push check for immediate local feedback:

```powershell
python scripts/fast_check.py
```

This fail-fast command checks diffs, Standards, secrets, compilation, Ruff,
Mypy, and environment integrity. It does not replace complete Pytest or CI.

The repository quality gates are:

```powershell
python scripts/validate_standards.py --mode full
python -m compileall -q src tests
python -m ruff check .
python -m mypy src
python -m pytest -q
python -m pip check
python scripts/dependency_locks.py check
python -m polysia.security.secret_scan
python -m build
```

Dependency and supply-chain changes additionally use:

```powershell
python -m pip_audit --strict --vulnerability-service osv
cyclonedx-py environment --output-format JSON --output-file artifacts/sbom.json
```

Network, Docker, authenticated, and external-state checks are not ordinary
development gates. Run them only when the scoped task explicitly requires and
authorizes them.

## Repository map

```text
src/polysia/        Python package and modular-monolith runtime
tests/              Architecture, contract, integration, property, and unit tests
docs/               Governance, architecture, requirements, operations, and evidence
standards/          Immutable Standards adoption and conformance records
scripts/            Dependency-free repository and documentation validation
deploy/             Controlled single-host deployment assets
locks/              Reproducible dependency inputs
```

## Authoritative documentation

- [Documentation entrance](docs/README.md) â€” canonical 30-second map.
- [Project status](docs/00-governance/PROJECT_STATUS.md) â€” durable
  capabilities, limits, and dated runtime snapshots. Not live host truth.
- [Master Operating Charter](docs/00-governance/master-operating-charter.md) â€”
  approved governance and long-term architecture direction.
- [Architecture](docs/04-architecture/README.md) â€” CURRENT/TARGET/FUTURE views
  and traceability.
- [Operations](docs/10-operations/server-deployment.md) â€” controlled deployment
  and recovery procedures.
- [Current evidence index](docs/18-ai-handoffs/README.md) â€” major operational
  evidence. Ordinary work resumes from the Issue or PR.
- [Roadmap](docs/22-roadmap/roadmap.md) â€” prioritized product and maintenance
  work.
- [Standards adoption](standards/adoption.toml) and
  [conformance](standards/conformance.toml) â€” selected immutable
  `PolySia-Systems/Standards@v0.5.2` profiles.

Historical documents remain evidence of earlier decisions and runs. They are
not automatically current instructions. Code, tests, schemas, configuration,
approved decisions, and verified operational evidence define present truth.
