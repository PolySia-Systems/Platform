"""Bounded allowlisted human views of already redacted publisher evidence."""

from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any

from polysia.monitoring.capabilities import CAPABILITIES
from polysia.monitoring.console_contract import (
    Component,
    EvidenceSection,
    EvidenceTable,
    Fact,
    Workspace,
)
from polysia.monitoring.console_projection import ConsoleReadModel, component


def obj(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def rows(value: Any) -> list[dict[str, Any]]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


NON_FINANCIAL_METRICS = frozenset({"age_seconds", "p50_ns", "p95_ns", "p99_ns"})


def text(value: Any, *, metric: bool = False) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "YES" if value else "NO"
    if isinstance(value, (str, int)):
        return str(value) if len(str(value)) <= 2048 else "UNKNOWN_OVERSIZED_VALUE"
    if metric and isinstance(value, float) and isfinite(value):
        return str(value)
    if isinstance(value, list):
        return "; ".join(filter(None, (text(item) for item in value[:30])))[:2048] or None
    return None


def facts(raw: Any, fields: str) -> list[Fact]:
    result = []
    for path in fields.split():
        value = raw
        for part in path.split("."):
            value = obj(value).get(part)
        result.append(
            Fact(
                label=path.replace("_", " ").replace(".", " / "),
                value=text(value, metric=path in NON_FINANCIAL_METRICS),
            )
        )
    return result


def table(title: str, records: Any, fields: str) -> EvidenceTable:
    items = rows(records)
    keys = fields.split()
    return EvidenceTable(
        title=title,
        columns=[key.replace("_", " ") for key in keys],
        rows=[
            [text(row.get(key), metric=key in NON_FINANCIAL_METRICS) for key in keys]
            for row in items[:100]
        ],
        total=len(records) if isinstance(records, list) else None,
        state="UNAVAILABLE"
        if not isinstance(records, list)
        else "EMPTY"
        if not records
        else "PARTIAL"
        if len(items) != len(records)
        else "AVAILABLE",
    )


def workspace(model: ConsoleReadModel, panel: str, now: datetime) -> Workspace:
    if panel not in {"operate", "evaluate", "system"}:
        raise ValueError("unknown_workspace")
    raw, sections = model.publication, []

    def add(
        title: str,
        evidence: Any,
        fields: str,
        guidance: str,
        tables: list[EvidenceTable] | None = None,
        *,
        dated: Any = None,
        validity: Component | None = None,
    ) -> None:
        source = obj(evidence)
        meta = (
            validity
            if validity is not None
            else component(
                "publication",
                obj(dated) or source or None,
                now=now,
                generation=model.generation,
                scope=model.scope,
            )
        )
        if validity is None and source and meta.state == "INCOMPATIBLE":
            # A publication cutoff qualifies undated subviews; it never renews them.
            meta = component(
                "publication", raw, now=now, generation=model.generation, scope=model.scope
            )
            meta = meta.model_copy(update={"state": "PARTIAL", "reason": "subview_time_unknown"})
        sections.append(
            EvidenceSection(
                title=title,
                validity=meta,
                facts=facts(source, fields),
                tables=tables or [],
                guidance=guidance,
            )
        )

    financial = obj(raw.get("financial_session"))
    if panel == "operate":
        policy = obj(raw.get("copy_policy"))
        add(
            "Effective and staged policy",
            policy,
            "digest effective.version effective.sizing effective.exit_preset "
            "effective.reentry staged.version",
            "Existing positions retain their frozen policy. Only registered Shadow "
            "templates can be staged here. "
            "Full financial policy authoring and financial authority issuance are deferred.",
        )
        lab = obj(raw.get("shadow_lab"))
        add(
            "Bounded Shadow Lab",
            lab,
            "virtual_capital financial_authority published_at",
            "Create or clone a registered slot, then preview its exact lifecycle operation. "
            "Each experiment has independent virtual capital; returns must not be summed.",
            [
                table(
                    "Experiments",
                    lab.get("experiments"),
                    "target phase policy_digest selection_digest experiment_id updated_at",
                ),
                table(
                    "Registered policy templates",
                    lab.get("policies"),
                    "digest version capital unit cohort window cost_model",
                ),
            ],
        )
        add(
            "Acquisition authority",
            raw,
            "status next_action authority_window.expires_at "
            "authority_window.maximum_requests authority_window.maximum_bytes "
            "authority.requests_charged authority.bytes_charged",
            "STOP acquisition halts source work; it does not stop a financial worker "
            "or settle positions. "
            "Financial drain blocks entries while permitted protection continues. "
            "Financial STOP can halt automatic exits; exposure may remain.",
        )
    elif panel == "evaluate":
        report = obj(raw.get("report"))
        analytical = obj(report.get("analytical"))
        measured = obj(analytical.get("report"))
        count = measured.get("evaluated_observations")
        measured_result = type(count) is int and count > 0
        state = obj(analytical.get("selected_window")) or obj(analytical.get("financial_state"))
        comparisons = []
        for key in (
            "opening_cash",
            "closing_cash",
            "realized_before_fees",
            "unrealized_after_hypothetical_exit_fees",
            "recorded_fees",
            "hypothetical_exit_fees",
            "fill_embedded_slippage",
            "net_result",
            "operating_costs",
        ):
            comparisons.append(
                {
                    "measure": key,
                    "control": obj(state.get("control")).get(key)
                    if measured_result or key != "net_result"
                    else None,
                    "target": obj(state.get("target")).get(key)
                    if measured_result or key != "net_result"
                    else None,
                }
            )
        add(
            "Same-tape Shadow comparison",
            {
                **report,
                "evidence_status": "RETAINED_SIMULATION"
                if measured_result
                else "NO_MEASURABLE_RESULT",
                "currency": report.get("currency") or analytical.get("currency"),
            },
            "evidence_status currency scope analytical_digest",
            "Paper/replay results are separate from actual trading. Compare fixed "
            "cohort, capital, window and cost assumptions. "
            "Incomplete marks and censored samples remain unknown; automation is not "
            "human acceptance.",
            [table("Independent virtual results", comparisons, "measure control target")],
        )
        add(
            "Sample and confidence",
            measured,
            "evaluated_observations total_observations unknown_observations "
            "control_target_net_delta "
            "confidence_interval sample_confidence censored_observations",
            "Absent confidence and sample evidence is UNKNOWN, not an accuracy estimate. "
            "No retained series means no trend chart. Source-removal replay is "
            "counterfactual, not causal profit.",
        )
        actual_economics = obj(financial.get("economics"))
        actual_economics = {
            **actual_economics,
            "currency": obj(financial.get("identity")).get("currency"),
        }
        if obj(financial.get("exposure")).get("reconciliation") != "MATCHED":
            actual_economics = {
                **actual_economics,
                "status": "UNKNOWN_RECONCILIATION_BLOCKED",
                **{
                    name: None
                    for name in ("cash", "net_pnl", "realized_pnl", "unrealized_pnl", "drawdown")
                },
            }
        add(
            "Actual trading economics",
            actual_economics,
            "status currency realized_pnl unrealized_pnl fees known_accounted_fees "
            "net_pnl cash drawdown "
            "drawdown_samples incomplete_valuations censored_orders valuation_method "
            "valued_at provider_cost infrastructure_cost source_value",
            "Exact retained values; no browser totals. Provider and infrastructure "
            "costs are separate. "
            "Actual fill prices already contain spread/slippage; do not charge it twice.",
            # Reuse account/scope/mode/reconciliation qualification and its
            # earliest deadline; a publication alone cannot renew economics.
            validity=model.financial(now)[1],
        )
        source = obj(raw.get("selection"))
        add(
            "Source value and evidence limits",
            source,
            "monitored_count source_value.summary source_value.overlap_count "
            "source_value.exclusive_coverage",
            "Shared source selection feeds all experiments. Goldsky is DEFERRED. "
            "Missing usable coverage and costs remain UNKNOWN.",
            [
                table(
                    "Report limitations",
                    [{"limitation": value} for value in report.get("limitations", [])]
                    if isinstance(report.get("limitations", []), list)
                    else [],
                    "limitation",
                )
            ],
        )
    else:
        capabilities = obj(raw.get("capabilities"))
        normalized = []
        requirements = []
        for item in rows(capabilities.get("capabilities"))[:50]:
            blockers = []
            required_names = CAPABILITIES.get(str(item.get("capability")), ((), ()))[0]
            seen = set()
            for requirement in rows(item.get("requirements"))[:50]:
                evidence = obj(requirement.get("evidence"))
                requirement_state = requirement.get("state", "UNKNOWN")
                if requirement_state == "VERIFIED":
                    try:
                        at = datetime.fromisoformat(evidence["observed_at"])
                        end = datetime.fromisoformat(evidence["expires_at"])
                        if at > now or end <= now or at.utcoffset() != now.utcoffset():
                            requirement_state = "EXPIRED"
                        if model.scope.run is None or evidence.get("scope") != model.scope.run:
                            requirement_state = "UNKNOWN"
                    except ValueError, TypeError, KeyError:
                        requirement_state = "UNKNOWN"
                required = requirement.get("identity") in required_names
                seen.add(str(requirement.get("identity")))
                if required and requirement_state != "VERIFIED":
                    blockers.append(str(requirement.get("identity")))
                requirements.append(
                    {
                        "capability": item.get("capability"),
                        "requirement": requirement.get("identity"),
                        "state": requirement_state,
                        "reason": evidence.get("reason"),
                        "next_action": evidence.get("next_action"),
                        "expires_at": evidence.get("expires_at"),
                    }
                )
            status = item.get("status", "UNKNOWN")
            blockers.extend(sorted(set(required_names) - seen))
            if str(item.get("capability")) not in CAPABILITIES or status not in (
                "READY",
                "BLOCKED",
                "UNKNOWN",
                "DISABLED",
                "DEGRADED",
            ):
                status = "UNKNOWN"
            if status != "DISABLED" and blockers:
                status = "BLOCKED"
            normalized.append(
                {"capability": item.get("capability"), "status": status, "blockers": blockers}
            )
        add(
            "Configured, verified and authorized",
            capabilities,
            "version observed_at",
            "Configuration, current verification and run-specific authorization are "
            "separate facts. "
            "A healthy browser never establishes financial readiness.",
            [
                table("Capability admission", normalized, "capability status blockers"),
                table(
                    "Prerequisites and next owner action",
                    requirements,
                    "capability requirement state reason next_action expires_at",
                ),
                table(
                    "How to obtain evidence",
                    capabilities.get("catalog"),
                    "identity obtain validate",
                ),
            ],
        )
        add(
            "Exact account verification",
            raw.get("active_account"),
            "identity status observed_at",
            "Revocation, identity or configuration changes invalidate old run "
            "authority. Credential values are never served.",
        )
        add(
            "Installed release and compatibility",
            raw,
            "package_version release_commit publisher_release_commit "
            "installation.version installation.profile status published_at last_attempt",
            "UI/API compatibility is checked independently against this installed "
            "bundle. Runtime uses Python; no Node or dev server.",
        )
        capacity = obj(raw.get("capacity"))
        add(
            "Source capacity and timing",
            capacity,
            "allocation actual_requests measured_response_bytes queue_depth "
            'queue_limit unknown_response_count unknown_transport_invocations '
            'external_shared_egress_utilization',
            "Observed bounded capacity is not production qualification. Shared "
            "egress and host resource limits need separate commissioning.",
            [
                table(
                    "Source health",
                    financial.get("sources") or obj(raw.get("selection")).get("source_health"),
                    "source source_id status phase age_seconds gaps next_action",
                ),
                table(
                    "Reserved request bounds",
                    [
                        dict(port=key, **obj(value))
                        for key, value in obj(capacity.get("reserved_port_bounds")).items()
                    ],
                    "port requests response_bytes source_cost",
                ),
            ],
        )
        add(
            "Latency and coverage",
            financial.get("latency"),
            "bottleneck sample_count missing_count censored_count clock_quality",
            "Missing timing samples and coverage remain UNKNOWN. Synthetic probes do "
            "not prove production throughput.",
            dated=financial,
            tables=[
                table(
                    "Latency percentiles (ns)",
                    obj(financial.get("latency")).get("stages"),
                    "stage p50_ns p95_ns p99_ns sample_count missing_count censored_count",
                )
            ],
        )
        backup = obj(raw.get("backup"))
        health = obj(raw.get("backup_health"))
        add(
            "Financial backup and independent restore",
            backup or health,
            "mode last_verified_at independent_restore backup.status "
            "backup.checked_at restore.status",
            "A missing or stale independent restore blocks financial readiness. "
            "Configure protected destinations through the administrative CLI.",
        )
        add(
            "Incidents and notification delivery",
            raw,
            "status next_action",
            "Incident state is distinct from delivery. No delivery receipt means no "
            "notification claim.",
            [
                table(
                    "Operational incidents",
                    raw.get("incidents"),
                    "kind scope reason next_action delivery_state",
                ),
                table(
                    "Financial incidents", financial.get("incidents"), "reason scope at next_action"
                ),
            ],
        )
    result = Workspace(generation=model.generation, sections=sections)
    if len(result.model_dump_json().encode()) > 220_000:
        raise ValueError("workspace_size_limit")
    return result
