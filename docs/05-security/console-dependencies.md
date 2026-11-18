# Console dependency decision

## Human Console static frontend

The current stack uses React/React DOM 19.3.1, Mantine core/hooks
9.7.5, TypeScript 7.0.2 and esbuild 0.28.2. Node 24.22.1/npm 11.19.1 and one npm
lockfile pin development builds; production has no Node process or asset fetch.
Registry peer/engine metadata and the current official React, Vite and Mantine
documentation were checked before selection. Strict TypeScript and a generated
Python-owned schema provide checked boundary types; no runtime framework or
Python dependency was added.

The historical 2026-11-16 maintenance update retains the original 2026-10-27 stack and
applies patch releases: Mantine core/hooks 9.7.4 â†’ 9.7.5, Vite 8.3.5 â†’ 8.3.8
and Rolldown 1.2.15 â†’ 1.2.18. Mantine's patch fixes focus, timer and input
handling; Vite's patch improves Windows path startup and build behavior.
Rolldown stays on Vite's declared `~1.2.18` line, avoiding a parallel 1.3.x
bundler graph. The proposed Mantine 9.8 feature update is not adopted.
See [Mantine fixes](https://github.com/mantinedev/mantine/releases/tag/9.7.5),
[Vite release](https://github.com/vitejs/vite/releases/tag/v8.3.8) and
[Rolldown maintenance release](https://github.com/rolldown/rolldown/releases/tag/v1.2.18).

The leaderboard release replaces the Vite build dependency with esbuild 0.28.2
(MIT) from its official npm release. The prior lock pulled an unpatched
[picomatch advisory](https://github.com/advisories/GHSA-fc5q-39xc-vjpf) through
Vite and tinyglobby. npm's proposed Vite 6.2.7 downgrade produced another high
advisory in an isolated lockfile audit. esbuild emits the single JavaScript and
CSS entry with CSS modules and separate media files. The reviewed build and
license custody procedure continues to own every shipped byte. The local Python
preview serves the development build on loopback with synthetic GET-only data.
The full npm audit and SBOM checks cover the replacement. Rollback selects a
complete retained Console release and restores its matching source and lock.
See the [official esbuild release](https://github.com/evanw/esbuild/releases/tag/v0.28.2).

H2 adds exact development-only `axe-core@4.14.0` (MPL-2.0), maintained by
Deque, for automated accessibility checks of the installed protected Console.
It runs only in synthetic browser tests, is absent from the shipped bundle and
runtime notices, and joins the JavaScript audit/SBOM inventory. Testing inspects
the real document through Playwright; CSP is never relaxed. Keyboard, focus,
reflow and representative RTL checks complement automation. Incomplete rules
remain explicit evidence, not a WCAG certification or screen-reader acceptance.
Alternative: manual-only checks, which lack repeatable contrast/semantic coverage.
Rollback removes this development dependency and its audit fixture together;
it has no production runtime or financial behavior. See the
[official engine and license](https://github.com/dequelabs/axe-core).

Rolldown 1.2.18 (MIT) remains an
exact direct development dependency because the final-byte recipe uses its
published AST parser. The recipe escapes whitespace in ordinary template
literals without changing their runtime string values; tagged raw templates
fail for explicit review. This preserves the existing whitespace gate rather
than exempting generated assets. Its semantic regression tests run in Node.

Need: compose context, modal/focus, investigation and command recovery lifetimes
without maintaining more handwritten DOM state. Alternatives are continued
vanilla JavaScript or another component library; the retained Mantine proof
passes the actual Python CSP, portal/focus and RTL tests, so a second library
prototype is unnecessary. All direct packages above are maintained upstream
and MIT licensed. The build ships production transitive license notices, npm
audit fails on low-or-higher advisories, and CI generates a CycloneDX JS SBOM.
These join existing Python audit/SBOM gates; no Standards profile is expanded.

`react-remove-scroll-bar@2.3.8` declares MIT but omits LICENSE in its npm tarball
and at its published gitHead. The retained notice in `frontend/licenses/` comes
from the maintainer's official
[license blob](https://github.com/theKashey/react-remove-scroll-bar/blob/7c08c3990396ecefd90f99ff5d9a34f26f5b5616/LICENSE),
reviewed on this date; it is not claimed as a file from the historical tarball.
Other notices come directly from locked installed packages, including both
type-fest licenses. Build-input and shipped-byte hashes cover these notices.

Security/maintenance cost: JavaScript dependencies require advisory and upstream
pin review; React renders untrusted text without HTML insertion. Static CSP
retains self-only scripts, no eval and a narrowly scoped style nonce. No CDN,
service worker, financial browser persistence, telemetry or automatic mutation
retry is introduced. Wheel/sdist/container and installed browser checks verify
the exact shipped assets. Rollback restores a complete retained release and
keeps STOP and financial custody; it never swaps UI bytes within a bound run.
See [ADR-0024](../04-architecture/adrs/ADR-0024-human-console-contract-and-static-build.md).

Date: 2026-10-16. Scope: protected Platform Console only.

## Optional local HTTPS gateway

The administrative entry pins stock Caddy **2.11.7** Linux amd64, Apache-2.0,
to its official release archive and SHA-512
`a7a433a1b133efc3c8d10eb0b99d52a24b5ef5c322dc77f5282182b1c0402139ab83f3a99f0c52409df77d20123fb0b523edad8a66d8f5e49136197bf61ef0e7`.
The checksum came from the [official release](https://github.com/caddyserver/caddy/releases/tag/v2.11.7);
it is a checksum, not a signature. Extraction retains LICENSE and rejects changed
immutable bytes. The release maintainer owns security/pin review; operators use
the tested update path and retain the old gateway for rollback. The systemd unit
caps CPU, memory, tasks, descriptors and logs independently of worker/STOP.
Private and own-domain profiles share this dependency; the production Cloudflare
connector is unchanged. See [ADR-0022](../04-architecture/adrs/ADR-0022-guided-single-installation.md).

The private issuer's public CA certificate is transferred over authenticated SSH
and trusted only by a dedicated browser/client context. The administrative entry
never installs a CA globally. It generates high-entropy Basic credentials, stores
only bcrypt hashes in Caddy's configuration and keeps the credential handoff file
root-only. Browser credential caching does not delay server-side revocation after
the account is removed and the dedicated gateway restarted. Gateway trust relies
on socket ownership, not on signed forwarded headers. Failed Cloudflare validation
never selects local authentication. Isolated protocol tests and publicly trusted
domain commissioning require distinct receipts.

Use PyJWT with its cryptography extra for RS256 Access token validation, and
Waitress for bounded WSGI serving on Linux and Windows. Versions are constrained
in `pyproject.toml` and pinned in both canonical dependency locks. PyJWT is MIT;
Waitress is ZPL-2.1; cryptography is dual Apache-2.0/BSD; their distribution notices
remain in installed packages and the generated SBOM. They are maintained upstream
projects; exact lock vulnerability assessment is a required supply-chain gate.

Alternatives: trusting unsigned forwarded identity is insufficient; implementing
RSA/JWT validation locally increases security maintenance; the Python development
HTTP servers are inappropriate as the deployed server; a larger web framework
adds unnecessary surface for a cached view and small command API.

Restrict JWT algorithm to RS256, issuer/audience to protected configuration, require
expiry/issued-at/subject, cache signing keys with a finite lifetime, and use an
explicit verified subject/email role map. Reject missing configuration or tokens.
The application binds loopback and does not trust arbitrary forwarded headers.

Rollback: stop the web unit, retain the worker and private reports, then revert
the Console and these direct dependencies/locks together. No financial migration
or weakening of authentication is permitted as a fallback.

Sources: [PyJWT usage](https://pyjwt.readthedocs.io/en/latest/usage.html) and
[Waitress documentation](https://docs.pylonsproject.org/projects/waitress/en/latest/).

The runtime image also installs Debian trixie `age=1.2.1-1+b5` (BSD-3-Clause)
for public-recipient authenticated encryption. Its exact dpkg inventory is retained
and hashed into the release manifest; the real encryption/decryption smoke is a
container gate. A missing reviewed version fails the build. The recovery private
key is generated and retained only on Nuremberg, outside the upload identity.
Using an established tool avoids implementing encryption. Host package changes
and a separate host encryption daemon are unnecessary. Rollback stops the new
backup service and retains existing encrypted generations and the protected key.
See [Debian package](https://packages.debian.org/trixie/age) and
[upstream](https://github.com/FiloSottile/age).

Playwright 1.65.0 is a development-only browser acceptance dependency with its
upstream Apache-2.0 notices and pinned transitive dependencies in the development
lock. CI installs Chromium for an explicit synthetic localhost HTTPS fixture;
certificate exceptions and test identities never enter the production Console.
Desktop/mobile, keyboard, protected downloads, durable STOP and reader denial
are maintained tests, with screenshots retained separately. Rollback can remove
the browser job and development dependency together; runtime behavior is unchanged.
The WSGI choice is a scoped deviation from the larger default web stack: this
cached interface needs neither ASGI tasks nor a second background supervisor.

## Dedicated host edge connector

The protected deployment uses official `cloudflare/cloudflared` 2026.10.1
Linux amd64, 40,227,032 bytes, SHA-256
`3bfc539f45d2620c71debb7a86be0efa737ed5ccbad9eb85c787116900e5c586`.
Both hosts independently fetched and verified this exact asset. It is a separately
pinned host connector, not a Python dependency or rebuilt application image.
Upstream is maintained by Cloudflare and licensed Apache-2.0; retain upstream
license/notice obligations with distribution. Sources: [official release](https://github.com/cloudflare/cloudflared/releases/tag/2026.10.1)
and [license](https://github.com/cloudflare/cloudflared/blob/master/LICENSE).

A tunnel exposes the loopback server through owner-only Access without opening a
public origin port. The official binary avoids changing host packages or unrelated
connectors. Alternatives are the official container, with another image/runtime
boundary, or a source build, with extra build/provenance maintenance. A direct
public origin would change the approved network boundary. No Workers/Pages
service or larger application stack is introduced.

Install only at `/usr/local/libexec/polysia-platform/cloudflared-2026.10.1`.
The dedicated unit disables automatic updates, runs as DynamicUser with no
capabilities and strict filesystem protections, and caps memory at 192 MiB,
CPU at 25% and tasks at 64. LoadCredential supplies the root-only tunnel token to
`--token-file`; a management API credential is unnecessary for runtime. Edge
policy and application RS256 validation remain independent requirements.
Upgrades need a reviewed pin, verified hash, resource/security assessment and
scoped startup/denial checks; retain the original pin for rollback.

Rollback disables/stops only `polysia-platform-tunnel.service` and stops its web
unit, retaining Access protection, private reports and recovery inputs. Reverting
the connector never changes financial schemas, renews authority or activates
acquisition. Secondary copies stay dormant until primary fencing and authority
reconciliation; do not activate both as automatic failover.
