# PolyCop Candidate-Wallet Ingestion Handoff

## Document control

| Field | Value |
|---|---|
| Task | Stage 1 automated candidate-wallet ingestion |
| Date | 2026-08-22 |
| Starting commit | `4589215ae75a06b3ad4f2615d5ff953e32fb4b19` |
| Working branch | `codex/polycop-candidate-ingestion` |
| External mutation | None; approved public GET reads only |
| Deployment | Not performed |

## Outcome

The repository now contains a complete read-only path from the explicit
PolyCop adapter to a separate protected SQLite history. Successful datasets are
promoted atomically; failed, unstable, incomplete, or schema-changed attempts
cannot replace the last-known-good snapshot. Daily server execution is provided
as an operator-installed systemd timer around a hardened one-shot Compose
service.

The implementation is ingestion only. It does not score, filter, select,
backtest, signal, paper trade, submit, cancel, transfer, or enable Live behavior.

## Implemented decisions

- `CandidateWalletSourcePort` is venue/source-neutral; PolyCop is one explicit
  adapter, not a generalized runtime registry.
- Pagination follows current `total_pages` with caps, unique-wallet/rank checks,
  a final page-1 guard, and one complete-read retry.
- The reviewed 24-field PolyCop row schema is strict. Added, missing, malformed,
  or retyped fields quarantine a redacted, compressed, checksummed sample.
- Source JSON floating-point tokens are decoded directly to `Decimal`; persisted
  source numeric metrics are canonical decimal strings.
- `run_id` identifies attempts and `snapshot_id` identifies versions. A
  successful source/date is idempotent unless `--force-new` is explicit.
- One SQLite transaction publishes the manifest, all rows, identities, and
  current pointer. Failure preserves the prior pointer.
- Raw public wallet addresses are confined to the protected identity table.
  Reports and ordinary snapshot rows use deterministic internal wallet keys.
- Normalized history defaults to 365 days, quarantine evidence to 30 days, and
  local backups to 14 copies. Current snapshots are never pruned.
- Health warns after 36 hours, becomes critical after 72 hours, and surfaces a
  failed/quarantined latest run even while last-known-good data remains fresh.
- Backups use online SQLite copy, integrity checks, and SHA-256 sidecars. The
  restore-check command performs a real disposable restore and validates schema,
  foreign keys, snapshot count, and row count.

## Main paths

- Domain: `src/polysia/domain/wallet_intelligence/`
- Port: `src/polysia/application/ports/candidate_wallets.py`
- Coordinator: `src/polysia/application/services/candidate_wallet_sync.py`
- PolyCop adapter: `src/polysia/adapters/polycop/candidate_wallet_source.py`
- SQLite owner/schema: `src/polysia/storage/wallet_intelligence.py` and
  `src/polysia/storage/wallet_intelligence_schema.sql`
- Backup/restore: `src/polysia/deployment/wallet_intelligence_backup.py`
- Sanitized health report: `src/polysia/monitoring/wallet_intelligence_health.py`
- CLI: `src/polysia/cli_commands/wallet_intelligence.py`
- Deployment: `compose.yaml` and `deploy/systemd/polysia-wallet-intelligence.*`
- Operations: `docs/10-operations/wallet-intelligence-ingestion.md`

## Runtime state

Protected host paths:

```text
/var/lib/polysia/wallet-intelligence/data/wallet-intelligence.sqlite3
/var/lib/polysia/wallet-intelligence/backups/
/var/lib/polysia/wallet-intelligence/reports/latest.json
```

Compose maps these dedicated locations to the stable in-container paths used by
the CLI. These paths are private, ignored runtime state and are not part of Git.
The main `polysia.sqlite3` trading database is neither mounted nor changed.

## Remaining limitations

- PolyCop remains an undocumented and unversioned external API with offset
  pagination and no point-in-time cursor. The page-1 guard detects likely drift
  but cannot prove a vendor-side transactionally consistent view.
- PolyCop exposes only its reviewed score-50-or-higher leaderboard through this
  contract; this is not the complete Polymarket wallet universe.
- File permissions and report redaction are implemented; encryption at rest and
  encrypted off-host backup are not.
- Systemd provides a nonzero failure signal, but no external alert provider is
  configured by this change.
- Timer installation and deployment were not performed. They require current
  source permission and normal deployment review.
- Stage 2 source comparison, wallet verification against official Polymarket
  data, selection, and every trading stage remain separate work.

## Validation

The final working tree passed:

- `python scripts/validate_standards.py --mode full` — zero findings;
- `python -m compileall -q src tests`;
- `python -m ruff check .`;
- `python -m mypy src` — 154 source files;
- `python -m pytest -q` — 729 passed;
- `python -m pip check`;
- `python -m polysia.security.secret_scan`;
- `python -m build` — source distribution and wheel built;
- Compose rendering for the wallet-intelligence profile using the tracked
  example environment;
- wheel inspection proving `wallet_intelligence_schema.sql` is packaged;
- changed-document local-link validation and `git diff --check`.

An owner-approved live read-only smoke fetched 22 dynamic pages and 2,108
unique rows, published one healthy temporary snapshot, created a checksummed
backup, restored it into disposable state, and reconciled all 2,108 restored
rows. The temporary database, backup, and report were automatically removed.
No wallet address was printed.

The optional whole-environment strict OSV audit reported vulnerabilities in an
unrelated orphan installation (`Required-by` was empty). That package is absent
from PolySia dependency declarations and lock files, and this task did not
change dependencies. The finding was not hidden or repaired inside this feature
scope. CycloneDX environment SBOM generation completed in ignored `artifacts/`
state.
