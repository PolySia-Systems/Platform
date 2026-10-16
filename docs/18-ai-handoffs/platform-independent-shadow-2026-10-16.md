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

## First real native diagnostic

Hosted Linux quality/container/supply-chain passed for source `696567e`, tested
merge artifact `b90e9627a5942bc761e608ff81edb6ff4f7469e3` (parents baseline
`ca9f37d` and source `696567e`). Helsinki retrieved its archive directly from GitHub;
no laptop artifact was an input. Archive digest:
`8fcff30417d834605db5aeeb30894587bc843d05873ecbd561ca63d0b9aea83a`.

Artifact portability defect: the source Docker store addressed the image by
config digest `0e418ac0…`, while the destination containerd store addressed the
same archive by OCI manifest digest `1c3a08f8…`. The archive binds both identities.
The initial load check failed before any acquisition; no allowance was consumed.
The bootstrap now resolves only identities bound by the verified archive.

Manifest `platform-native-feasibility-20261016-001` was then frozen with one wallet,
40 requests/32 MiB total (5 requests/4 MiB reserved), 1 MiB response cap, 15-minute
expiry, 30-second cadence, 512 MiB RAM/50% CPU and an 8 GiB free-disk floor.
Effective policy digest:
`351634e938968a7bdc1f25b030616bdf989ced5cc14ef0510fc9817eab28887e`.
At 06:27:39 UTC it failed closed after 4 requests / 1,569,982 bytes, without
publishing a cohort or starting simulations. Economics remains UNKNOWN.

