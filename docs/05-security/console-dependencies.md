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
