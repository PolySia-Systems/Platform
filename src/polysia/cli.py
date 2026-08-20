from __future__ import annotations

import typer

from polysia.cli_commands import core, live, operations, research
from polysia.control.cli import control_app

app = typer.Typer(
    help="PolySia — Polymarket-first trading platform.",
    no_args_is_help=True,
)
app.add_typer(control_app, name="control")


@app.callback()
def main() -> None:
    """Run polysia commands."""


app.command("health")(core.health)
app.command("configuration-status")(core.configuration_status)
app.command("operator-status")(operations.operator_status)
app.command("operator-report")(operations.operator_report)
app.command("deployment-readiness")(operations.deployment_readiness)
app.command("operator-runbook")(operations.operator_runbook)
app.command("release-manifest")(operations.release_manifest)
app.command("deployment-automation")(operations.deployment_automation)
app.command("final-handoff")(operations.final_handoff)
app.command("acceptance-audit")(operations.acceptance_audit)
app.command("production-gap-audit")(operations.production_gap_audit)
app.command("main-merge-review")(operations.main_merge_review)
app.command("local-release-closeout")(operations.local_release_closeout)
app.command("reconcile-account")(operations.reconcile_account)
app.command("shadow-run")(research.shadow_run)
app.command("shadow-run-real-data")(research.shadow_run_real_data)
app.command("strategy-evaluation")(research.strategy_evaluation)
app.command("strategy-evaluation-extended")(research.strategy_evaluation_extended)
app.command("fill-simulation-audit")(research.fill_simulation_audit)
app.command("tiny-live-readiness")(operations.tiny_live_readiness)
app.command("discover-markets")(core.discover_markets)
app.command("stream-market")(core.stream_market)
app.command("paper-trade")(core.paper_trade)
app.command("backtest-jsonl")(core.backtest_jsonl)
app.command("live-open-orders")(live.live_open_orders)
app.command("live-account-status")(live.live_account_status)
app.command("live-cancel-order")(live.live_cancel_order)
app.command("live-cancel-market-orders")(live.live_cancel_market_orders)
app.command("live-smoke-test")(live.live_smoke_test)
app.command("tiny-live-execute")(live.tiny_live_execute)
app.command("tiny-live-round-trip")(live.tiny_live_round_trip)
app.command("tiny-live-copy")(live.tiny_live_copy)
app.command("post-live-reconciliation")(operations.post_live_reconciliation)
app.command("reconcile-live-round-trip")(operations.reconcile_live_round_trip_command)
app.command("monitor-live-round-trip")(operations.monitor_live_round_trip_command)
app.command("observability-snapshot")(operations.observability_snapshot)
app.command("tiny-live-monitor")(operations.tiny_live_monitor)
app.command("controlled-second-tiny-live")(live.controlled_second_tiny_live)
app.command("manual-intervention-live-test")(live.manual_intervention_live_test)
app.command("live-limit-order")(live.live_limit_order)


if __name__ == "__main__":
    app()