Root cause confirmed in the [official Data API v2 contract](https://data-api.polymarket.com/v2/docs):
the bare trade feed ignores time bounds and covers the current/previous month.
Only wallet-anchored trades and activity honor those bounds. The native route
is corrected to explicitly sample one feed page for seed identities, without a
feed completeness/watermark claim, then completely walk each selected wallet's
activity with unchanged filters. This reduces the work rather than widening the
diagnostic. Raw provider responses and query/trace/digest metadata are now retained
privately before successful charge settlement. Exact cursor failure reasons are
preserved. No unchanged diagnostic is authorized by this finding.

The changed-workload follow-up used tested merge artifact
`4265f4b708730da03b4ca6a2960f25f8870d79b9` (source `24e573e`), archive
`9cb75d36377da8212a93b21ec743b5d2c3560afa6cae4b11267a5b27ee3789f2`.
It reused the original manifest and all prior counters. The seed sample contained
500 rows; one wallet had 4 complete activity rows and passed current mapping,
fee and book checks. Shadow failed closed at the source boundary because the
manifest omitted Gamma `/events`, used by the existing trade normalizer.
At 06:42:03 UTC the combined charge was 10 requests / 1,978,349 bytes, zero uncertain
requests. No economic conclusion or continuous admission is supported.

An explicit continuation command now records predecessor/new policy digests and
the owner-execution reference, keeps every request/byte charge and STOP unchanged,
and rejects higher numeric ceilings, lower closure reserves or a longer run
duration. It permits a new bounded diagnostic window and the specifically required
public metadata endpoint under the owner's existing delegation. Ordinary
initialization still rejects replacing an active policy. This is an explicit
audited action, not automatic allowance renewal or reopening a WI campaign.


## Preserved continuation and source freshness

Continuation 002 used tested merge `7f471bb4b1117fa36ef9346441f48169ed0abd28`
(source `62ae9ad`, CI 38863512604), archive SHA-256
`f552b2715af03d40d121ffda136de6ca029875aaa3016a329669472c6fd7390e`.
It added Gamma `/events` with identical numeric ceilings and carried all charges.
Effective policy digest `22ac683ec9da57615c214b581588f734ae484b5a8d0fbf83315a26a0f314edcb`.
At 07:04:47 UTC all 500 sampled seeds were outside the 60-second profile.
The newest source timestamp was 07:01:06 UTC, age 221.686 seconds at receipt.
No financial root was started. The combined 11 requests / 2,371,503 bytes
and zero uncertain requests remain charged. Durable STOP was explicitly set
and verified without network access. Do not repeat this unchanged diagnostic or
widen freshness bounds merely to obtain nonempty observations.

Browser read-only verification established the existing Zero Trust team and an
active super-admin owner identity; only that verified identity may be mapped.
The edge certificate covers `*.movafegh.com` and the apex, not the requested
`platform.polysia.movafegh.com`. Covering deeper names requires a paid feature,
which is outside authority. The unused single-level `console.movafegh.com` is the
prompt-authorized fallback candidate; the original record remains unchanged.
Access, origin and fallback publication still require verified deployment receipts.
A credential-parser exception exposed an existing credential in the tool error
stream. It is excluded from repository/report content; sanitized management
boundaries replace raw parser errors. Rotation of that existing shared credential
must preserve its other consumers and remains an operator security dependency.

Offline interval-report/recovery tests reconstruct a nonempty financial state,
replay the same analytical digest and retain consumed authority/STOP. Encryption
is separately verified using real age in the container gate. Synthetic desktop
and mobile browser acceptance passes locally, including keyboard CSV download,
JWT-protected evidence, wallet exclusions, reader controls and durable STOP.
These fixtures do not establish actual source usefulness or owner comprehension.


Planned scoped Cloudflare assets, recorded before mutation: one self-hosted
`PolySia Console` application for unused `console.movafegh.com`, one explicit
verified-owner email allow policy (no Everyone, bypass, service-token or domain
wildcard), one dedicated Helsinki tunnel to loopback port 8765, and that single
new DNS record. Reuse the existing verified team issuer. Retain returned IDs and
configuration privately. Rollback removes only the new record/application/tunnel
by their recorded IDs and stops the dedicated connector; it preserves all existing
records, Access configuration and services. Create protection before any route.


## Backup allocation manifest

Before allocation, Helsinki has 22,067,630,080 free bytes and Nuremberg
28,702,048,256 free bytes. New Platform-only allocation on Nuremberg:
`/var/lib/polysia-platform-backups/vault.img`, exactly 4,294,967,296 bytes,
mounted at `/srv/polysia-platform-backups`. Neither path existed. Preserve at
least 8 GiB on the host. Maximum ciphertext generation 512 MiB; retain two
completed generations plus plaintext staging/restore reserve inside the new
filesystem. Upload identity `polysia-platform-upload` has only chrooted SFTP;
protected recovery key remains under root's separate configuration directory.
Daily backup and isolated cold-recovery checks target RPO <=24h and RTO <=60m;
only actual drill receipts establish those bounds. No existing WI allocation,
backup, key or unrelated container is changed. Rollback disables the new units
and upload identity; retain the new ciphertext, key and allocation for recovery.

The scoped Access-app creation request returned HTTP 403. The existing API
credential cannot apply the required protection. UI-based security access creation
requires action-time confirmation under the browser tool policy; the owner asks
for no questions. That affected action stays BLOCKED; no unprotected route is
created. Existing hostname and DNS remain unchanged.


## Installed-artifact findings and final review

CI 38871621799 tested merge `d8448c7dd1811692446bcc90c1727191f425344d`
(source `790c4b7`): Linux quality, container, browser, supply-chain and Windows
compatibility passed. Its archive `23abb2d5a7ed4853fe4ba2c0b4927750603d2b33964cb76a34b502e28e9605a6`
was retrieved directly on both servers, verified and loaded. The common destination
image is `sha256:137822ace3ba8f0e3a9512edfc95c2e6fa15934df827a28e205086454c859694`.
This is candidate evidence; the final main release requires its own exact checks.

The primary bootstrap created dedicated identities/units with acquisition false
and web stopped. A new runtime root retained SQLite Backup API snapshots of the
Platform diagnostic, including one experiment, two polls and zero opportunities.
All 11 requests / 2,371,503 bytes and durable STOP were preserved; original roots
remain intact. This is explicitly retained isolated-diagnostic data, not continuous
admission or an imported WI experiment. Candidate worker startup reported STOPPED.
The publisher exposed two defects before commissioning could pass: SQLite WAL
bookkeeping cannot always operate through a physically read-only directory; older
provider metadata lacks latency fields. Source connections remain `mode=ro` plus
`query_only`, with directory write access only for SQLite bookkeeping. No immutable
mode is used on active files. Missing latency is UNKNOWN with an explicit sample
count, not fabricated or treated as a software crash. The final image must recheck
these paths. No provider acquisition was restarted during these tests.

Nuremberg's allocated filesystem reports 4,143,677,440 usable bytes. Chrooted SFTP
login and `/incoming` confinement passed through a host-key-pinned connection.
A protected recovery key was generated there with the tested age binary, mode
0600; only its public recipient reached Helsinki. Neither private key entered a
report, repository, upload account or archive. Actual encrypted-generation and
restore receipts remain necessary before recovery acceptance.

The deliberate second review resolved cross-identity command-file permissions,
UTC CLI parsing, WAL snapshot access, legacy metadata compatibility, source/error
classification, replay code binding, export capacity accounting, failure receipts,
log bounds and narrow backup mounts. Financial values still use the single existing
Decimal engine. Native research has no signer, Alpha membership or Live path;
existing v1/v2 gates are preserved. Reports include code digests, UTC bounds/cutoff,
policy/cohort/config identities and separate cumulative/interval scope. Core money,
risk, ledger and reconciliation semantics were not replaced.

The tracked-repository consumer review covered 727 paths and 266 Python modules,
CLI/entry points, dynamic import sites, installed assets, schedules, dependency
locks, migrations, historical readers and documentation links. Three modules have
only test/entry/manual static consumers: the CLI is the declared entry point;
latency benchmark helpers remain an offline research API with unique tests; the
Copy signal outcome accessor preserves a historical schema/public research contract.
The old WI producer wrapper remains only for supported historical import/parity
consumers and is absent from all new service/backup dependencies. No demonstrated
safe deletion justified breaking these consumers; apparent duplication is retained
for those explicit reasons. This is a reachability review, not proof that every
line is necessary. Six changed Mermaid diagrams were rendered and visually checked;
other views retain their semantics with refreshed delta-review metadata.

Local evidence: full suite 1,410 passed / 4 explicit opt-in skips; subsequent
focused fixes passed their affected tests, typing (266 modules), Ruff, compilation,
Standards, secret and diff checks. Installed-wheel desktop/mobile/keyboard tests
are maintained in hosted CI and include finite cached-read p95 measurements on a
specified synthetic dataset; they do not establish production or owner comprehension.
Final exact-release gates, host scheduling/recovery and public access remain separate
acceptance rows; no blanket ENGINEERING_COMPLETE/PRODUCT_ACCEPTED claim is made here.
