# Test Strategy

PolySia uses risk-based layers:

- `tests/unit`: deterministic component behavior;
- `tests/property`: invariants across generated financial inputs;
- `tests/architecture`: dependency direction and SDK confinement;
- `tests/contract`: pinned external SDK surface;
- `tests/integration`: multi-component vertical slices and persistence;
- `tests/migration`: distribution, namespace, CLI, and legacy removal;
- future `tests/e2e`: packaged operator workflows with no live mutation.

Ordinary tests and CI force DATA_ONLY mode, disable the live flag, and clear the
live token allowlist. They must not receive test or production credentials.
Network tests are opt-in and read-only unless a separately marked controlled
validation has explicit owner authorization for that specific run.

Every meaningful engineering change runs its applicable compile, Ruff, Mypy,
pytest, and `pip check` gates. Packaging changes also run build and
installed-wheel smoke tests. Supply-chain
gates include a tracked-file secret scan, dependency audit, and CycloneDX SBOM.

Priority test subjects are order states, Decimal arithmetic, risk limits,
idempotency, duplicates/out-of-order events, restart/recovery, reconciliation,
redaction, SDK contracts, and negative proofs for live gates.

## Feedback and Windows scope

`scripts/classify_ci_changes.py` owns applicability for the complete diff;
`ci_policy_contract.py` verifies projection and required-job failure/skip behavior.
Unknown paths, policy/build changes and mixed risky inputs retain conservative
coverage. Scheduled weekly and explicit full runs retain all gates.

A diff limited to CSS/brand source, its generated Console assets and editorial
documentation runs package custody/regeneration, installed-wheel smoke, Python
and browser checks. It does not alone require Windows, container installation,
ACME or restore regression. Output-only changes and frontend logic, contract,
toolchain or recipe changes cannot use this exception. Regeneration must match
all committed outputs, including JS and the manifest, before CI can pass.

Windows identity, locking, SQLite/replacement, process transport/supervision and
their regression cases select native validation. `scripts/windows_validation.py`
runs a bounded transport/native-lifecycle/session set only for its explicitly
mapped inputs. Storage, identity, dependencies, packaging, unknown native impact
and full/periodic requests still run full pytest. Extend a narrower mapping only
with evidence that it covers the affected callers and real native behavior.
The operational-session module runs once, rather than a preflight and then a
second time inside full pytest. Failures retain JUnit evidence where available;
missing JUnit after an early infrastructure failure does not hide that failure.

Canonical resolver determinism runs in Linux quality for dependency/full inputs;
Windows retains locked installation, environment integrity, package and CLI
smoke. Ordinary unit tests must not resolve online or write tracked locks.
Linux-only administration tests remain in their owning suite and skip on
Windows; removing those short skips is not a material optimization.

Use focused tests locally and reuse valid results for unchanged inputs. Compare
actual job/step timings under the same toolchain and scope before claiming a
speed improvement. Scheduled coverage and Linux success do not establish that
a changed native path works on Windows.
