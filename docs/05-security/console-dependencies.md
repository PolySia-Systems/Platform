# Console dependency decision

Date: 2026-10-16. Scope: protected Platform Console only.

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

Playwright 1.64.0 is a development-only browser acceptance dependency with its
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
