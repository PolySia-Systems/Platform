from __future__ import annotations

from dataclasses import dataclass

from pm_trader.monitoring.metrics import OperatorStatus
from pm_trader.monitoring.readiness import DeploymentReadinessReport


@dataclass(frozen=True, slots=True)
class OperatorRunbookSection:
    """One operator runbook section."""

    title: str
    objective: str
    commands: tuple[str, ...]
    checks: tuple[str, ...]
    stop_conditions: tuple[str, ...] = ()


def render_operator_runbook_markdown(
    *,
    operator_status: OperatorStatus,
    readiness: DeploymentReadinessReport,
    include_live: bool = False,
) -> str:
    """Render a sanitized operator runbook."""

    sections = _runbook_sections(include_live=include_live)
    status_payload = operator_status.to_dict()
    readiness_payload = readiness.to_dict()
    return "\n".join(
        (
            "# Polymarket Operator Runbook",
            "",
            "This runbook is generated from sanitized runtime checks. It does not include "
            "private keys, wallet addresses, allowlisted token values, or raw live order "
            "responses.",
            "",
            "## Current Gate Status",
            "",
            f"- Operator status: {status_payload['status']}",
            f"- Deployment readiness: {readiness_payload['status']}",
            f"- Tiny live orders ready: {status_payload['tiny_live_orders_ready']}",
            f"- Readiness failures: {_readiness_failure_count(readiness)}",
            f"- Generated at: {status_payload['timestamp']}",
            "",
            *(_render_section(section) for section in sections),
        )
    )


def _runbook_sections(*, include_live: bool) -> tuple[OperatorRunbookSection, ...]:
    sections = [
        OperatorRunbookSection(
            title="1. Start Of Day",
            objective="Confirm the local environment is safe before collecting data.",
            commands=(
                "python -m pm_trader.cli health",
                "python -m pm_trader.cli deployment-readiness",
                "python -m pm_trader.cli operator-status",
            ),
            checks=(
                "health returns status ok",
                "deployment-readiness returns status ready",
                "operator-status does not expose secrets or wallet addresses",
            ),
            stop_conditions=(
                "deployment-readiness is blocked",
                "operator-status reports an unexpected live-ready state",
            ),
        ),
        OperatorRunbookSection(
            title="2. Data Collection",
            objective="Inspect public markets and stream one token without trading.",
            commands=(
                "python -m pm_trader.cli discover-markets --limit 10",
                "python -m pm_trader.cli stream-market --token-id YOUR_TOKEN_ID --max-events 5",
            ),
            checks=(
                "market discovery returns active markets",
                "stream-market prints normalized JSON lines",
            ),
            stop_conditions=(
                "public SDK or websocket errors repeat",
                "received events cannot be normalized",
            ),
        ),
        OperatorRunbookSection(
            title="3. Research Loop",
            objective="Test strategies only through paper trading and replay backtests.",
            commands=(
                "python -m pm_trader.cli paper-trade --token-id YOUR_TOKEN_ID --order-size 1",
                "python -m pm_trader.cli backtest-jsonl --input .\\events.jsonl "
                "--strategy stale-price",
                "python -m pm_trader.cli backtest-jsonl --input .\\events.jsonl "
                "--strategy passive-market-maker --min-edge 0.05",
            ),
            checks=(
                "paper-trade uses the local paper broker",
                "backtests finish without live API calls",
                "fills, positions, and PnL are explainable before any live dry-run",
            ),
            stop_conditions=(
                "risk decisions are unexpected",
                "paper results cannot be reproduced from the same input",
            ),
        ),
        OperatorRunbookSection(
            title="4. Reporting",
            objective="Create a sanitized operator snapshot for review.",
            commands=(
                "python -m pm_trader.cli operator-report --format markdown",
                "python -m pm_trader.cli operator-report --format html "
                "--output .\\operator-report.html",
            ),
            checks=(
                "report includes only configured/not-configured booleans and counts",
                "report does not print secrets, wallet addresses, token values, or hashes",
            ),
        ),
    ]
    if include_live:
        sections.append(
            OperatorRunbookSection(
                title="5. Live Dry-Run Only",
                objective="Preview tiny live operations before any actual submission.",
                commands=(
                    "python -m pm_trader.cli live-open-orders "
                    "--token-id YOUR_TOKEN_ID --i-understand-this-uses-live-account",
                    "python -m pm_trader.cli live-cancel-market-orders "
                    "--token-id YOUR_TOKEN_ID --dry-run "
                    "--i-understand-this-modifies-live-orders",
                    "python -m pm_trader.cli live-limit-order "
                    "--token-id YOUR_TOKEN_ID --side BUY --price 0.01 --size 1 "
                    "--dry-run --i-understand-this-places-real-orders",
                ),
                checks=(
                    "TRADING_MODE is LIVE only when intentionally set by the operator",
                    "LIVE_TRADING_ENABLED is true only for deliberate live testing",
                    "the token is allowlisted and caps remain tiny",
                    "dry-run output shows submitted false",
                ),
                stop_conditions=(
                    "readiness is blocked",
                    "operator-status reports warnings",
                    "any live command would move beyond dry-run before the operator is ready",
                ),
            )
        )
    sections.append(
        OperatorRunbookSection(
            title="Emergency Stop",
            objective="Return the system to a no-live-order state.",
            commands=(
                "Set TRADING_MODE=DATA_ONLY for the active shell or deployment environment.",
                "Set LIVE_TRADING_ENABLED=false for the active shell or deployment environment.",
                "Remove POLYMARKET_LIVE_TOKEN_ALLOWLIST from the active shell or "
                "deployment environment.",
                "Run python -m pm_trader.cli deployment-readiness again.",
            ),
            checks=(
                "deployment-readiness remains ready or clearly explains blocked checks",
                "operator-status reports tiny_live_orders_ready false",
                "no live cancel or submit command is run without explicit acknowledgement",
            ),
            stop_conditions=(
                "environment values cannot be confirmed",
                "open live orders need manual review before cancellation",
            ),
        )
    )
    return tuple(sections)


def _render_section(section: OperatorRunbookSection) -> str:
    return "\n".join(
        (
            f"## {section.title}",
            "",
            section.objective,
            "",
            "### Commands",
            "",
            *(_bullet(command) for command in section.commands),
            "",
            "### Checks",
            "",
            *(_bullet(check) for check in section.checks),
            "",
            "### Stop Conditions",
            "",
            *(_bullet(condition) for condition in section.stop_conditions or ("None",)),
            "",
        )
    )


def _bullet(value: str) -> str:
    return f"- `{value}`" if value.startswith("python ") else f"- {value}"


def _readiness_failure_count(readiness: DeploymentReadinessReport) -> int:
    summary = readiness.to_dict()["summary"]
    if not isinstance(summary, dict):
        raise TypeError("readiness summary must be a dict")
    fail_count = summary.get("fail", 0)
    if not isinstance(fail_count, int):
        raise TypeError("readiness failure count must be an int")
    return fail_count
