# Developer Context Packet

- **Status:** CURRENT
- **Mode:** local developer tooling
- **No authority:** no Live, Risk, Execution, wallet, order, or host-control path

Produce a bounded, deterministic context packet so a model without chat
history can resume one scoped repository task from repository truth.

## Developer entry

Use CPython 3.14.8 and the locked environment from the root
[README](../../README.md#requirements-and-installation). Initial pip/Conda
bootstrap needs package-network access. No `.env`, provider credentials,
owner account, manifest or running server is needed afterward:

```bash
polysia system health
polysia research paper-trade --token-id fixture-token --order-size 1
python -m pytest -q tests/integration/test_native_drain_transport.py tests/unit/monitoring/test_console.py
```

These are offline fixtures, with no economic or capacity acceptance claim.
An installed server also offers `/demo`, separately labeled and read-only;
its JSON cannot become a canonical financial report. Ordinary Console reads
use retained data and never acquire provider data.

| Feature | Module | Contract | Focused evidence |
|---|---|---|---|
| Close-only native drain | `cli_support/native_lifecycle.py`, `application/services/continuous_shadow.py` | Original identity/capital; charged complete source and current market evidence; no new entry | `tests/integration/test_native_drain_transport.py` |
| Durable worker/STOP | `cli_commands/platform_worker.py` | No authority initialization on lost state; independent STOP and explicit receipts | `tests/unit/cli/test_platform_worker_boundaries.py` |
| Console reporting/auth | `monitoring/console.py`, `deployment/gateway.py` | Canonical report, exact identity/Origin/CSRF, exclusive verifier | `tests/unit/monitoring/test_console.py`, `tests/unit/deployment/test_gateway.py` |
| Guided maintenance | `deploy/platform_admin.py`, `platform_bootstrap.py` | Verified release, disabled activation, retained rollback | `tests/unit/deployment/test_platform_admin.py`, `scripts/installation_acceptance.py` |
| Backup and recovery | `deploy/platform_backup.py`, `deployment/platform_recovery.py` | Real encrypted generation, replay identity and STOP; separately held key | `tests/integration/test_continuous_shadow_portfolio.py`, `scripts/backup_destination_acceptance.py` |

Module paths above are relative to `src/polysia/` unless prefixed by `deploy/`.
Read the relevant path's instructions. For a small status-explanation change,
edit the centralized `STATUS_TEXT` in `monitoring/console_assets/console.js`,
update the corresponding browser expectation, then run that browser test and
`node --check` on the asset. Do not change worker authority states to fit wording.
For a report contract change, first add a canonical accounting fixture, then
change the reporting service and only then its Console renderer. Use the PR as
the resume artifact. Context packets below are optional assistance.

## Required behavior

The Issue or PR remains the ordinary task owner. [`docs/README.md`](../README.md)
remains the canonical documentation entrance. Generated packets are disposable
views and are never project truth.

A packet MUST report:

- repository identity, exact HEAD, and dirty-state fingerprint;
- an opaque Issue/PR identifier when a task reference is supplied;
- applicable `AGENTS.md` files discovered from the repository root toward the
  scoped path;
- relevant requirements and approved ADRs with path, digest, and why they apply;
- implementation boundaries and existing capabilities to reuse;
- validation scope derived from `scripts/classify_ci_changes.py`;
- reusable validation evidence and checks still missing;
- unresolved decisions and the next concrete action.

Task input is untrusted data. The packet and rendered text MUST contain only a
sanitized opaque identifier such as `PR #123`, or an omission marker. Raw task
text MUST NOT appear in JSON, excerpts, `next_action`, or human-readable output.
The tool MUST NOT read secret files, execute Issue/PR/log text, or silently
omit safety instructions when excerpts are truncated. Cache reuse is valid only
when HEAD, sanitized task reference, instruction digest, scope, and environment
fingerprints match. Dirty worktrees bypass the cache because a path-only status
fingerprint cannot prove that scoped file contents are unchanged.

Dependency-classified changes include both configured supply-chain gates:
`python -m pip_audit --strict --vulnerability-service osv` and
`cyclonedx-py environment --output-format JSON --output-file artifacts/sbom.json`.

## Command

```text
python -m polysia.cli system developer-context \
  --task <issue-or-pr-reference> \
  --scope <path> \
  --json-file artifacts/developer-context.json
```

Human-readable text is the default stdout. JSON is versioned as
`developer-context-packet-v1`.
