# Independent Platform Shadow operations

Status: implemented DATA_ONLY software; commissioning and real-observation
acceptance are separate receipts. See the [execution record](../18-ai-handoffs/platform-independent-shadow-2026-10-16.md).
Historical WI campaigns, roots and authority remain separate and stopped.

## Release and isolated roots

Python 3.14 is required. CI builds the wheel and immutable image, tests the image,
retains their source/archive/config identities, performs the supply-chain checks,
and exercises the installed wheel in a synthetic HTTPS desktop/mobile browser.
The release workflow promotes the retained assets from a successful full main CI
run; it does not rebuild them. Use `v0.2.0` for the declared distribution version.
A full manual main CI run is supported when automatic classification omits a gate.
Never promote a PR merge-test identity as the final main release.

Download release assets directly on each host. Verify `manifest.json`, the image
archive SHA-256 and the bootstrap script SHA-256 against that release before running:

```bash
python3 platform_bootstrap.py --artifact-directory /path/to/verified/assets --commit EXACT_40_HEX_COMMIT
```

The bootstrap verifies the archive and actual installed BUILD_COMMIT, creates
worker/web identities 10101/10102, and installs units without starting acquisition
or web access. It preserves existing assets and rejects a changed immutable root.
Docker config and OCI manifest IDs can differ across stores; both must be bound
by the verified saved archive. Moving tags are never deployment authority.

Roots are `/opt/polysia-platform/releases/COMMIT`, `/etc/polysia-platform`, and
`/var/lib/polysia-platform/{worker,control,publication}`. The worker owns financial,
authority and telemetry stores; web mounts only publication read-only and the
separate command queue writable. The queue is group-writable to the two dedicated
identities; it is not a financial command bypass. Worker and publisher use distinct
OS locks; report snapshots never copy live DB/WAL files separately. Publisher
SQL connections use `mode=ro` and `query_only`; its state-directory mount permits
SQLite to create/recover SHM bookkeeping even when the last worker closed WAL.
A physically read-only directory failed the installed-artifact test. The web
process still has no financial mount, and reports perform no financial writes.

The [worker example](../../deploy/platform-worker.example.json) defaults acquisition
to false and has no admission. Replace its release identity and private paths only
from verified receipts. Copy the existing authority database and current manifest
through SQLite Backup API when moving a diagnostic root; never initialize a fresh
counter database to escape consumed limits. Keep the original immutable evidence.
A missing old Platform root is a new epoch, not evidence of historical continuity.

## Acquisition and reporting

`research discovery-diagnostic` runs one explicit finite workload under a frozen
numeric manifest. Native first-page seeds are an acknowledged sample; each selected
wallet's activity must complete its cursor walk. PolyCop keeps its existing named
policy. Unified wallet identity does not make the two observations independent.
Native recency is not trader skill and never grants Alpha/Stress membership.

The manifest specifies host/endpoints, expiry, cadence/cohort, request/byte caps,
closure reserves, response size/timeout, disk/RAM/CPU and backup/retention bounds.
All requests reserve authority before I/O; uncertain responses remain fully charged.
`ops acquisition-policy` previews an explicitly directed continuation; `--apply`
records the predecessor/new manifests and authorization reference while retaining
all lifetime charges and STOP. It cannot raise ceilings or reduce reserves. It is
not an automatic campaign renewal. Continuous native operation additionally needs
nonempty diagnostic/resource admission for the matching code and cohort.

```bash
polysia ops shadow-report --database FINANCIAL_SQLITE --experiment-id EXPERIMENT
polysia ops shadow-report --database FINANCIAL_SQLITE --experiment-id EXPERIMENT --start UTC_START --end UTC_END
```

Check command help for output/export options. Both UTC bounds are required; the
interval is `[start,end)`. Reports reconstruct opening and closing state with the
same canonical prospective engine. Unsupported boundaries, missing/stale marks and
cross-session comparisons are rejected. Daily report windows advance independently
of RUNNING/DRAINING/FINALIZED financial state, capital and acquisition accounting.
Immutable digest-named report exports preserve prior results; the 32-MiB export
archive refuses more work at capacity rather than deleting promised replay.

