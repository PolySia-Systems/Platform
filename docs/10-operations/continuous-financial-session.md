# Continuous financial session: preparation and gated commissioning

Date: 2026-10-25. Status: engineering preparation, not deployment or Live authority.
The [proposed decision](../04-architecture/adrs/ADR-0023-bounded-financial-session.md)
and [requirements](../03-requirements/continuous-financial-session.md) own the
new contract. Existing [delivery/rollback](delivery-and-rollback.md) and
[installation](independent-platform-shadow.md) remain the operational entrances.

## Immutable prerequisites and handoff

1. Resolve release-blocking findings; obtain protected integration authorization.
   Record exact integrated main SHA and policy-required native CI receipts.
2. Produce the full exact-main release matrix, source-bound wheel/image/artifact
   digests and release manifest. A local Windows/Python 3.14.7 run is not an
   exact Python 3.14.8 release receipt. Do not relabel historical v0.4.0 evidence.
3. Accept ADR-0023 before composing a continuous Live supervisor. Retain the
   DATA_ONLY worker and browser isolation. Bind one account and eligible host to
   one trusted witness root; the second host remains fenced.
4. Verify the owner receipt against the exact envelope and artifact/config/policy
   identities. Freeze actual limits from measurements and an explicit run
   decision. No candidate count, test fixture or historical Tiny Live limit is
   inherited permission. No authority file has been issued by this engineering.
5. Supply a complete exact-account reader to LiveSessionExecution, plus bounded
   request/cost estimates for ACCOUNT, SUBMIT, CANCEL and CANCELLATION_READ,
   including all underlying requests. Map current venue identifiers, collateral
   and settlement routes; verify occurrence identity, paging completeness and
   finality. Missing source occurrence or account/fee evidence blocks entries.
6. Commission independent mandatory supervision, persistent STOP and restricted
   witness/checkpoint custody. Provision only a fresh explicitly approved empty
   account baseline. Nonempty inventory needs an assessed migration.
7. Perform separately authorized disabled installation and bounded non-Live
   qualification. Record actual route/IP/signer ownership, latency/freshness,
   resource budgets and cohort viability. Acquire no provider by implication.
8. Obtain a separate run-specific Live authorization before any account read or
   mutation under that run. No canary, 72-hour observation or financial action
   is authorized by this document or by the engineering PR.

No new CLI command signs, provisions, resumes or deploys this session. The
library boundary is concrete and tested; operational receipt verification,
account/source wiring and supervisor commissioning must be reviewed together
with the accepted decision and authorized installation. Do not add an arbitrary
Console command as a shortcut. A trusted publisher passes only
`financial_session_view` and `SharedCohortSelection.to_console_dict()` snapshots
to the retained Console publication; web code receives no financial-store path.

## Recovery and incidents

STOP/kill denies mutations. DRAIN prevents new entries; it does not itself grant
exits. Entry expiry permits only separately scoped protective actions, before
their own deadline and with all venue/account/Risk/supervision checks intact.
Redemption, approval and transfer require separate authority. If closure is
ineligible, retain evidence and report the incident; do not bypass restrictions.

Preserve the private financial file, witness and externally retained checkpoint.
On restart require the exact envelope and checkpoint; refresh independent
supervision and reconcile complete cash/positions/orders/fees before explicitly
resuming entries. An uncertain submission retains attempt and reservation until
authoritative reconciliation; never retry a submission because a timeout,
empty page or 404 looks like failure. A cancellation ACK remains pending until
the existing bounded finality gate and fee-aware account evidence agree.

The witness is excluded from ordinary financial backup restore. Restoring the
financial database alone against an advanced witness is rejected. Restore of
both files and external checkpoint control cannot be detected by a purely local
process; it is prohibited as automatic recovery and needs an independent owner
reconciliation decision. Never run two hosts with copied signer/authority state.

Rollback stops the new composition and chooses retained compatible code. Keep
STOP, consumed authority and both state files. There is no database downgrade,
counter reset, automatic schema migration or automatic wider cohort.

## Goldsky value gate: DEFER

Current official documentation was checked on 2026-10-25. Goldsky provides
managed indexing/query/streaming capabilities, and Polymarket lists it as a data
resource. That establishes neither a usable endpoint/schema nor measured
incremental coverage for this account/cohort. Third-party schemas may lag venue
contracts. No account, subscription, endpoint probe, acquisition or integration
is authorized or performed here. The first two-source slice does not require it.

A later authorized bounded experiment must freeze: common chain/contract/schema
versions, exact cohort/window, canonical transaction/occurrence keys, venue
collateral/settlement-route compatibility, pagination/cursor start/end and
history completeness, finality/reorg handling, timestamp/clock quality and
request/byte/storage/cost ceilings. Retain every exclusion and missing interval.

Compare native/PolyCop overlap and exclusive usable observations on the same
window, earliest attributable delivery and delay distributions, confirmed-event
coverage, follower-size/exit feasibility and source-removal replay. Label replay
counterfactual. Record request/storage/infrastructure costs separately from
actual trade cashflow. Report terms/access constraints and provider quotes with
their dates. Predeclare minimum useful exclusive coverage, freshness and
cost-benefit thresholds before acquisition; no post-hoc threshold selection.

Decision choices: ADD only with demonstrated marginal value and authority;
LIMITED_USE for a bounded proven role; REJECT for incompatible contracts or
negative value; otherwise DEFER. Missing evidence now: approved access/budget,
current endpoint-specific schema/contract coverage and terms, overlapping raw
observations, finality/history/cursor completeness, usable attribution,
latency/resource/cost measurements and frozen acceptance thresholds.

Official references:

- [Polymarket order lifecycle](https://docs.polymarket.com/concepts/order-lifecycle)
- [IP limits and separate signer limits](https://docs.polymarket.com/api-reference/rate-limits)
- [Data resources and schema caveat](https://docs.polymarket.com/resources/blockchain-data)
- [Geographic restrictions](https://docs.polymarket.com/api-reference/geoblock)
- [Authenticated account order stream](https://docs.polymarket.com/trading/realtime-order-updates)
- [Goldsky managed product overview](https://docs.goldsky.com/introduction)
- [Goldsky subgraph contract family](https://docs.goldsky.com/subgraphs/introduction)

## Performance and acceptance reporting

The existing request scheduler remains instance-local. The session's durable
budget covers its configured financial port calls; it does not establish a
global IP budget for unrelated processes. Actual installed worker sharing and
IP/signer tiers require the separately authorized host inspection. Native
diagnostic cap 10 and software cohort envelope 40 remain software facts, not
vendor limits or observed capacity. Discovery-row fixture tests do not measure
hot subscriptions. No new broker, database service or language is introduced.

Use monotonic local stage durations and source UTC clock-quality flags. Missing
and restart-censored spans stay unknown. Existing latency-intelligence policy
requires 20/100/1,000 samples for P50/P95/P99 respectively. No credible production
percentile or 99% supervision claim exists from deterministic fixtures. Report
queue pressure, expiry and resource costs with explicit windows/denominators;
do not infer low pressure merely from absence of 429s.

The PR must distinguish ENGINEERING_VERIFIED/OPEN, INTEGRATION_PENDING,
DEPLOYMENT_NOT_PERFORMED, LIVE_NOT_AUTHORIZED and ECONOMICS_NOT_OBSERVED.
Human operator acceptance, host performance and sustained economic observation
remain separate receipts. No removal of legacy working behavior is required;
only proven unreachable task-owned code may be retired with compatibility proof.
