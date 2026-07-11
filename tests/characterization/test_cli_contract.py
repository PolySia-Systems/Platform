import typer

from polysia import cli
from polysia.cli_support import (
    apply_secure_env_from_settings,
    safe_open_order_to_dict,
    safe_order_response,
)

EXPECTED_COMMANDS = {
    "acceptance-audit",
    "backtest-jsonl",
    "controlled-second-tiny-live",
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
    "release-manifest",
    "shadow-run",
    "shadow-run-real-data",
    "strategy-evaluation",
    "strategy-evaluation-extended",
    "stream-market",
    "tiny-live-execute",
    "tiny-live-monitor",
    "tiny-live-readiness",
}


def test_cli_command_inventory_is_preserved() -> None:
    command = typer.main.get_command(cli.app)

    assert set(command.commands) == EXPECTED_COMMANDS


def test_legacy_cli_helper_imports_delegate_to_support_modules() -> None:
    assert cli._apply_secure_env_from_settings is apply_secure_env_from_settings
    assert cli._safe_open_order_to_dict is safe_open_order_to_dict
    assert cli._safe_order_response is safe_order_response
