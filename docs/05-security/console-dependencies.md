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
