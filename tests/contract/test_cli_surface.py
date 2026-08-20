import inspect

import typer

from polysia import cli
from polysia.cli_commands import core, live, operations, research

EXPECTED_COMMANDS = {
    "acceptance-audit",
    "backtest-jsonl",
    "controlled-second-tiny-live",
    "configuration-status",
    "control",
    "deployment-automation",
    "deployment-readiness",
    "discover-markets",
    "fill-simulation-audit",
    "final-handoff",
    "health",
    "live-account-status",
    "live-cancel-market-orders",
    "live-cancel-order",
    "live-limit-order",
    "live-open-orders",
    "live-smoke-test",
    "local-release-closeout",
    "main-merge-review",
    "manual-intervention-live-test",
    "observability-snapshot",
    "operator-report",
    "operator-runbook",
    "operator-status",
    "paper-trade",
    "post-live-reconciliation",
    "production-gap-audit",
    "reconcile-account",
    "reconcile-live-round-trip",
    "monitor-live-round-trip",
    "release-manifest",
    "shadow-run",
    "shadow-run-real-data",
    "strategy-evaluation",
    "strategy-evaluation-extended",
    "stream-market",
    "tiny-live-copy",
    "tiny-live-execute",
    "tiny-live-monitor",
    "tiny-live-round-trip",
    "tiny-live-readiness",
}


def test_cli_command_inventory_is_preserved() -> None:
    command = typer.main.get_command(cli.app)

    assert set(command.commands) == EXPECTED_COMMANDS


def test_control_command_inventory_is_bounded() -> None:
    command = typer.main.get_command(cli.app)

    assert set(command.commands["control"].commands) == {"apply", "history", "plan", "status"}


def test_cli_composes_responsibility_owned_commands() -> None:
    command = typer.main.get_command(cli.app)

    assert inspect.unwrap(command.commands["health"].callback) is core.health
    assert (
        inspect.unwrap(command.commands["strategy-evaluation"].callback)
        is research.strategy_evaluation
    )
    assert (
        inspect.unwrap(command.commands["operator-status"].callback)
        is operations.operator_status
    )
    assert (
        inspect.unwrap(command.commands["live-limit-order"].callback)
        is live.live_limit_order
    )


def test_tiny_live_round_trip_command_is_dry_run_by_default() -> None:
    signature = inspect.signature(live.tiny_live_round_trip)

    assert signature.parameters["submit"].default is False
    assert signature.parameters["verified_ci_commit"].default is None
