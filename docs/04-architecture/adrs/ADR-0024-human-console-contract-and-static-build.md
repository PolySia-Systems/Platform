# ADR-0024: Human Console contract and static build

- Date: 2026-10-27
- Status: Accepted for H1 engineering under explicit scoped owner activation.
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
notices. A UI replacement changes financial binding; H1 grants no hot deployment
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

## H1 seam and bounded H2 acceptance

CURRENT `/h1` contains Overview, bounded wallet/order investigation and the
permitted command/receipt journey. `/` retains the existing presentation and its
verified routes/assets/tests. This is a migration-branch seam, not a deployable
dual-console product. H2 must migrate all required task groups and remove the
old HTML/JS/CSS/demo presentation plus `/h1` routing before replacement is
accepted. Required protected exports, CLI, command owners and historical
evidence survive.

H2 must complete policy/Lab argument choices and all currently supported
operations, acquisition control preview/recovery, sources/selection/rationale,
capability/setup/capacity/incidents, Shadow evaluation/exports, and any missing
producer-supported position/decision/fill links. Missing causal links stay
UNKNOWN. It must close the parity/removal ledger, broaden accessibility and
resource-isolation evidence, and obtain separately commissioned human acceptance.
It must not invent financial resume/close/cancel or an authority issuer.

Freeze H2 lab budgets at Overview <=2 s, p95 interaction-to-paint <=200 ms over
>=100 samples, initial JS <=400 KiB gzip, default/max pages 50/100, and <=5 MiB
post-GC heap growth / <=100 extra DOM nodes over 1,000 settled refreshes. The
10,000-wallet/200-order fixture and 25h accelerated browser clock are synthetic;
neither is a multi-day soak. CI/PR artifacts own actual measurements and exact
source identities, not this decision's prose. Manual screen-reader testing,
human acceptance, deployment, Live authorization and economics are unobserved.

## Official sources reviewed

- [React versions](https://react.dev/versions)
- [Vite backend integration](https://vite.dev/guide/backend-integration)
- [Mantine provider](https://mantine.dev/theming/mantine-provider/)
- [Mantine RTL](https://mantine.dev/styles/rtl/)

Documentation establishes supported mechanisms. The installed protected browser
tests establish the scope actually verified here.
