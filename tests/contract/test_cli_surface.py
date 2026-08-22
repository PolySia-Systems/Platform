import inspect

import typer
from typer.testing import CliRunner

from polysia import cli
from polysia.cli_commands import core, live, operations, research

runner = CliRunner()

EXPECTED_NAMESPACES = {
    "control",
    "live",
    "market",
    "ops",
    "research",
    "system",
    "wallet-intelligence",
}
EXPECTED_COMMANDS = {
    "system": {"configuration", "health", "observability", "report", "runbook", "status"},
    "market": {"discover", "stream"},
    "research": {
        "backtest",
        "evaluate",
        "evaluate-extended",
        "fill-audit",
        "paper-trade",
        "shadow",
        "shadow-public",
    },
    "ops": {
        "acceptance-audit",
        "deployment-automation",
        "deployment-readiness",
        "final-handoff",
        "local-release-closeout",
        "main-merge-review",
        "monitor-live-round-trip",
        "post-live-reconciliation",
        "production-gap-audit",
        "reconcile-account",
        "reconcile-live-round-trip",
        "release-manifest",
        "tiny-live-monitor",
    },
    "control": {"apply", "history", "plan", "status"},
    "wallet-intelligence": {"backup", "ensure", "health", "pool", "restore-check", "sync"},
    "live": {
        "account-status",
        "cancel-market-orders",
        "cancel-order",
        "controlled-second-attempt",
        "limit-order",
        "manual-intervention-test",
        "open-orders",
        "readiness",
        "smoke-test",
        "tiny-copy",
        "tiny-execute",
        "tiny-round-trip",
    },
}
EXPECTED_LEGACY_ALIASES = {
    "health": ("system", "health"),
    "configuration-status": ("system", "configuration"),
    "operator-status": ("system", "status"),
    "operator-report": ("system", "report"),
    "deployment-readiness": ("ops", "deployment-readiness"),
    "operator-runbook": ("system", "runbook"),
    "release-manifest": ("ops", "release-manifest"),
    "deployment-automation": ("ops", "deployment-automation"),
    "final-handoff": ("ops", "final-handoff"),
    "acceptance-audit": ("ops", "acceptance-audit"),
    "production-gap-audit": ("ops", "production-gap-audit"),
    "main-merge-review": ("ops", "main-merge-review"),
    "local-release-closeout": ("ops", "local-release-closeout"),
    "reconcile-account": ("ops", "reconcile-account"),
    "shadow-run": ("research", "shadow"),
    "shadow-run-real-data": ("research", "shadow-public"),
    "strategy-evaluation": ("research", "evaluate"),
    "strategy-evaluation-extended": ("research", "evaluate-extended"),
    "fill-simulation-audit": ("research", "fill-audit"),
    "tiny-live-readiness": ("live", "readiness"),
    "discover-markets": ("market", "discover"),
    "stream-market": ("market", "stream"),
    "paper-trade": ("research", "paper-trade"),
    "backtest-jsonl": ("research", "backtest"),
    "live-open-orders": ("live", "open-orders"),
    "live-account-status": ("live", "account-status"),
    "live-cancel-order": ("live", "cancel-order"),
    "live-cancel-market-orders": ("live", "cancel-market-orders"),
    "live-smoke-test": ("live", "smoke-test"),
    "tiny-live-execute": ("live", "tiny-execute"),
    "tiny-live-round-trip": ("live", "tiny-round-trip"),
    "tiny-live-copy": ("live", "tiny-copy"),
    "post-live-reconciliation": ("ops", "post-live-reconciliation"),
    "reconcile-live-round-trip": ("ops", "reconcile-live-round-trip"),
    "monitor-live-round-trip": ("ops", "monitor-live-round-trip"),
    "observability-snapshot": ("system", "observability"),
    "tiny-live-monitor": ("ops", "tiny-live-monitor"),
    "controlled-second-tiny-live": ("live", "controlled-second-attempt"),
    "manual-intervention-live-test": ("live", "manual-intervention-test"),
    "live-limit-order": ("live", "limit-order"),
}


def test_cli_exposes_capability_namespaces() -> None:
    command = typer.main.get_command(cli.app)

    visible_commands = {name for name, child in command.commands.items() if not child.hidden}
    assert visible_commands == EXPECTED_NAMESPACES
    for namespace, expected in EXPECTED_COMMANDS.items():
        assert set(command.commands[namespace].commands) == expected


def test_root_help_hides_compatibility_aliases() -> None:
    result = runner.invoke(cli.app, ["--help"])

    assert result.exit_code == 0
    for namespace in EXPECTED_NAMESPACES:
        assert namespace in result.stdout
    for legacy_name in EXPECTED_LEGACY_ALIASES:
        assert legacy_name not in result.stdout


def test_flat_compatibility_aliases_are_hidden_and_complete() -> None:
    command = typer.main.get_command(cli.app)

    assert set(cli.LEGACY_COMMAND_ALIASES) == set(EXPECTED_LEGACY_ALIASES)
    assert "post-v0.2.0" in cli.LEGACY_ALIAS_REMOVAL_CONDITION
    assert all(command.commands[name].hidden for name in EXPECTED_LEGACY_ALIASES)


def test_cli_composes_responsibility_owned_commands() -> None:
    command = typer.main.get_command(cli.app)

    assert inspect.unwrap(command.commands["system"].commands["health"].callback) is core.health
    assert (
        inspect.unwrap(command.commands["research"].commands["evaluate"].callback)
        is research.strategy_evaluation
    )
    assert (
        inspect.unwrap(command.commands["system"].commands["status"].callback)
        is operations.operator_status
    )
    assert (
        inspect.unwrap(command.commands["live"].commands["limit-order"].callback)
        is live.live_limit_order
    )


def test_flat_aliases_delegate_to_the_same_callbacks() -> None:
    command = typer.main.get_command(cli.app)

    for legacy_name, (namespace, canonical_name) in EXPECTED_LEGACY_ALIASES.items():
        alias_callback = inspect.unwrap(command.commands[legacy_name].callback)
        canonical_callback = inspect.unwrap(
            command.commands[namespace].commands[canonical_name].callback
        )
        assert alias_callback is canonical_callback
        assert cli.LEGACY_COMMAND_ALIASES[legacy_name] is canonical_callback


def test_flat_aliases_preserve_parameter_contracts() -> None:
    command = typer.main.get_command(cli.app)

    def parameter_contract(child) -> tuple[tuple[object, ...], ...]:
        return tuple(
            (
                type(parameter).__name__,
                parameter.name,
                tuple(getattr(parameter, "opts", ())),
                tuple(getattr(parameter, "secondary_opts", ())),
                parameter.required,
                parameter.default,
                parameter.nargs,
                getattr(parameter, "multiple", False),
                getattr(parameter, "is_flag", False),
            )
            for parameter in child.params
        )

    for legacy_name, (namespace, canonical_name) in EXPECTED_LEGACY_ALIASES.items():
        assert parameter_contract(command.commands[legacy_name]) == parameter_contract(
            command.commands[namespace].commands[canonical_name]
        )


def test_tiny_live_round_trip_command_is_dry_run_by_default() -> None:
    signature = inspect.signature(live.tiny_live_round_trip)

    assert signature.parameters["submit"].default is False
    assert signature.parameters["verified_ci_commit"].default is None
