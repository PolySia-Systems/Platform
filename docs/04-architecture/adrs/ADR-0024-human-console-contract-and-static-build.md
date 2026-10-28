# ADR-0024: Human Console contract and static build

- Date: 2026-10-27
- Status: Accepted for H1/H2 engineering under explicit scoped owner activations.
- Scope: Console presentation, redacted read models, existing command gateway,
  reproducible static assets. Operational acceptance remains EXTERNAL.
- Depends on: [ADR-0022](ADR-0022-guided-single-installation.md) and
  [ADR-0023](ADR-0023-bounded-financial-session.md). This decision does not
  approve ADR-0023's pending operational decision.

## Decision and CURRENT boundary

Use React 19.3.1, strict TypeScript 7.0.2, Vite 8.3.5 and Mantine 9.7.4 with
CSS modules and a small PolySia token layer. Build with Node 24.22.1 and npm
11.19.1; `frontend/package-lock.json` is the sole JavaScript lock. The existing
protected WSGI application serves static assets. No Node production runtime,
new service, provider read, signer, custody access or private financial-journal
query is added to web handlers. Existing Risk, execution, reconciliation,
supervision and command owners retain authority.

Python Pydantic models in `console_contract.py` own the v1 wire vocabulary.
`scripts/console_contract.py` generates TypeScript types and the schema used by
the browser validator. The validator interprets that bounded schema without
eval; shared producer/gateway fixtures test real mapping and malformed input.
Amounts stay exact strings with explicit units and unknowns. A stable one-way
account fingerprint supports context without publishing the private binding.
Unsupported environment/venue facts stay UNKNOWN.

The response explicitly says `atomic=false`: publication bytes define one
generation, while supervision has its own run scope and validity. No response
timestamp renews producer evidence. List/detail queries use the same redacted
publication, a default 50/max 100 rows and a generation/query-bound cursor.
Expired cursors return 410 and require a visible refresh. Optional record
indexing cannot invalidate financial summary or protective command admission.
Complete protected legacy exports keep their existing size/integrity controls.

H1 operations reuse `ControlService` and `ConsoleCommandStore`; registered
targets and typed choices come from the server. Preview bindings include actor,
current authentication identity, target, arguments, revision, expiry, source
generation where relevant, and installed bundle identity. Protective STOP/drain
catalog and admission do not consult optional analytical evidence. Every POST
rechecks identity, role, Host/Origin, CSRF, preview binding and owner checks.
One intended request keeps one idempotency key in volatile memory through lost
responses. Exact actor/target-authorized lookup precedes any identical resend.
Reload uses authenticated durable history, with no persistent browser payload,
credential or cache. Phase and effect are separate; FAILED/UNKNOWN remains
unresolved and is never automatically retried after login or restart.

Mantine's representative portal, keyboard focus, dense table and RTL are tested
under the Python production CSP. External CSS is preferred; a per-response nonce
is restricted to style elements. There is no unsafe script, eval, blanket inline
allowance, CDN, telemetry or service worker. RSC `use client` directives in the
Mantine distribution are removed by an explicit static-browser transform; this
application has no server-component semantics. This resolves the Vite directive
warning at its browser-only build boundary.

## Static artifact custody

`npm ci --ignore-scripts --prefix frontend` and `npm run build --prefix frontend`
are the only asset recipe. Generated HTML/JS/CSS/notices/manifest are checked in
under `src/polysia/monitoring/human_console_assets`. The manifest hashes all
shipped bytes and binds API, release and source inputs. Its source identity is
embedded in HTML and returned by authenticated session metadata. Missing,
changed, incompatible, unlisted, symlinked or traversing assets fail closed.

The Hatch hook verifies this custody and source freshness for wheel and sdist
builds, without invoking npm. The sdist contains source and verified assets;
sdist-to-wheel and container builds use the same hook. CI regenerates and rejects
any diff. Installed browser tests remove the source import path. The
build recipe escapes trailing template whitespace after minification without
changing cooked string values, then names the final JavaScript by its byte hash;
tagged raw templates require explicit review. Tests prove exact value preservation.
This satisfies the unchanged whitespace gate for upstream CSS template literals.
The financial package-tree digest includes every new shipped asset, including manifest and
notices. A UI replacement changes financial binding; engineering grants no hot deployment
or renewal of an existing financial authority.

## Alternatives, maintenance and rollback

Extending handwritten DOM code remains possible but leaves growing context,
preview and recovery lifetimes difficult to compose. A second HTTP framework,
SSR or generic BFF adds ownership without a demonstrated need. Mantine is retained
because the production slice proves its required interaction/CSP surface; no
second speculative library comparison is needed. React, Mantine, TypeScript and
Vite are maintained upstream, MIT licensed; transitive notices are shipped,
JavaScript audit and CycloneDX SBOM join existing Python supply-chain gates.
Exact dependency rationale and the upstream notice exception are recorded in
[Console dependencies](../../05-security/console-dependencies.md).

Rollback selects a retained complete compatible release after stopping the
affected worker/web process through the protected operator procedure. Retain
STOP, financial stores, custody and consumed allowance. Do not downgrade data,
replace assets during a bound run or manufacture new authority.

## Completed presentation migration and compatibility

