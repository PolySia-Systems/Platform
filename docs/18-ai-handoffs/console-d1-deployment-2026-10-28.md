# D1 Console integration and DATA_ONLY deployment

Date: 2026-10-28. Status: DATA_ONLY_DEPLOYED_AND_COMMISSIONED_WITHIN_D1.
This is dated operational evidence. Live host queries own current runtime truth.

## Authority and target decision

The owner explicitly activated Master Prompt D1, then confirmed Helsinki
`37.27.8.79` for Platform and Nuremberg `91.99.29.4` for independent recovery.
Administrative SSH used the existing aliases `Hetzner-Finland-Helsinki-01` and
`Hetzner-Germany-Nuremberg-01`, with BatchMode and StrictHostKeyChecking enabled.

At 14:16:34–14:17:21 UTC, the documented Platform installation, configuration,
state, recovery directories and dedicated units were absent. The owner’s target
clarification authorized a fresh installation on these existing servers. Neither
an alternative host nor a second active writer was selected. Both hosts reported
Ubuntu 26.04.1 LTS, amd64, Docker 29.9.2, about 4 GB RAM and about 28 GB available
disk before task staging. Unrelated services were preserved.

Pinned administrative Ed25519 fingerprints:

| Host | SHA-256 fingerprint |
|---|---|
| Helsinki | `doblcAu6vZyLzGiGOQSTfmP1YKJADU7GQLuiUlwRc3M` |
| Nuremberg | `S+OD2i3pABQhtFsGH54PDSmt2qchnDig5UX1HUaUNrM` |

The latest clean-install receipt used private HTTPS through SSH. That supported
profile was selected for the fresh installation. An anonymous public request to
`https://console.movafegh.com` returned a Cloudflare Access login redirect at
14:19:58 UTC; this establishes neither backend placement nor a working origin.
DNS, Cloudflare Access/Tunnel, public ingress, firewall and global CA trust were
unchanged. The authorized private origin is `https://localhost:8443` through SSH.

## Protected integration and immutable source

