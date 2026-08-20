from __future__ import annotations

from collections.abc import Callable

import typer

from polysia.cli_commands import core, live, operations, research
from polysia.control.cli import control_app

app = typer.Typer(
    help="PolySia — Polymarket-first trading platform.",
    no_args_is_help=True,
)
system_app = typer.Typer(help="Inspect local system and operator state.", no_args_is_help=True)
market_app = typer.Typer(help="Discover and stream venue market data.", no_args_is_help=True)
research_app = typer.Typer(
    help="Run non-Live research and evaluation workflows.",
    no_args_is_help=True,
)
ops_app = typer.Typer(
    help="Run operational evidence and reconciliation workflows.",
    no_args_is_help=True,
)
live_app = typer.Typer(help="Run explicitly gated Live account workflows.", no_args_is_help=True)

app.add_typer(system_app, name="system")
app.add_typer(market_app, name="market")
app.add_typer(research_app, name="research")
app.add_typer(ops_app, name="ops")
app.add_typer(control_app, name="control")
app.add_typer(live_app, name="live")


@app.callback()
def main() -> None:
    """Run polysia commands."""


system_app.command("health")(core.health)
system_app.command("configuration")(core.configuration_status)
system_app.command("status")(operations.operator_status)
system_app.command("report")(operations.operator_report)
system_app.command("runbook")(operations.operator_runbook)
system_app.command("observability")(operations.observability_snapshot)

market_app.command("discover")(core.discover_markets)
market_app.command("stream")(core.stream_market)

research_app.command("paper-trade")(core.paper_trade)
research_app.command("backtest")(core.backtest_jsonl)
research_app.command("shadow")(research.shadow_run)
research_app.command("shadow-public")(research.shadow_run_real_data)
research_app.command("evaluate")(research.strategy_evaluation)
research_app.command("evaluate-extended")(research.strategy_evaluation_extended)
research_app.command("fill-audit")(research.fill_simulation_audit)

ops_app.command("deployment-readiness")(operations.deployment_readiness)
ops_app.command("release-manifest")(operations.release_manifest)
ops_app.command("deployment-automation")(operations.deployment_automation)
ops_app.command("final-handoff")(operations.final_handoff)
ops_app.command("acceptance-audit")(operations.acceptance_audit)
ops_app.command("production-gap-audit")(operations.production_gap_audit)
ops_app.command("main-merge-review")(operations.main_merge_review)
ops_app.command("local-release-closeout")(operations.local_release_closeout)
ops_app.command("reconcile-account")(operations.reconcile_account)
ops_app.command("post-live-reconciliation")(operations.post_live_reconciliation)
ops_app.command("reconcile-live-round-trip")(operations.reconcile_live_round_trip_command)
ops_app.command("monitor-live-round-trip")(operations.monitor_live_round_trip_command)
ops_app.command("tiny-live-monitor")(operations.tiny_live_monitor)

live_app.command("readiness")(operations.tiny_live_readiness)
live_app.command("open-orders")(live.live_open_orders)
live_app.command("account-status")(live.live_account_status)
live_app.command("cancel-order")(live.live_cancel_order)
live_app.command("cancel-market-orders")(live.live_cancel_market_orders)
live_app.command("smoke-test")(live.live_smoke_test)
live_app.command("tiny-execute")(live.tiny_live_execute)
live_app.command("tiny-round-trip")(live.tiny_live_round_trip)
live_app.command("tiny-copy")(live.tiny_live_copy)
live_app.command("controlled-second-attempt")(live.controlled_second_tiny_live)
live_app.command("manual-intervention-test")(live.manual_intervention_live_test)
live_app.command("limit-order")(live.live_limit_order)


LEGACY_ALIAS_REMOVAL_CONDITION = (
    "Remove after a post-v0.2.0 owner-approved breaking-change review proves that the "
    "controlled server and every tracked consumer use namespaced commands."
)
LEGACY_COMMAND_ALIASES: dict[str, Callable[..., object]] = {
    "health": core.health,
    "configuration-status": core.configuration_status,
    "operator-status": operations.operator_status,
    "operator-report": operations.operator_report,
    "deployment-readiness": operations.deployment_readiness,
    "operator-runbook": operations.operator_runbook,
    "release-manifest": operations.release_manifest,
    "deployment-automation": operations.deployment_automation,
    "final-handoff": operations.final_handoff,
    "acceptance-audit": operations.acceptance_audit,
    "production-gap-audit": operations.production_gap_audit,
    "main-merge-review": operations.main_merge_review,
    "local-release-closeout": operations.local_release_closeout,
    "reconcile-account": operations.reconcile_account,
    "shadow-run": research.shadow_run,
    "shadow-run-real-data": research.shadow_run_real_data,
    "strategy-evaluation": research.strategy_evaluation,
    "strategy-evaluation-extended": research.strategy_evaluation_extended,
    "fill-simulation-audit": research.fill_simulation_audit,
    "tiny-live-readiness": operations.tiny_live_readiness,
    "discover-markets": core.discover_markets,
    "stream-market": core.stream_market,
    "paper-trade": core.paper_trade,
    "backtest-jsonl": core.backtest_jsonl,
    "live-open-orders": live.live_open_orders,
    "live-account-status": live.live_account_status,
    "live-cancel-order": live.live_cancel_order,
    "live-cancel-market-orders": live.live_cancel_market_orders,
    "live-smoke-test": live.live_smoke_test,
    "tiny-live-execute": live.tiny_live_execute,
    "tiny-live-round-trip": live.tiny_live_round_trip,
    "tiny-live-copy": live.tiny_live_copy,
    "post-live-reconciliation": operations.post_live_reconciliation,
    "reconcile-live-round-trip": operations.reconcile_live_round_trip_command,
    "monitor-live-round-trip": operations.monitor_live_round_trip_command,
    "observability-snapshot": operations.observability_snapshot,
    "tiny-live-monitor": operations.tiny_live_monitor,
    "controlled-second-tiny-live": live.controlled_second_tiny_live,
    "manual-intervention-live-test": live.manual_intervention_live_test,
    "live-limit-order": live.live_limit_order,
}

for legacy_name, callback in LEGACY_COMMAND_ALIASES.items():
    app.command(legacy_name, hidden=True)(callback)


if __name__ == "__main__":
    app()