H1 established the contract/build/slice at source
`7ea1c292b35093b5f0b281d05a98d037c891e8be` with exact-head CI. H2 retains that
architecture. CURRENT `/` serves the sole Human Console and `/assets/` its
allowlisted static files. The previous handwritten HTML/JS/CSS/demo files and
`/h1`, `/h1/assets/`, `/demo`, `/api/demo`, `/console.js`, `/console.css` routes
are removed. The same presentation offers `/?example=1`, a clearly synthetic
read-only dataset. Its session has reader identity, its action catalog is empty,
and its data never enters canonical reports or financial stores. This is a
dataset choice, not a second presentation or migration switch.

Overview, Investigate, Operate, Evaluate and System / Setup now share compact
scope/mode/identity context and explicit protective target choices. Bounded
wallet/source/filter/detail and order/position views preserve selection reasons,
frozen policy, Risk/trigger/reservation/fill links and cash events only when
retained by the publisher. Missing links remain UNKNOWN. Confirmed resolution
can mark inventory `REDEEMABLE_REVIEW`; it grants no redemption authority.
Closed inventory is distinct from externally observed settled cash. Account
observation/expiry are independent of publication time: refreshing a publication
cannot renew an account read. Blocked reconciliation qualifies cash and economics
as UNKNOWN without altering accounting or discarding confirmed evidence.

`console_workspaces.py` maps allowlisted redacted facts into bounded typed
sections/tables. No arbitrary JSON dump, private path, URL navigation, SQL,
signer, custody or provider access is added to web handlers. Tables show their
own unavailable/empty/partial state and counts; a missing dataset is never a
healthy zero. Wallet details are lazy; a cached reverse index connects only
retained wallet/order IDs. List pages omit detailed traces and remain 50/100.
Workspace responses are limited to 220,000 bytes; the client accepts at most
250,000 characters. Catalogs are schema-bounded to 128 actions, 64 choices per
argument and two arguments per operation; excessive configurations fail visibly
and retain the protected CLI path.

Registered Shadow create/clone/start/drain/resume/finalize/archive/compare and
policy-stage forms reuse `ControlService` and `ShadowLab`. The publisher exposes
registered template digests and assumptions through `ShadowLab.console_view`;
the web never reads its private configuration. Related choices require published
existing slots. Console clone previews also bind the source-policy digest; the
owner rejects an unpublished concurrent policy change before creating a slot.
The optional scoped guard is additive; existing direct consumers retain their
prior contract and can adopt the guard without a presentation compatibility layer.
Only CREATED Shadow slots can
stage templates; running positions remain frozen. Full financial policy editing,
financial resume/close/cancel, redemption and authority issuance remain deferred.
Acquisition STOP/drain/resume/export retain the original acquisition queue and
owner; additive immutable previews bind their exact identity, revision, bounds
and expiry. Both queues share authenticated exact receipt/history lookup, stable
history cursors and cross-queue idempotency-key conflict protection. There is no
automatic replay, optimistic effect or persistent browser financial payload.

The UI serializes an unresolved intended request rather than replacing its key.
For immediate emergency action while a request is unresolved or the control
store is unavailable, use the independent OS-protected CLI/custody path.
Optional analytics and history cannot invalidate an otherwise valid protective
preview. A corrupt optional history result cannot prevent acquisition revision
admission. An unreadable command queue latches independent custody STOP once,
without terminating supervisor financial checks or clearing an existing STOP.
Financial witness uncertainty still fails closed. Local real-collaborator fault
tests complement existing separate-identity/container and checkpoint tests;
they do not certify deployed host isolation.

Protected `/api/report`, `/download/comparison.csv`, `/reports/<digest>.json`,
current acquisition/scoped command APIs and emergency CLI contracts remain.
These are backend owner/consumer interfaces, not retained presentation adapters.
Their removal requires a separate versioned consumer migration; H2 does not
claim zero historical APIs. Browser contracts, installed private-HTTPS/keyboard
journeys and regression assertions are ported to the sole presentation.

H2 lab budgets remain Overview <=2 s, p95 interaction-to-paint <=200 ms over
>=100 samples, initial JS <=400 KiB gzip, default/max pages 50/100, and <=5 MiB
post-GC heap growth / <=100 extra DOM nodes over 1,000 settled refreshes.
The 10,000-wallet/200-order fixture, 25h accelerated clock, 10 CSRF rotations and
100 injected receipt failures are synthetic. Actual wall time and named runner
measurements live in CI/PR artifacts, not a fabricated multi-day soak.

Axe automation, keyboard/focus, 200%-equivalent reflow and representative Persian
text/RTL are bounded engineering evidence. Screen-reader and human acceptance,
real host cgroups/ACLs/shared-egress isolation, independent backup commissioning,
alert delivery, real-data qualification, deployment, Live authorization and
economics remain EXTERNAL/UNKNOWN. No production-readiness claim follows.

## Official sources reviewed

- [React versions](https://react.dev/versions)
- [Vite backend integration](https://vite.dev/guide/backend-integration)
- [Mantine provider](https://mantine.dev/theming/mantine-provider/)
- [Mantine RTL](https://mantine.dev/styles/rtl/)

Documentation establishes supported mechanisms. The installed protected browser
tests establish the scope actually verified here.