| PR | Actual merge commit | Merge UTC |
|---|---|---|
| [#229](https://github.com/PolySia-Systems/Platform/pull/229) | `7c18cf87e979b19ca49f181035933e770a762de1` | 14:34:32 |
| [#230](https://github.com/PolySia-Systems/Platform/pull/230) | `45e044cdc7a2c1c5de6399006f3a24ab41e8f54d` | 14:51:27 |
| [#233](https://github.com/PolySia-Systems/Platform/pull/233) | `8faa568ba3d2e03bac7cc758260b3e67626b23c4` | 15:18:58 |

The active rules required a current `CI Gate` and zero approving reviews. Each
draft was marked ready, bases were updated with merge commits, and stacked PRs
were retargeted to `main` in order. Required checks passed before each merge.
No self-approval, protection bypass, force push or history rewrite was used.
Delivery/dependency branches were retained.

The first updated #230 strict OSV audit exposed its still-pinned
`msgpack==1.2.2` / CVE-2026-114613. Accepted correction commit `59181c6` was brought
forward unchanged as `398e523`: the two locks select 1.2.4 and retain the existing
supply-chain decision. Local deterministic-lock verification and the secret scan
passed; subsequent native supply-chain checks passed. Superseded CI runs are not
acceptance evidence.

- Accepted Console source: `9fd37dd014da043dc7d80b249dfb78a615424aa4`.
- Accepted tree: `3d211aebe8ed42356dafb825ff9f98ef7727901f`.
- Integrated source / image `BUILD_COMMIT`: `8faa568ba3d2e03bac7cc758260b3e67626b23c4`.
- Integrated tree: `fd1ece91e43a04cda1a459f7c0730ad856ffcf7b`.
- The sole final-tree delta from acceptance is development lock `jsonpointer`
  3.4 → 3.5, already merged independently on `main`. Runtime source, runtime
  dependencies and the accepted Console bundle are unchanged.
- Exact-main validation: [CI 40714695972](https://github.com/PolySia-Systems/Platform/actions/runs/40714695972).
  All required jobs succeeded; the run completed at 15:43:06 UTC.

Final-main Linux: **1,948 passed / 28 configured skips in 148.76 s**; Windows:
**1,944 passed / 32 configured skips in 1,116.97 s**, plus eight operational
composition preflight cases in 35.58 s; installed-wheel browser: **26 passed in
113.40 s**. Standards, compile, Ruff, Mypy (316 modules), secret scan, docs/links,
environment integrity, deterministic locks, build, strict OSV, both SBOMs,
frontend checks, image, installation/recovery and CI Gate passed. Scheduled
dependency-health was skipped by policy. Linux ordinary-suite skips comprise the
26 separately passing browser cases and two unavailable private historical
evidence fixtures; Windows additionally skips four Linux ownership cases.

H1/H2 and the accepted HC-R1/HC-R2 review were reused. No broad H3 was launched.
The previous [final-source CI](https://github.com/PolySia-Systems/Platform/actions/runs/40680309545)
supports unchanged engineering inputs; it does not replace exact-main evidence.

## Privately retained artifact identities

All final inputs come from exact-main CI 40714695972. No public release was
published, tag overwritten, moving branch deployed or old artifact relabeled.
Version metadata remains 0.4.0; source identity is the new exact commit.

| Input | Verified identity |
|---|---|
| Native image artifact | `12827258942`, archive SHA-256 `186f3f14390a46609d67a3b0d12ff64c3923b4e713605cd1d43f0d2026620a16` |
| Image tar SHA-256 | `1189473c8eae3d9cc40bcec86b867e9d09a407837b04354795c6daed227ad7b4` |
| Native image config ID | `sha256:12de3e4f0e91f0767ac9463f1003de93b3e6cca1fc9469a5b8c5ab1249f392f8` |
| Archive-bound host OCI ID | `sha256:c6b278e0df220185e9689b499ec36feaaae22c8cbbb5efaee6f1afd1866ad1cc` |
| Wheel SHA-256 | `2d8ca8ec415d0d94946908245e0ce533c6b16c856f8e2a8454f84f473a5612be` |
| Installed first-party package digest | `b208e1071420c4d5a3581014e621855fa24677f1d3b6df936255d2885492c14f` |
| Console source | `486d16d75740e939912fee9d86a1e9176b1c21e258d14b014b76c1854a598277` |
| Administrative script SHA-256 | `4f2668ace166d6f8cb2bed4ac7f01bcb7086ef046a14215dded2e318fec35301` |
| Bootstrap SHA-256 | `1f0c9eb2d374e1e2917b945abc3888fd7c10c8e5fdf491f25a1ae19ce77c4dc2` |
| Backup script SHA-256 | `047cf2695143cf54c217f78d1c29d2c836f7898da854ced32bac48e24635c5bc` |
| OS inventory SHA-256 | `5152875775b0e765ee513b01f31ea1f1024cca604d8a7a31d67c0a9d2551ae1d` |
| Original manifest SHA-256 | `326da547fee4e3e42f0d14f80eb0b9872bc05ab26b82feceed6a7943556ef5e7` |

Native package artifact `12828317215` has archive digest
`b99a9a213715f77030426e6d753717eb736755499c149ab23c8af34fea41589f`.
Python SBOM artifact `12827109281` has archive digest
`8ba140b1e02f27bda0aded3622bd57e0c2656bc53f493d7d9422ba37d42d5ced`;
Console SBOM `12828345594` has digest
`f3cd2ed144e4b2cbd2e01f3f86e3bc0ea14d090b753809ff3e875aa4b181df81`.
The wheel/sdist and both SBOMs are privately retained beside the original image
inputs on both hosts; the original manifest was not rewritten.

Both native image identities are bound by the same verified archive; host Docker
uses its OCI identity. All 330 first-party wheel files match Git byte for byte
and all 330 installed image files match that wheel. The new native wheel is
byte-identical to the accepted reference. The image embeds the integrated commit.
Python is 3.14.8; Node is absent; image defaults are DATA_ONLY and Live false.

Private candidate directory on both hosts:
`/opt/polysia-platform/downloads/8faa568ba3d2e03bac7cc758260b3e67626b23c4`.
Artifacts transferred over verified SSH using short-lived GitHub URLs, with
archive SHA-256 verification and canonical manifest/archive validation. Tokens
and private keys were neither printed nor placed in tracked content.

## Actual host qualification

The exact final-main image completed a network-disabled, isolated synthetic
process probe on Helsinki at 15:27:29 UTC in 3.193 seconds. Distinct PIDs ran a
UID-10101 worker and root supervisor. Eight mutations completed independent ACKs
while a separate process held SQLite exclusively for 150 ms. A second writer and
worker custody write were denied. The unchanged two-second ACK deadline expired
in 2.002 seconds when supervision was withheld. STOP stayed latched, unqualified
and stale-checkpoint restarts were rejected, nine attempts remained, and consumed
receipt replay was rejected. Temporary fixture authority was confined to this
network-disabled instance; it was never real installation authority.

All seven HC-R1/HC-R2 browser journeys passed on the same final-main image in
71.70 seconds at 15:29:23 UTC. The installed Python package served isolated
synthetic data; a separate real Chromium process drove the shipped bundle. This
covers account-bound expiry, unrelated history, wrong-key/late recovery,
overlapping intent, CSRF rotation, expired preview and revocation. No real
publication or receipt was overwritten for fault injection.

The reference-image probe first exposed setup mistakes in the probe itself:
witness placement, the lock exception type and a no-exec temporary tooling mount.
Those were corrected in isolated task tooling. The final-image tests above had
no product-source change or weakened assertion. Ephemeral QA tooling is separate
from the runtime image. Actual HTTPS trust checks use an isolated CA store with
certificate validation enabled.

## Activation, access and restart

The exact shipped `platform_admin.py preflight`, `stage` and `install` path
activated Helsinki at **15:46:14 UTC**. Runtime assets and installation receipt:
`/opt/polysia-platform/releases/8faa568ba3d2e03bac7cc758260b3e67626b23c4`.
Configuration: `/etc/polysia-platform`; state: `/var/lib/polysia-platform`.

The existing D1 preparation fence prevented the installer's first cold worker
tick. Its phase receipt correctly recorded `ACTIVATION_INCOMPLETE`. Inspection
confirmed UNCONFIGURED state, acquisition false, empty admission and absent
financial/authority stores. One explicitly bounded, network-disabled installed
DATA_ONLY tick initialized only the cold command/status stores. The same exact
installation resumed once and reached `ACTIVATED`. The OS fence was retained
throughout; no source bytes were patched, markers cleared or allowance issued.

Actual HTTPS probes at **15:46:34 UTC**: operator/reader GET 200; anonymous,
incorrect password and anonymous identity spoof 401; reader mutation, spoofed
reader mutation, wrong Origin, missing CSRF and direct backend without identity
403; wrong Host 421. All six retired presentation routes returned 404. Production
CSP, explicit certificate validation, absent public backend listener and
unprivileged Unix-socket denial passed. The web process is UID/GID 10102:10102,
network none, read-only root, all capabilities dropped, bounded local logs;
its mounts exclude financial state, signer, issuer, custody and Docker access.
Gateway uses UID 10102, a protected Unix socket, 192 MiB / 25% CPU and bounded logs.

Protected DATA_ONLY STOP key `d1-data-only-stop-20261028` was admitted (202), then
applied by one network-disabled unconfigured control tick. At **15:47:25 UTC**,
revision **1 / APPLIED**, zero pending commands and SQLite integrity survived
one planned web/gateway restart. The OS fence digest remained
`7cb6403b37504a392de0db6a4afad9213c6f6990d6566bc5ce189589000dd8d1`.
Worker timer is disabled/inactive; worker containers are zero. The independent
SSH STOP receipt accurately says `NO_AUTHORITY_CONFIGURED` and does not invent
a stopped financial authority or consumption row.

All five deployed workspaces passed at 1440 and 390 pixels at **18:12:07 UTC**,
using Chromium, a dedicated NSS trust database and normal certificate validation.
Screenshots were inspected. Financial/account/scope/economics remain UNKNOWN;
the deliberately fenced worker receipt is honestly STALE while the publisher is
fresh. Refresh did not manufacture account evidence or resume work. Automated
browser checks are not human comprehension acceptance.

The browser probe used a root-readable copy of the public CA after its first
mount retained the gateway owner's 0600 mode. Firefox could not launch in the
restricted tooling container; Chromium with explicit local CA trust passed.
Production permissions, CSP, certificate checks and global trust were unchanged.

At **18:15:39 UTC**, post-install identity/package/configuration readback passed.
Configuration inventory digest:
`c589f0d816217c85a13703395c40e164d60cbcf288e11a79fe2b3f094267e800`.
It hashes canonical sorted compact JSON of each retained active configuration and
dedicated unit's path, SHA-256, UID, GID and mode. The private file-level inventory
is `/opt/polysia-platform/d1-evidence/identity.json`; secret values are excluded.

Owner access follows the existing private profile:

```bash
ssh -N -L 8443:127.0.0.1:8443 Hetzner-Finland-Helsinki-01
```

Open `https://localhost:8443` with explicit dedicated client trust. Public CA
PEM-file SHA-256:
`c02dd499c6ae0cd578690568105c65409126c5992d710638851067adb8e0b4f4`.
The public CA was transferred through verified SSH and the hash checked locally.
Generated owner/reader login handoff remains in root-only
`/etc/polysia-platform/gateway-credentials.json`. Public-domain origin
commissioning is not claimed.

## Independent backup and restore

The dedicated SFTP account is restricted to `/srv/polysia-platform-backups` on
Nuremberg, key-only authentication and the Helsinki source address. Its public
authorized-key file is root-owned 0644; an initial 0600 configuration prevented
sshd reading it as the upload identity and was corrected. Administrative SSH and
restricted `/incoming` / `/status` reads then passed.

The independently generated recovery key remains root-only at
`/etc/polysia-platform-recovery/recovery-key`, outside the upload chroot. Only its
public recipient reaches Helsinki. Public-recipient file SHA-256:
`02eef53f779b3a538dcfe634d1da19c42608ee5bbfa4d7d0226bfa079ba38b6a`.
The recovery target remains fenced. No signer or financial owner key was copied.

The canonical backup snapshots SQLite through its Backup API under the worker
lock, encrypts with age, uploads through pinned SFTP and commits destination
selection only after matching independent restore proof. The first generation
returned `AWAITING_INDEPENDENT_RESTORE`; only real Nuremberg verification permitted
`DESTINATION_VERIFIED / INDEPENDENT_SFTP`. A subsequent final backup includes the
committed configuration and applied STOP identity.

Final generation: `platform-20261028T154802Z.tar.age`, **77,453,976 bytes**,
SHA-256 `6269a7187ac5517e17cf6612421c1a58d4661dc0516dfdf65286a63e84404757`.
Uploaded at **15:48:23 UTC**; Nuremberg verified it at **15:49:12 UTC** with
**RPO 56.286 s / RTO 43.758 s**, network none, acquisition false, real orders
false and UNCONFIGURED runtime. Both 24-hour / one-hour objectives passed.
Two encrypted generations are retained, bounded to 512 MiB each; actual host free
space exceeded the canonical 8 GiB reserve plus staging allowance. The earlier
documented 4 GiB filesystem was absent; this authorized fresh destination uses
the existing filesystem with the canonical capacity and retention checks.

At **18:16:30 UTC**, an additional isolated decryption verified SQLite integrity,
the identical **revision-1 APPLIED STOP key**, zero pending commands and the same
absence of financial authority/inventory. A network-disabled, 128 MiB / 25% CPU
frontend instance of the same image rendered the correct bundle and rejected an
anonymous Unix-socket request (403), using a copied command snapshot and fresh
independent CSRF. No financial mounts, copied signer or second worker were present.
Its temporary socket directory was corrected to the product's required 0770
permissions after an initial probe guard refusal. Plaintext staging was removed;
encrypted generations, independent key and manifests remain retained.

Enabled durable jobs: primary encrypted backup **00:15 UTC daily**, secondary
isolated restore **00:45 UTC daily**, primary recovery-status fetch every **15
minutes**, publisher and health each minute. Backup/restore jobs are bounded to
640 MiB / 50% CPU / 256 tasks / 600 s; status fetch to 256 MiB / 25% / 64 / 60 s.
Actual job starts succeeded; the primary publishes the independent restore
receipt. Recovery remains fenced. Real financial recovery is NOT_PERFORMED:
there is no financial authority, journal/witness/custody or real inventory in
this fresh installation. Synthetic/CI financial recovery does not replace that
later qualification.

A separate canonical `preserve_rollback` checkpoint retained **22 configuration
and unit files** with hashes, ownership and modes. Checkpoint identity:
`e84bed84fd7ffbf7a7eac31063c94af0cf604679c458361ce3937590fa0df661`.
Its **61,640-byte** age-encrypted archive has SHA-256
`7fea2e09953b2e541a121f55f0938fbf1930bc0f99068c87464da17f0e5fe62a`.
Nuremberg independently decrypted and verified every saved file at **18:25:18
UTC**, then removed plaintext staging. The protected ciphertext and verification
remain under `/etc/polysia-platform-recovery/console-config`. Configuration was
not applied to the recovery host. Financial signer and TLS CA private keys are
excluded; a future private-gateway replacement requires explicit CA trust
bootstrap. No previous installed release existed, so this is the current
recoverable configuration checkpoint, not an invented previous-release rollback.

## Ten-minute commissioning observation

**PASS:** 18:08:58.284–18:18:59.663 UTC, **601.379 seconds**, **21 samples** at
30-second cadence. Dedicated web/gateway remained active; worker service/timer
stayed inactive/fenced. Unexpected restarts **0**, dedicated service error records
**0**, maximum queue age **0 s**, minimum available disk **22,596,898,816 bytes**,
minimum available RAM **2,836,955,136 bytes**. SQLite/WAL/publication file sizes,
bounded local web-log bytes, CPU and process memory were retained per observation.
The worker receipt remains deliberately stale, independently of fresh publication.

The first observer stopped before accepting a sample because Docker's `local`
driver exposes an empty `LogPath` in this store. The corrected observer discovered
the dedicated container's actual local-log path from DockerRootDir and container
identity. Only the complete fresh window above is commissioning evidence. Task
interruption/waiting time is not represented as additional soak coverage. No
multi-day reliability claim is made.

## Verification, rollback and cleanup

Exact-main CI executed the repository gates: `python scripts/validate_standards.py
--mode full`; `python -m compileall -q src tests`; `python -m ruff check .`;
`python -m mypy src`; `python -m pytest -q`; `python -m pip check`;
`python scripts/dependency_locks.py check`; `python -m polysia.security.secret_scan`;
`python -m build`; strict OSV `python -m pip_audit --strict
--vulnerability-service osv`; Python and JavaScript CycloneDX SBOMs. Native
frontend checks, installed-wheel browser tests and installation/recovery jobs
used the exact workflow's immutable image/source inputs. The Windows full-suite
command additionally used `-x --tb=short --durations=25` and a JUnit artifact.
CI's complete logs and commands remain attached to run 40714695972.

Host operations used the exact shipped administrative `preflight`, `stage`,
`install`, `stop` and `backup` entries with the immutable artifact directory.
The one interrupted cold installation resumed from its recorded phase. Real
backup/restore/status used the manifest-bound `platform_backup.py` jobs. The
additional request/frontend and encrypted configuration checks used unused
isolated destinations and the same verified image. No developer tooling was
installed into the host Python or production runtime image.

Skeptical review and the deliberate second pass covered authorization, target and
artifact binding, restrictive defaults, web/gateway mounts, STOP/queue identity,
independent keys, encrypted/SQLite backup, restore fencing, retained configuration,
schema compatibility and rollback. No unresolved blocking finding remains for the
bounded DATA_ONLY scope. Financial qualification remains restricted below.

Recover using the retained exact image, encrypted generations and configuration
checkpoint, keeping primary/recovery fencing and separately reconciling any future
financial authority. For withdrawal, stop only the dedicated gateway/web while
retaining state, keys, backups and the worker fence. There is no previous installed
financial schema to downgrade and no financial allowance to refund.

Temporary browser/tooling containers and the two task-created browser images were
removed. Task QA wheels, test trees, synthetic state and duplicate partial-copy
reference directory were removed; original private reference/final artifacts,
receipts, probe scripts, screenshots, recovery keys and ciphertext remain. The
task-only local integration branch was deleted after its commit was verified as
an ancestor of `main`. Delivery/dependency branches remain retained. Unrelated
`3x-ui` service/container remained running. No model polling, source campaign,
external alert delivery or D2 work is left running.

## Verdicts and next boundary

| Area | Verdict | Evidence / boundary |
|---|---|---|
| Integration | PASS | #229, #230 and #233 actually merged through required gates |
| Engineering | PASS | Exact-main CI and reused accepted unchanged inputs; configured skips disclosed |
| Immutable artifact | PASS | Manifest/archive/BUILD_COMMIT, Git-bound wheel, both image IDs and bundle verified |
| Deployment | PASS | Actual Helsinki private HTTPS, exact artifact, DATA_ONLY and worker fenced |
| Identity and isolation | PASS | Pinned SSH, explicit TLS trust, operator/reader/anonymous boundaries and least-privilege mounts |
| Financial custody | BLOCKED | No real financial authority/custody commissioned; synthetic process mechanics passed |
| Backup/restore | PASS | Current unconfigured installation and exact STOP identity; independent encrypted configuration verified |
| Real financial recovery | NOT_PERFORMED | No real journal/witness/custody, allowance or inventory exists in this installation |
| Alert delivery | NOT_PERFORMED | `ALERT_DELIVERY_NOT_COMMISSIONED`; no exact external destination authorization |
| Real-data/account qualification | BLOCKED | Missing approved bounded source/account read inputs and numeric authority; no reads performed |
| Human acceptance | NOT_PERFORMED | Automated browser evidence only; no participant feedback |
| DATA_ONLY operational qualification | PASS | Actual role/access/restart/recovery checks and 601.379-second host observation |
| Financial/Live operational qualification | BLOCKED | D1 does not authorize issuance, trading or D2 |

Financial execution remained fenced throughout. Research/source acquisition,
authenticated venue/account reads, financial authority issuance and financial
account mutation were not performed. No existing financial STOP was cleared and
no allowance was issued, reset or reconstructed from a fixture. Synthetic
consumption evidence is separate from real installation authority.

`ALERT_DELIVERY_NOT_COMMISSIONED`: D1 excludes an external alert delivery without
a separately approved exact destination. Real-data/account qualification lacks
an approved bounded workload, artifact, window and numeric caps. Human/operator
acceptance has no participant receipt. These remain separate qualifications.

A later D2 proposal must bind the immutable source/tree, image/archive/package,
bundle, configuration and operational receipts in this record. It additionally
requires the owner’s exact accounts, instruments/routes, capital and order caps,
window/duration/loss/attempt/request/resource limits, source/account read budget
and qualification, signer references, signed version-2 authority, opening and
reconciliation proof, independent custody/supervision/recovery qualification,
alert destination approval and human feedback. D1 selects none of those financial
inputs and does not activate D2 or Live.
