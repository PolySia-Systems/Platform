# Independent Platform execution

Date: 2026-10-16. Status: IN_PROGRESS. This is the single execution record;
the delivery PR owns ordinary resume after creation. Runtime rows below are
dated observations, not live status.

## Authority and publication boundary

The owner explicitly authorized execution of the final 16 October execution
prompt and selected `platform.polysia.movafegh.com`. Platform remains public.
Work is limited to Platform DATA_ONLY engineering and commissioning, scoped
project deployment/Access/Tunnel, bounded acquisition under a new manifest,
encrypted backups and isolated recovery. Real account mutation, Live, host
reboots and unrelated services are excluded. WI campaigns remain stopped.

Publication inventory: existing Platform source/tests/configuration; selected
first-party Standards requirement identities and consumer evidence at v0.5.2;
new Platform implementation. No whole private repository, operational dataset,
credential or private observation is approved for publication. WI implementation
will be reused only where needed after consumer and third-party notice review.
Original WI and Standards repositories remain unchanged.

## Verified starting identities

- Platform: clean `main`, `ca9f37df91a5b9659726fa18312b381ccb081d83`.
- WI reference: clean `5f9f3604b2b27d1da4116b2133717a1ed2578d42`.
- Latest released Standards: immutable v0.5.2,
  `2ccbe4dbbcb3574db52e5a8eb73e968a9165a83c`, release 414090521.
- Open #142 is an older frozen canary task, not authority to rerun it unchanged.
- Both designated hosts permit administrative SSH; unrelated services and WI
  assets exist and must be preserved. No Platform service was found.
- Supplied hostname resolves through the proxy; public HTTPS verification failed
  during TLS negotiation. Secure Console access is not yet established.

## Work map

| Milestone | Acceptance | State / dependency |
|---|---|---|
| A: foundations | Selected released Standards, fail-closed CI, immutable promotion | IN_PROGRESS |
| B: retained value | Deterministic snapshot reports, honest uncertainty, no provider I/O | OPEN; existing accounting reused |
| C: discovery | Two source routes, causal eligibility, durable budgets and funnel reasons | OPEN; numeric policy before network |
| D: operation | Secure Console, bounded jobs, supervision, cleanup and required checks | OPEN |
| E: commissioning | Exact artifact, protected access, isolated restore, durable observation | OPEN; A-D and verified permissions |

## Acceptance ledger

Engineering, reporting, operational usefulness, reliability, Human View,
independent secure deployment/recovery, and repository cleanup are OPEN.
Economic evidence is UNKNOWN. Owner comprehension is OPEN and cannot be inferred
from automated checks. No acquisition has been started by this execution.

## Incremental evidence

Draft delivery PR: [#190](https://github.com/PolySia-Systems/Platform/pull/190).
Foundation commit: `5646048`. Focused classifier tests: 16 passed. Standards
full validation, focused Ruff, secret scan and diff checks passed. Hosted quality,
container and supply-chain jobs passed for that commit; Windows was still running
at the last query. These are not final-release results.

The next increment adds a shared snapshot reporting service/CLI, new Platform
durable acquisition reservations, a finite two-route diagnostic and retained
hosted image/promotion manifests. Focused tests: 44 passed, 46 deselected.
The accounting fixture contains persisted simulated activity and verifies identical
analytical digests with network access disabled. These fixtures are not economic
observations. Native activity eligibility remains distinct from execution eligibility.

Access setup: the existing protected provider credential can read zone DNS,
Access applications and tunnels. The supplied record matches the selected origin.
Account user/membership, Access organization and certificate-pack requests return
403. No existing Access application/allowlist or Tunnel was found. The owner
identity and Access organization therefore remain unverified; public commissioning
is BLOCKED until a supported protected route is established. No broader permission,
subscription purchase or guessed identity is assumed. Offline engineering continues.

The next hosted run at `647c2c1` passed container and supply-chain checks but failed
the CLI surface contract because the new command names were not yet included in
its exact command inventory. That contract is updated in the Console increment;
the focused CLI/Console/native/authority suite then passed 17 tests. Full local
typing passed for 260 source files before that increment. Revalidate the final
identity through hosted CI.

Console dependencies: PyJWT[crypto] and Waitress, with rationale/notices/rollback
in `docs/05-security/console-dependencies.md`; canonical locks were regenerated
without upgrading unrelated pins. Console denial, RS256 issuer/audience/expiry,
role, CSRF, revision and idempotency cases pass focused tests. Worker receipt
application and actual protected deployment remain OPEN.

Dependency automation: the scoped repository request to permit workflow-created
PRs was rejected with HTTP 409: organization policy forbids Actions creating or
approving PRs. The existing read-only default and protections were preserved.
Use the authenticated operator's existing `scripts/dependency_locks.py` manual
generation/review path; no organization-wide permission change or new token is
authorized by this fallback.

Native runtime increment: `continuous-shadow-native-research-v1` keeps the old
v1/v2 meanings and gates unchanged. The native policy/cohort/code are bound in
persisted config. An offline nonempty integration test persists wallet and mixed
follower simulations under `NATIVE_RESEARCH`, with no Alpha/Stress membership.
Continuous admission requires matching nonempty diagnostic/resource evidence;
isolated diagnostics use a distinct admission mode and root.

Worker ticks and report publication are separate commands. Acquisition stays
disabled unless explicitly enabled in protected configuration. Durable STOP is
processed before missing cohort data or retry delay; expiry and finite transient
retry accounting block the affected operation. Per-window limits and closure
reserves remain inside lifetime totals. Focused authority/STOP tests: 7 passed;
native/report integration tests: 2 passed. Full typing: 263 files passed.