Operational follower-ledger policy/capital can differ from prospective Control and
Target. Do not compound separately funded experiments or call an inception result
an interval result. Fill slippage is already embedded; hypothetical liquidation
fees and unallocated operating costs are separate. Known partial values remain
visible when total equity is UNKNOWN. Zero simulations is no measurable result.

## Console, STOP and failed dependencies

`system console --config WEB_JSON` binds loopback only. Deployment requires a
verified Cloudflare Access issuer/audience, explicit owner role map, protected CSRF
secret, owner-only Access policy and a dedicated Tunnel to loopback port 8765.
No default identity, anonymous mode or public port is provided. Every asset,
report and archived download checks RS256 identity. Commands validate role, origin,
CSRF, revision and idempotency; the worker/publisher applies durable receipts.
The protected page still serves STOP when report publication is unavailable.

The requested deep hostname lacks current free edge-certificate coverage. An unused
single-level fallback may be provisioned under the execution delegation, but only
after Access protection succeeds. An API 403 or a browser-required security approval
blocks that action; it never authorizes an unprotected origin or a paid upgrade.

If Access is unavailable, use the existing protected administrative SSH route and
the installed immutable image, with the same worker configuration/state mounts:

```bash
polysia ops platform-stop --config /config/worker.json
```

This operation sets durable STOP without provider reads or a valid cohort/admission;
it preserves consumed authority and records a command receipt. Do not merely kill
a container and assume that disables a persistent timer. `research platform-tick`
and `ops platform-publish` are separately scheduled minute jobs. Expected STOP,
expired authority, missing configuration, source degradation and internal failure
are distinct states. Old worker receipts are explicitly stale. Inspect the dedicated
unit journal and retained provider receipts; retries are finite and never widen caps.
No new alert recipient is guessed: actionable failures remain in Console/journal.

## Bounded encrypted recovery

Nuremberg's dedicated 4-GiB filesystem is `/srv/polysia-platform-backups`.
Its SFTP identity can reach only that chroot. The recovery private key is root-only
on Nuremberg, outside the upload account and all archives. Helsinki has only the
public age recipient and its separate upload key. SSH host identity is pinned
through the existing verified administrative channel, never an unauthenticated scan.

The retained `platform_backup.py` is hashed in the release manifest. It runs as a
bounded daily host job; Docker performs coordinated SQLite Backup API snapshots
under the worker lock with network disabled, then age encrypts to the public
recipient. The upload uses a partial name and atomic rename. Retain two completed
ciphertext generations, each at most 512 MiB; stage and restore within the remaining
allocation and preserve at least 8 GiB on the host. Plaintext includes release,
configuration, original policy, counters/STOP, financial data, cohort and provider
provenance. It never includes the recovery or upload private key.

Nuremberg writes a small root-owned receipt under the chroot's read-only `/status`
directory. A separate hourly primary status job fetches it through the pinned SFTP
route; the upload identity cannot replace that receipt. Console publication labels
missing, failed or stale backup/restore receipts explicitly.

The separate Nuremberg restore job retrieves a completed generation, decrypts with
the protected key, validates the bounded flat archive, all file/SQLite digests and
an independently retained release manifest, starts the same image without network,
and replays the same analytical digest. It rewrites paths into a new isolated root
and forces acquisition disabled. RPO <=24h and RTO <=60m require measured receipts,
not an SFTP login. The recovery root is not an automatically promoted second writer.
Fence the old primary and reconcile the newest authority before any real failover;
a stale backup cannot restore spent allowance.

## Rollback and retained compatibility

Stop acquisition durably first. Select the prior compatible immutable image and
its schema root; preserve newer observations, counters and open-position evidence.
Never downgrade an active financial schema in place or erase a failed migration.
Disable only the dedicated new units/connector/upload identity when rolling back;
retain ciphertext and the protected recovery key. Preserve WI and unrelated services.
The legacy `wallet-intelligence local` producer wrapper remains solely for existing
historical import/parity consumers; it is not used by the new worker, Console,
reporting or restore. Remove it only after retained-import parity and the documented
consumer migration are proven. Public research replay/accessor APIs with unique
historical-schema tests likewise remain experimental rather than live runtime gates.
