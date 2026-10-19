# ADR-0022: Guided single-installation maintenance and HTTPS access

Date: 2026-10-19. Status: Accepted under the owner's scoped execution delegation.

## Decision

Retain the Python modular monolith, immutable Docker artifact and dedicated
systemd supervision. The root-only administrative entry shares bootstrap,
versioned configuration validation and durable phase receipts. It creates no
acquisition policy, admission, capital or provider connection. Existing data and
consumed authority survive retries. Protected OS STOP fences worker restarts
even when identity, publication or the command database is unavailable.

CURRENT access mechanisms are verified Cloudflare Access, or the optional stock
Caddy gateway. Local gateway profiles share hashed Basic authentication and
explicit reader/operator roles; they use a permission-restricted Unix socket,
never an identity-bearing TCP backend. Private access binds loopback and uses
authenticated OpenSSH forwarding plus explicitly bootstrapped certificate trust.
Own-domain access is an explicit opt-in using ordinary ACME HTTP/TLS challenges
on ports 80/443. Test-CA acceptance is distinct from public-domain commissioning.
The existing production Cloudflare profile remains unchanged by this decision.

The gateway has no financial/control database access, Docker socket or root
execution API. Caddy's administration API is disabled. Client identity headers
are stripped and replaced only after authentication; Host/Origin, CSRF, bounded
requests, command idempotency and role checks remain application gates. Basic
credentials may be cached by browsers; revocation removes the gateway account
and recreates both the backend and dedicated gateway, denying subsequent requests.
Atomic replacement of a bind-mounted configuration alone does not reload its
inode in an existing container. Basic has no
Cloudflare MFA/session semantics. A separately retained CA private key is never
transferred for browser trust; only its public certificate crosses SSH.

## Alternatives and limits

A custom password/session/IAM service increases cryptographic and operational
maintenance without a product need. A public setup wizard would require root
authority in the browser. Kubernetes, a second database and automatic failover
are unnecessary. A checksum binds downloaded bytes to a trusted release origin;
it is not a signature. Active pinned sessions, open inventory, pending evidence
and incompatible schemas require safe refusal, retaining the old executable and
data. A database downgrade is not rollback.

Stock Caddy is separately pinned in the administrative entry; its Apache-2.0
license is retained with the binary. Resource ceilings bound the gateway to
192 MiB, 25% CPU, 64 tasks and 256 file descriptors. The maintainer reviews
gateway security/updates; the operator promotes reviewed pins. Rollback stops
the optional gateway and selects retained compatible units/configuration; it
does not alter financial stores, STOP, authority, DNS or Cloudflare policy.

Acceptance receipts in PR #198 determine tested implementation scope. Human
usability trials and authorized publicly trusted domain commissioning remain
EXTERNAL; this decision does not claim they passed.

The native financial session also keeps a small durable identity marker beside
its database. Losing a database while retaining its marker fails closed rather
than initializing new cash. Backup includes that marker when present. Missing,
empty or identity-mismatched retained authority similarly cannot initialize new
allowance. Config rollback restores hash-checked units/configuration with their
ownership/modes and leaves a restart fence; it never downgrades financial data.
