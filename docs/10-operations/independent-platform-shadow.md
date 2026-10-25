# Independent Platform Shadow operations

Status: implemented DATA_ONLY software; commissioning and real-observation
acceptance are separate receipts. See the [execution record](../18-ai-handoffs/platform-independent-shadow-2026-10-16.md).

## Release and isolated roots

The root-only administrative entry is `platform_admin.py`, distributed beside
the manifest-verified bootstrap in the same exact immutable release. Current
release [v0.4.0](https://github.com/PolySia-Systems/Platform/releases/tag/v0.4.0)
contains the SDK 0.13.0 migration from [PR #200](https://github.com/PolySia-Systems/Platform/pull/200).
The owner's clean-server decision supersedes the old v0.3.0 staging blocker.
Historical receipts remain unchanged; ordinary retained-state upgrade gates remain.
The dated clean-install receipt records actual private activation and cold recovery.

On a supported Ubuntu LTS amd64 server, administrative SSH, Docker/systemd,
at least 1 GiB available RAM and 8 GiB free staging/rollback space are prerequisites.
Fresh private setup creates its own reader/operator credentials and configuration;
it creates no acquisition manifest or admission. For a fresh server, download the
published entry into a new private directory and verify its recorded SHA-256
before running it. Ubuntu's Python and coreutils suffice for this bootstrap:

```bash
set -eu
mkdir -m 700 polysia-v0.4.0
cd polysia-v0.4.0
python3 -c "from urllib.request import urlretrieve; urlretrieve('https://github.com/PolySia-Systems/Platform/releases/download/v0.4.0/platform_admin.py', 'platform_admin.py')"
printf '%s  platform_admin.py\n' '4f2668ace166d6f8cb2bed4ac7f01bcb7086ef046a14215dded2e318fec35301' | sha256sum --check
sudo python3 platform_admin.py install --tag v0.4.0 --commit 4f3b611adae17defbcc6e24b4f9f917b466d5ad8
```

The entry downloads and verifies its matching bootstrap and remaining release
assets from the same trusted origin. The checksum is not an author signature;
`gh release verify v0.4.0` additionally verifies GitHub's release attestation when
GitHub CLI is available. On interruption, rerun the last administrative command
from the retained directory rather than overwriting it. These fresh-install
commands do not authorize activation over incompatible retained state.

The default guided choice is private SSH access. For noninteractive use add
`--noninteractive --profile private`. The same validation generates configuration,
stages/verifies immutable assets, installs supervision and checks actual HTTPS.
Reruns retain credentials and data. `status`, `preflight`, `stop` and `uninstall`
are administrative actions; uninstall retains data, keys and generations.
Protected STOP writes an OS restart fence before stopping the dedicated worker.
If authority persistence is uncertain, it reports that uncertainty and leaves
restart fenced. Never delete a fence merely to get a service running.
After first setup, a missing or damaged command queue is not automatically
recreated by the browser, publisher or configured worker. Its receipt identities
must be recovered. Independent SSH STOP still fences supervision and reports
whether durable authority STOP and a command receipt were separately confirmed.

Private access uses `https://localhost:8443` through an authenticated SSH forward:

```bash
ssh -N -L 8443:127.0.0.1:8443 YOUR_ADMINISTRATIVE_SSH_DESTINATION
```

Transfer only `/var/lib/polysia-platform/gateway/caddy/pki/authorities/local/root.crt`
over the same host-key-verified SSH connection. Verify its SHA-256 on both ends.
Import that public certificate into a dedicated browser trust context, or use an
explicit client CA file. Never disable certificate checks or silently trust the
CA system-wide. The root-only `/etc/polysia-platform/gateway-credentials.json`
contains the generated browser credential handoff. Keep it private; no owner
Cloudflare or provider credentials are needed for this profile. Browser reads
without a manifest show UNCONFIGURED and unknown economics. Choosing no backup
shows UNPROTECTED rather than a recovery claim.

Own-domain setup uses `--profile own-domain --hostname YOUR_HOSTNAME --public-opt-in`
and the same authentication/socket path. Only this explicit choice permits
ports 80/443 for ACME/redirects and authenticated HTTPS application content.
The existing installation is not converted automatically. Actual public-domain
commissioning still requires an authorized hostname and ingress; a test CA is
not publicly trusted evidence. Never apply these flags to change current
production DNS, Cloudflare policy or ingress in this execution.

Application Python 3.14.8 is pinned; the root host entry uses Ubuntu's existing
Python 3.12+ without replacing it. Ubuntu 24.04/26.04 amd64 are admitted profiles;
only OS versions named in actual acceptance receipts are verified. CI builds
the wheel and immutable image, tests the image,
retains their source/archive/config identities, performs the supply-chain checks,
and exercises the installed wheel in a synthetic HTTPS desktop/mobile browser.
The release workflow promotes the retained assets from a successful full main CI
run; it does not rebuild them. Exact-main CI 39274691513 and release workflow
39276778666 bind v0.4.0 to source `4f3b611adae17defbcc6e24b4f9f917b466d5ad8`.
The earlier v0.3.0/v0.2.1 staging/runtime evidence remains historical after the
owner's reset. A dated installation receipt establishes actual host state.

A full manual main CI run is supported when automatic classification omits a gate.
Never promote a PR merge-test identity as the final main release.

### Maintenance and identity configuration

Use the verified release's administrative entry for `configure` (access profile),
`update` (exact new tag/commit), `rollback` (retained compatible configuration),
`backup`, `restore`, `status`, `preflight`, `stop` and `uninstall`. Configuration
and units are checkpointed before replacement, with content digests and original
ownership/modes. Interrupted activation writes `ACTIVATION_INCOMPLETE` and fences
the worker; inspect that receipt and dedicated unit logs before retrying the
same exact release. A retained fence is not cleared by an install/update. Rollback
restores compatible configuration and leaves a stopped, inspectable worker; it
does not downgrade a database or erase newer observations. Open inventory,
pending observations and active persistent sessions refuse code activation.
`preflight` reports that refusal with a nonzero exit. `stage` downloads and
verifies the exact archive/scripts and image metadata without loading a Docker
image or changing active configuration, units or data. Its durable staging
receipt records activation eligibility separately; it is not a deployment claim.

A new Cloudflare installation supplies `--access-issuer`, `--access-audience`
and `--access-owner` (or answers the guided prompts). Those configure only the
signature-validating loopback backend. The owner separately creates an owner-only
Access application, DNS/ingress and a Tunnel to `127.0.0.1:8765` in their account.
Missing inputs produce `ACCESS_CONFIGURATION_REQUIRED`; no public backend is
created. Existing production web identity and Tunnel inputs are preserved.
Neither successful setup nor an external-identity configuration receipt proves
that a new route/login was commissioned.

The private gateway CA is not globally installed. Retain its public fingerprint
with SSH host verification and use a dedicated browser trust context. Basic
credentials can remain in the browser cache. Use `configure --remove-user USER`
to revoke, or `configure --reader USER` / `configure --operator USER` to add or
change a local role. At least one operator must remain. Validated access
configuration recreates the backend and gateway, so subsequent
requests are denied. Protect the root-only credential handoff. No password-reset
endpoint or root-capable browser settings are exposed. The certificate health
timer checks actual local TLS with explicit trust, publishes expiry/failure and
next action, and grants no acquisition authority. Own-domain certificates use
the system public trust store; controlled-ACME test receipts use separate test
trust and are not public commissioning evidence.

### Backup changes and replacement-server restore

`backup --backup-mode none` disables the dedicated schedule and reports
UNPROTECTED, retaining all generations. For an encrypted local checkpoint use
`--backup-mode local --recipient-file ABSOLUTE_PUBLIC_RECIPIENT_FILE
--recovery-key ABSOLUTE_SEPARATELY_HELD_KEY`. For independent SFTP add
`--backup-mode sftp --secondary-host HOST --secondary-port 22
--known-hosts-file ABSOLUTE_PINNED_HOST_KEYS --upload-key-file ABSOLUTE_ROOT_ONLY_KEY`.
Recipient and destination files are inputs obtained over an authenticated channel,
not configuration files to edit. SFTP prerequisites are an independent bounded
destination with restricted upload access and a separately held root recovery key.
The primary never receives that private key for routine backup. A candidate stays
uncommitted until its exact ciphertext has a real decrypt/replay proof; SFTP proof
is fetched from the destination's protected restore receipt. Failed B leaves A
active; successful B permits retention on B without deleting A's retained files.
Local encrypted checkpoints do not establish independent-host protection.

Existing `backup.json`/upload credentials/generations are recognized on first
guided maintenance and preserved, with the backup executable promoted to the
verified release. The prior proof is labeled retained/reverification required;
fresh backup/restore receipts establish protection for that release.

On a clean replacement, use the same release's `restore` entry with normal
private/profile options plus `--archive ABSOLUTE_GENERATION --recovery-key
ABSOLUTE_SEPARATELY_HELD_KEY`. It verifies/decrypts/replays before importing any
financial data, retains report/export identities and consumed authority, and
fences worker restart. Existing command, financial or report state is refused
before replacement writes. An interrupted import retains staging and a fence;
inspect the receipt and finish or recover into another clean root rather than
overwriting partial evidence. Lost-primary recovery needs the independently
retained release manifest/image, SSH access, key and identity-recovery procedure;
a key solely inside its own encrypted backup is unusable. Do not restore web
credentials from an unverified primary. Use generated replacement credentials
and a separately verified public CA, or separately commission the owner's route.
Fence the old primary and reconcile newest authority before any future resume.

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

Persistent native composition uses `continuous-shadow-native-research-v2` for a
new admitted financial session. Admission includes UTC `expires_at`, matching
code/original cohort, nonempty persisted simulations and resource approval. Every
due tick checks admission and authority before source work. The same identities
are revalidated after three hours through complete wallet-activity walks and
mapping/fee/current-book checks; the original frozen lookback is preserved.
Successful receipts are cached in `cohort-revalidation.json` beside authority
(or protected `cohort_refresh` configuration), binding code/original cohort.
Retries are finite and charged; incomplete or insufficient evidence cannot advance
financial watermarks or replace a cohort. No admission carries across releases.

An already DRAINING session does not revalidate entry eligibility or spend its
closure reserve on cohort rediscovery. It retains the admitted identities and
uses the existing complete-source/current-market close-only path. Stale cohort
eligibility cannot admit new exposure. STOP, admission/policy expiry, absolute
request/byte and window ceilings still apply; missing or ambiguous closure
evidence retains inventory and uncertainty. Restart never replenishes authority.

The financial session has no daily time reset. Event/storage ceilings and explicit
drain/finalize remain enforced with open inventory and pending observations.
Daily/UTC reports view retained state, not fresh capital. A changed cohort or
release needs a controlled compatible financial-session decision while flat using
existing preparation/transition controls. Preserve old roots and release-specific
replay. No new session/acquisition is activated by patch deployment.

The minute supervisor enforces manifest cadence through a durable pre-I/O due
slot retained across crash/restart. `WAITING_CADENCE`, `WAITING_RETRY` and
`WAITING_WORKER` distinguish ordinary scheduling/overlap; a regressed UTC clock
blocks source work. Controls precede waiting. STOP bypasses queue backlog, fences
earlier resume work and needs no financial/provider access. Drain without a
financial session returns a blocked receipt. Exports have a separate publisher
queue. STOP and expiry never imply that existing positions settled.

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

The protected owner Console is [console.movafegh.com](https://console.movafegh.com).
The original deeper hostname lacks current free certificate coverage; its supplied
DNS record was preserved. The covered fallback was published after Access policy
and origin denial verification. Do not add an anonymous route or paid upgrade when
access fails. Login/render is verified; comprehension is a separate condition.

Helsinki's enabled `polysia-platform-tunnel.service` pulls in the static
`polysia-platform-web.service` at boot. A dedicated hostname ingress serves only
loopback port 8765 with a terminal 404. Check both services and existing timers
with `systemctl status`; use the dedicated unit journals for errors. The pinned
binary is `/usr/local/libexec/polysia-platform/cloudflared-2026.10.1`; its
[dependency decision](../05-security/console-dependencies.md) records checksum,
notices and rollback. Automatic binary updates are disabled.

The connector uses systemd LoadCredential from root-only
`/etc/polysia-platform/tunnel-token`, passed with `--token-file`; never put its
value in unit arguments, environment, reports or Git. The administrative API token
is not a runtime dependency. Web configuration and CSRF files under
`/etc/polysia-platform` are root-owned mode 0640 with web group 10102. Access
requires the exact verified issuer/audience and sole authorized owner role map;
no wildcard or bypass rule is permitted.

To stop public serving without changing worker state:

```bash
systemctl disable --now polysia-platform-tunnel.service
systemctl stop polysia-platform-web.service
```

Keep the owner-only Access policy in place. To restart this commissioned route,
after checking protected configuration and the pinned binary:

```bash
systemctl enable --now polysia-platform-tunnel.service
```

Verify both services are active and only `127.0.0.1:8765` is listening.
Missing-identity origin requests must be 403. Public anonymous JSON GETs for `/`,
`/api/report`, `/api/health`, `/api/commands`, `/download/comparison.csv`,
`/console.js` and `/console.css`, and an anonymous command POST, must be rejected.
Ordinary browser navigation must reach the named Access login with normal TLS.
The owner completes email login personally; never collect OTPs in chat. Restarting
this route does not renew acquisition authority.

Visible Console pages perform serialized read-only refresh approximately every
20 seconds with a 10-second request deadline. Hidden pages suspend refresh and
refresh immediately on return. Local aging continues during network failure;
worker age, publication age and retained financial cutoff are separate. A fresh
publisher cannot make an old worker receipt healthy. Background reads do not
resubmit commands or clear user-entered boundaries/filters.

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
allocation and preserve at least 8 GiB on the host. Backup/restore preflight
additionally reserves 1 GiB for bounded plaintext/ciphertext staging; failure
occurs before snapshot/decryption. Destination configuration history is bounded
to 64 distinct retained checkpoints and fails explicitly when full. Plaintext includes release,
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

New backups also retain the bounded immutable `reports/` archive under the same
encrypted inventory. Restore verifies report digests and recreates download paths.
Historical APPLIED export receipts whose artifacts cannot be recovered become
explicit FAILED receipts with their prior result retained, on a separate restored
command-store copy. The verified original snapshot remains unchanged. Recovered
exports are independent frozen results, not permission to query a provider.

The protected secondary directory `/etc/polysia-platform-recovery/console`
retains web configuration, unit templates, the dedicated runtime token and
independent CSRF. Credential files are root-only; the directory is mode 0700,
outside the upload identity. The administrative API token is not retained there.
Refresh these inputs through verified administrative SSH whenever primary
equivalents change. Both hosts retain the independently hash-verified connector.
Secondary units are templates only; the connector stays inactive.

The frontend isolated startup receipt uses the same image, network none,
128 MiB/0.25 CPU, independent CSRF and no financial-store mount. It supplements
complete financial recovery; it does not replace replay or measured RPO/RTO.
For manual failover, first fence the primary and reconcile newest authority with
the existing recovery-worker fence. Adapt paths, generate independent CSRF and
install retained dedicated templates only after these checks. Never start a
second writer or restore spent allowance.

## Rollback and retained compatibility

Stop acquisition durably first. Select the prior compatible immutable image and
its schema root; preserve newer observations, counters and open-position evidence.
Never downgrade an active financial schema in place or erase a failed migration.
Disable only the dedicated new units/connector/upload identity when rolling back;
retain ciphertext and the protected recovery key. Preserve unrelated services.
Public research replay/accessor APIs with unique historical-schema tests remain
experimental rather than live runtime gates.
