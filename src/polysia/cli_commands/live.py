"""Explicitly gated authenticated and Live CLI commands."""

from __future__ import annotations

import asyncio
import json
from datetime import (
    UTC,
    datetime,
)
from decimal import Decimal
from pathlib import Path
from typing import (
    Annotated,
    Literal,
)
from uuid import uuid4

import typer

from polysia import cli_support
from polysia.adapters.polymarket.public import PolymarketPublicAdapterError
from polysia.adapters.polymarket.secure import (
    PolymarketSecureAdapter,
    PolymarketSecureAdapterError,
)
from polysia.cli_commands import core, print_error_and_exit
from polysia.config.settings import (
    AppSettings,
    TradingMode,
)
from polysia.config.structured_logging import configure_logging
from polysia.execution.controlled_second_tiny_live import (
    ControlledSecondTinyLiveConfig,
    controlled_second_tiny_live_filename,
    run_controlled_second_tiny_live,
)
from polysia.execution.intents import OrderIntent
from polysia.execution.live_broker import (
    LiveBroker,
    LiveBrokerError,
)
from polysia.execution.live_smoke_test import (
    LiveSmokeTestConfig,
    run_live_smoke_test,
)
from polysia.execution.manual_intervention_live_test import (
    ManualInterventionLiveTestConfig,
    manual_intervention_live_test_filename,
    run_manual_intervention_live_test,
)
from polysia.execution.tiny_live_copy import (
    TinyLiveCopyConfig,
    run_tiny_live_copy,
)
from polysia.execution.tiny_live_execution import (
    TinyLiveExecutionConfig,
    normalize_tiny_live_execution_formats,
    render_tiny_live_execution,
    run_tiny_live_execution,
    tiny_live_execution_filename,
)
from polysia.execution.tiny_live_round_trip import (
    AUTHORIZATION_ID,
    TinyLiveRoundTripConfig,
    run_tiny_live_round_trip,
)
from polysia.monitoring.tiny_live_round_trip_report import write_tiny_live_round_trip_reports
from polysia.risk.checks import (
    RiskContext,
    RiskEngine,
)
from polysia.risk.limits import RiskLimits


def live_open_orders(
    token_id: Annotated[str | None, typer.Option("--token-id")] = None,
    order_id: Annotated[str | None, typer.Option("--order-id")] = None,
    market: Annotated[str | None, typer.Option("--market")] = None,
    redact_secrets: Annotated[bool, typer.Option("--redact-secrets")] = False,
    i_understand_this_uses_live_account: Annotated[
        bool,
        typer.Option("--i-understand-this-uses-live-account"),
    ] = False,
) -> None:
    """Read authenticated live open orders; never submits or cancels."""
    settings = AppSettings()
    configure_logging(settings)

    try:
        payload = asyncio.run(
            _live_open_orders(
                settings=settings,
                token_id=token_id,
                order_id=order_id,
                market=market,
                i_understand_this_uses_live_account=(
                    i_understand_this_uses_live_account or redact_secrets
                ),
            )
        )
    except (LiveBrokerError, PolymarketSecureAdapterError) as error:
        print_error_and_exit(error)

    typer.echo(json.dumps(payload, sort_keys=True))


def live_account_status(
    redact_secrets: Annotated[bool, typer.Option("--redact-secrets")] = False,
    i_understand_this_uses_live_account: Annotated[
        bool,
        typer.Option("--i-understand-this-uses-live-account"),
    ] = False,
) -> None:
    """Read a sanitized live account status; never submits or cancels."""
    settings = AppSettings()
    configure_logging(settings)

    try:
        payload = asyncio.run(
            _live_account_status(
                settings=settings,
                i_understand_this_uses_live_account=(
                    i_understand_this_uses_live_account or redact_secrets
                ),
            )
        )
    except (LiveBrokerError, PolymarketSecureAdapterError) as error:
        print_error_and_exit(error)

    typer.echo(json.dumps(payload, sort_keys=True))


def live_cancel_order(
    order_id: Annotated[str, typer.Option("--order-id")],
    dry_run: Annotated[bool, typer.Option("--dry-run/--submit")] = True,
    i_understand_this_modifies_live_orders: Annotated[
        bool,
        typer.Option("--i-understand-this-modifies-live-orders"),
    ] = False,
) -> None:
    """Cancel one live order; defaults to dry-run."""
    settings = AppSettings()
    configure_logging(settings)

    try:
        payload = asyncio.run(
            _live_cancel_order(
                settings=settings,
                order_id=order_id,
                dry_run=dry_run,
                i_understand_this_modifies_live_orders=(i_understand_this_modifies_live_orders),
            )
        )
    except (LiveBrokerError, PolymarketSecureAdapterError) as error:
        print_error_and_exit(error)

    typer.echo(json.dumps(payload, sort_keys=True))


def live_cancel_market_orders(
    token_id: Annotated[str, typer.Option("--token-id")],
    dry_run: Annotated[bool, typer.Option("--dry-run/--submit")] = True,
    i_understand_this_modifies_live_orders: Annotated[
        bool,
        typer.Option("--i-understand-this-modifies-live-orders"),
    ] = False,
) -> None:
    """Cancel live orders for one allowlisted token; defaults to dry-run."""
    settings = AppSettings()
    configure_logging(settings)

    try:
        payload = asyncio.run(
            _live_cancel_market_orders(
                settings=settings,
                token_id=token_id,
                dry_run=dry_run,
                i_understand_this_modifies_live_orders=(i_understand_this_modifies_live_orders),
            )
        )
    except (LiveBrokerError, PolymarketSecureAdapterError) as error:
        print_error_and_exit(error)

    typer.echo(json.dumps(payload, sort_keys=True))


def live_smoke_test(
    market_slug: Annotated[str | None, typer.Option("--market-slug")] = None,
    condition_id: Annotated[str | None, typer.Option("--condition-id")] = None,
    token_id: Annotated[str | None, typer.Option("--token-id")] = None,
    outcome: Annotated[str, typer.Option("--outcome", help="YES or NO.")] = "YES",
    side: Annotated[str, typer.Option("--side", help="BUY or SELL.")] = "BUY",
    max_notional: Annotated[str, typer.Option("--max-notional")] = "1.00",
    order_type: Annotated[str, typer.Option("--order-type", help="FAK or FOK.")] = "FAK",
    max_slippage_bps: Annotated[int, typer.Option("--max-slippage-bps", min=0)] = 200,
    dry_run: Annotated[bool, typer.Option("--dry-run/--no-dry-run")] = True,
    require_clean_git: Annotated[bool, typer.Option("--require-clean-git")] = False,
    auto_btc_5m: Annotated[bool, typer.Option("--auto-btc-5m")] = False,
    i_understand_this_places_a_real_order: Annotated[
        bool,
        typer.Option("--i-understand-this-places-a-real-order"),
    ] = False,
) -> None:
    """Run one guarded live connectivity smoke test; defaults to dry-run."""
    settings = AppSettings()
    configure_logging(settings)
    cli_support.apply_secure_env_from_settings(settings)

    try:
        parsed_outcome = cli_support.parse_outcome(outcome)
        selection = asyncio.run(
            core.resolve_live_smoke_selection(
                market_slug=market_slug,
                condition_id=condition_id,
                token_id=token_id,
                outcome=parsed_outcome,
                auto_btc_5m=auto_btc_5m,
            )
        )
        if auto_btc_5m and selection.token_id not in settings.polymarket_live_token_allowlist:
            settings = settings.model_copy(
                update={"polymarket_live_token_allowlist": (selection.token_id,)}
            )
        report = asyncio.run(
            run_live_smoke_test(
                LiveSmokeTestConfig(
                    settings=settings,
                    market_slug=selection.market_slug,
                    condition_id=selection.condition_id,
                    token_id=selection.token_id,
                    outcome=parsed_outcome,
                    side=cli_support.parse_side(side),
                    max_notional=cli_support.parse_decimal(max_notional, "max_notional"),
                    order_type=cli_support.parse_order_type(order_type),
                    max_slippage_bps=max_slippage_bps,
                    dry_run=dry_run,
                    require_clean_git=require_clean_git,
                    acknowledgement=i_understand_this_places_a_real_order,
                    project_root=Path("."),
                )
            )
        )
    except (PolymarketPublicAdapterError, ValueError) as error:
        print_error_and_exit(error)

    payload = {
        "final_result": report.final_result,
        "report_json": "live_smoke_test.json",
        "report_markdown": "live_smoke_test.md",
        "status": "ok" if report.final_result == "PASS" else "blocked",
    }
    typer.echo(json.dumps(payload, sort_keys=True))
    if report.final_result != "PASS":
        raise typer.Exit(code=1)


def tiny_live_execute(
    token_id: Annotated[str, typer.Option("--token-id")],
    side: Annotated[Literal["BUY", "SELL"], typer.Option("--side")],
    outcome: Annotated[Literal["YES", "NO"], typer.Option("--outcome")],
    max_notional: Annotated[str, typer.Option("--max-notional")],
    order_type: Annotated[Literal["FAK", "FOK"], typer.Option("--order-type")],
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Directory for tiny live execution reports."),
    ] = Path("release-artifacts"),
    dry_run: Annotated[bool, typer.Option("--dry-run/--no-dry-run")] = True,
    require_clean_git: Annotated[bool, typer.Option("--require-clean-git")] = False,
    i_understand_this_places_one_real_order: Annotated[
        bool,
        typer.Option("--i-understand-this-places-one-real-order"),
    ] = False,
    market_slug: Annotated[str | None, typer.Option("--market-slug")] = None,
    condition_id: Annotated[str | None, typer.Option("--condition-id")] = None,
    price: Annotated[str | None, typer.Option("--price")] = None,
    redact_secrets: Annotated[
        bool,
        typer.Option("--redact-secrets/--no-redact-secrets"),
    ] = True,
    json_report: Annotated[bool, typer.Option("--json")] = False,
    markdown_report: Annotated[bool, typer.Option("--markdown")] = False,
    html_report: Annotated[bool, typer.Option("--html")] = False,
) -> None:
    """Preview or submit exactly one guarded tiny live FAK/FOK order."""

    settings = AppSettings()
    configure_logging(settings)
    cli_support.apply_secure_env_from_settings(settings)

    try:
        report = asyncio.run(
            run_tiny_live_execution(
                TinyLiveExecutionConfig(
                    settings=settings,
                    token_id=token_id,
                    side=side,
                    outcome=outcome,
                    max_notional=cli_support.parse_decimal(max_notional, "max_notional"),
                    order_type=order_type,
                    output_dir=output_dir,
                    dry_run=dry_run,
                    require_clean_git=require_clean_git,
                    acknowledgement=i_understand_this_places_one_real_order,
                    market_slug=market_slug,
                    condition_id=condition_id,
                    price=cli_support.parse_optional_decimal(price),
                    redact_secrets=redact_secrets,
                    project_root=Path("."),
                )
            )
        )
        formats = normalize_tiny_live_execution_formats(
            json_enabled=json_report,
            markdown_enabled=markdown_report,
            html_enabled=html_report,
        )
    except ValueError as error:
        print_error_and_exit(error)

    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, str] = {}
    for report_format in formats:
        path = output_dir / tiny_live_execution_filename(report_format)
        path.write_text(
            f"{render_tiny_live_execution(report, report_format)}\n",
            encoding="utf-8",
        )
        artifacts[report_format] = str(path)

    payload = {
        "artifacts": artifacts,
        "final_result": report.final_result,
        "live_attempt_count": report.live_attempt_count,
        "order_submitted": report.order_submitted,
        "status": "ok" if not report.blocking_reasons else "blocked",
    }
    typer.echo(json.dumps(payload, sort_keys=True))
    if report.blocking_reasons:
        raise typer.Exit(code=1)


def tiny_live_round_trip(
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Base directory for immutable run evidence."),
    ] = Path("release-artifacts/tiny-live-round-trip"),
    submit: Annotated[
        bool,
        typer.Option("--submit/--dry-run", help="Submit only after every merged-code gate."),
    ] = False,
    acknowledge: Annotated[
        str | None,
        typer.Option("--acknowledge", help=f"Required live acknowledgement: {AUTHORIZATION_ID}"),
    ] = None,
    verified_ci_commit: Annotated[
        str | None,
        typer.Option("--verified-ci-commit", help="Exact green-CI commit required for submit."),
    ] = None,
) -> None:
    """Discover and validate one BTC 15m favorite round trip; dry-run by default."""

    settings = AppSettings()
    configure_logging(settings)
    cli_support.apply_secure_env_from_settings(settings)
    run_id = str(uuid4())
    run_output_dir = output_dir / run_id
    try:
        report = asyncio.run(
            run_tiny_live_round_trip(
                TinyLiveRoundTripConfig(
                    settings=settings,
                    project_root=Path("."),
                    output_dir=run_output_dir,
                    database_path=Path("data/polysia.sqlite3"),
                    dry_run=not submit,
                    acknowledgement=acknowledge == AUTHORIZATION_ID,
                    verified_ci_commit=verified_ci_commit,
                    run_id=run_id,
                )
            )
        )
        artifacts = write_tiny_live_round_trip_reports(report, run_output_dir)
    except (OSError, ValueError) as error:
        print_error_and_exit(error)

    safe_results = {"COMPLETED_ROUND_TRIP", "ENTRY_FILLED_EXIT_OPEN"}
    payload = {
        "artifacts": {name: str(path) for name, path in artifacts.items()},
        "final_result": report.final_result,
        "live_entry_attempt_count": report.live_entry_attempt_count,
        "run_id": report.run_id,
        "status": "ok" if report.final_result in safe_results else "blocked",
    }
    typer.echo(json.dumps(payload, sort_keys=True))
    if report.final_result not in safe_results:
        raise typer.Exit(code=1)


def tiny_live_copy(
    candidate_file: Annotated[
        Path,
        typer.Option(
            "--candidate-file",
            help="Protected mode-0600 candidate input; raw addresses are never reported.",
        ),
    ],
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Protected run-specific report directory."),
    ],
    database_path: Annotated[
        Path,
        typer.Option("--database", help="Persistent PolySia SQLite state database."),
    ] = Path("data/polysia.sqlite3"),
    run_id: Annotated[
        str | None,
        typer.Option("--run-id", help="Stable run id used for restart recovery."),
    ] = None,
    submit: Annotated[
        bool,
        typer.Option("--submit/--dry-run", help="Enable only the bounded owner-approved run."),
    ] = False,
    authorization_id: Annotated[
        str | None,
        typer.Option(
            "--authorization-id",
            help="Protected runtime owner authorization; omit for Dry-run/Shadow.",
        ),
    ] = None,
    acknowledge: Annotated[
        str | None,
        typer.Option(
            "--acknowledge",
            help="Required Live acknowledgement; must match --authorization-id exactly.",
        ),
    ] = None,
    verified_ci_commit: Annotated[
        str | None,
        typer.Option("--verified-ci-commit", help="Exact green-CI merge commit."),
    ] = None,
    maximum_poll_cycles: Annotated[
        int | None,
        typer.Option(
            "--maximum-poll-cycles",
            min=1,
            help="Test-only bounded return; omit for the fixed 12-hour run.",
        ),
    ] = None,
) -> None:
    """Run the exact 102-candidate, three-attempt Tiny Live Copy experiment."""

    settings = AppSettings()
    configure_logging(settings)
    cli_support.apply_secure_env_from_settings(settings)
    actual_run_id = run_id or f"tiny-live-copy-{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
    report = asyncio.run(
        run_tiny_live_copy(
            TinyLiveCopyConfig(
                settings=settings,
                project_root=Path("."),
                output_dir=output_dir,
                database_path=database_path,
                candidate_file=candidate_file,
                run_id=actual_run_id,
                dry_run=not submit,
                authorization_id=authorization_id,
                acknowledgement=(authorization_id is not None and acknowledge == authorization_id),
                verified_ci_commit=verified_ci_commit,
                maximum_poll_cycles=maximum_poll_cycles,
            )
        )
    )
    typer.echo(json.dumps(report.to_dict(), sort_keys=True))


def controlled_second_tiny_live(
    auto_btc_5m: Annotated[
        bool,
        typer.Option("--auto-btc-5m"),
    ] = False,
    token_id: Annotated[
        str | None,
        typer.Option("--token-id", help="Optional allowlisted BTC 5m token."),
    ] = None,
    market_slug: Annotated[
        str | None,
        typer.Option("--market-slug", help="BTC Up/Down 5m market slug."),
    ] = None,
    side: Annotated[Literal["BUY", "SELL"], typer.Option("--side")] = "BUY",
    outcome: Annotated[Literal["YES", "NO"], typer.Option("--outcome")] = "YES",
    max_notional: Annotated[str, typer.Option("--max-notional")] = "1.00",
    order_type: Annotated[Literal["FAK", "FOK"], typer.Option("--order-type")] = "FOK",
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Keep this run dry. Default when --submit is absent."),
    ] = False,
    submit: Annotated[
        bool,
        typer.Option("--submit", help="Request the one real second tiny live attempt."),
    ] = False,
    require_clean_git: Annotated[
        bool,
        typer.Option("--require-clean-git"),
    ] = False,
    i_understand_this_places_real_orders: Annotated[
        bool,
        typer.Option("--i-understand-this-places-real-orders"),
    ] = False,
    i_confirm_this_is_the_second_controlled_tiny_live_test: Annotated[
        bool,
        typer.Option("--i-confirm-this-is-the-second-controlled-tiny-live-test"),
    ] = False,
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Directory for controlled second tiny reports."),
    ] = Path("release-artifacts"),
) -> None:
    """Prepare or submit one stricter controlled second tiny live attempt."""
    settings = AppSettings()
    configure_logging(settings)

    try:
        selected_token = token_id
        selected_market_slug = market_slug
        if auto_btc_5m:
            selection = asyncio.run(
                core.resolve_live_smoke_selection(
                    market_slug=None,
                    condition_id=None,
                    token_id=None,
                    outcome=outcome,
                    auto_btc_5m=True,
                )
            )
            selected_token = selection.token_id
            selected_market_slug = selection.market_slug
        if selected_token is None or selected_market_slug is None:
            raise ValueError(
                "--token-id and --market-slug are required unless --auto-btc-5m is used."
            )
        report = asyncio.run(
            run_controlled_second_tiny_live(
                ControlledSecondTinyLiveConfig(
                    settings=settings,
                    output_dir=output_dir,
                    token_id=selected_token,
                    side=side,
                    outcome=outcome,
                    max_notional=cli_support.parse_decimal(max_notional, "max_notional"),
                    order_type=order_type,
                    market_slug=selected_market_slug,
                    dry_run=(not submit) or dry_run,
                    submit_requested=submit,
                    acknowledgement=i_understand_this_places_real_orders,
                    second_acknowledgement=(i_confirm_this_is_the_second_controlled_tiny_live_test),
                    auto_btc_5m=auto_btc_5m,
                    require_clean_git=require_clean_git,
                    project_root=Path("."),
                )
            )
        )
    except (PolymarketPublicAdapterError, ValueError) as error:
        print_error_and_exit(error)

    artifacts = {
        "json": str(output_dir / controlled_second_tiny_live_filename("json")),
        "markdown": str(output_dir / controlled_second_tiny_live_filename("markdown")),
    }
    payload = {
        "artifacts": artifacts,
        "final_result": report.final_result,
        "live_attempt_count": report.live_attempt_count,
        "order_submitted": report.order_submitted,
        "status": "ok" if report.final_result != "BLOCKED" else "blocked",
    }
    typer.echo(json.dumps(payload, sort_keys=True))
    if report.final_result == "BLOCKED":
        raise typer.Exit(code=1)


def manual_intervention_live_test(
    auto_btc_5m: Annotated[bool, typer.Option("--auto-btc-5m")] = False,
    token_id: Annotated[
        str | None,
        typer.Option("--token-id", help="Optional allowlisted BTC 5m token."),
    ] = None,
    market_slug: Annotated[
        str | None,
        typer.Option("--market-slug", help="BTC Up/Down 5m market slug."),
    ] = None,
    condition_id: Annotated[
        str | None,
        typer.Option("--condition-id", help="Optional selected market condition id."),
    ] = None,
    outcome: Annotated[Literal["YES", "NO"], typer.Option("--outcome")] = "YES",
    side: Annotated[Literal["BUY", "SELL"], typer.Option("--side")] = "BUY",
    max_notional: Annotated[str, typer.Option("--max-notional")] = "1.00",
    order_type: Annotated[Literal["FAK", "FOK"], typer.Option("--order-type")] = "FOK",
    dry_run: Annotated[bool, typer.Option("--dry-run/--no-dry-run")] = True,
    require_clean_git: Annotated[bool, typer.Option("--require-clean-git")] = False,
    poll_attempts: Annotated[int, typer.Option("--poll-attempts", min=1)] = 30,
    poll_interval_seconds: Annotated[
        float,
        typer.Option("--poll-interval-seconds", min=0.0),
    ] = 2.0,
    i_understand_this_places_one_real_order: Annotated[
        bool,
        typer.Option("--i-understand-this-places-one-real-order"),
    ] = False,
    i_will_manually_cancel_or_close: Annotated[
        bool,
        typer.Option("--i-will-manually-cancel-or-close"),
    ] = False,
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Directory for manual-intervention reports."),
    ] = Path("release-artifacts"),
) -> None:
    """Run a controlled manual-intervention test; defaults to dry-run."""
    settings = AppSettings()
    configure_logging(settings)

    try:
        selected_token = token_id
        selected_market_slug = market_slug
        selected_condition_id = condition_id
        if auto_btc_5m:
            selection = asyncio.run(
                core.resolve_live_smoke_selection(
                    market_slug=None,
                    condition_id=None,
                    token_id=None,
                    outcome=outcome,
                    auto_btc_5m=True,
                )
            )
            selected_token = selection.token_id
            selected_market_slug = selection.market_slug
            selected_condition_id = selection.condition_id
        if selected_token is None or selected_market_slug is None:
            raise ValueError(
                "--token-id and --market-slug are required unless --auto-btc-5m is used."
            )
        if auto_btc_5m and selected_token not in settings.polymarket_live_token_allowlist:
            settings = settings.model_copy(
                update={"polymarket_live_token_allowlist": (selected_token,)}
            )
        cli_support.apply_secure_env_from_settings(settings)
        report = asyncio.run(
            run_manual_intervention_live_test(
                ManualInterventionLiveTestConfig(
                    settings=settings,
                    output_dir=output_dir,
                    token_id=selected_token,
                    side=side,
                    outcome=outcome,
                    max_notional=cli_support.parse_decimal(max_notional, "max_notional"),
                    order_type=order_type,
                    market_slug=selected_market_slug,
                    condition_id=selected_condition_id,
                    dry_run=dry_run,
                    acknowledgement=i_understand_this_places_one_real_order,
                    manual_intervention_acknowledgement=i_will_manually_cancel_or_close,
                    require_clean_git=require_clean_git,
                    poll_attempts=poll_attempts,
                    poll_interval_seconds=poll_interval_seconds,
                    project_root=Path("."),
                )
            )
        )
    except (PolymarketPublicAdapterError, ValueError) as error:
        print_error_and_exit(error)

    artifacts = {
        "json": str(output_dir / manual_intervention_live_test_filename("json")),
        "markdown": str(output_dir / manual_intervention_live_test_filename("markdown")),
    }
    payload = {
        "artifacts": artifacts,
        "final_result": report.final_result,
        "live_attempt_count": report.live_attempt_count,
        "manual_intervention_detected": report.manual_intervention_detected,
        "order_submitted": report.order_submitted,
        "status": "ok" if report.final_result != "BLOCKED" else "blocked",
        "trading_should_pause": report.trading_should_pause,
    }
    typer.echo(json.dumps(payload, sort_keys=True))
    if report.final_result == "BLOCKED":
        raise typer.Exit(code=1)


def live_limit_order(
    token_id: Annotated[str, typer.Option("--token-id", help="Allowlisted outcome token ID.")],
    side: Annotated[str, typer.Option("--side", help="BUY or SELL.")] = "BUY",
    price: Annotated[str, typer.Option("--price", help="Limit price in [0, 1].")] = "0.01",
    size: Annotated[str, typer.Option("--size", help="Share size capped by settings.")] = "1",
    dry_run: Annotated[bool, typer.Option("--dry-run/--submit")] = True,
    strategy_id: Annotated[str, typer.Option("--strategy-id")] = "operator-tiny-live",
    reason: Annotated[str, typer.Option("--reason")] = "manual tiny live limit order",
    current_position: Annotated[str, typer.Option("--current-position")] = "0",
    current_market_position: Annotated[str, typer.Option("--current-market-position")] = "0",
    daily_pnl: Annotated[str, typer.Option("--daily-pnl")] = "0",
    open_orders_count: Annotated[int, typer.Option("--open-orders-count", min=0)] = 0,
    market_data_age_ms: Annotated[int, typer.Option("--market-data-age-ms", min=0)] = 0,
    i_understand_this_places_real_orders: Annotated[
        bool,
        typer.Option("--i-understand-this-places-real-orders"),
    ] = False,
) -> None:
    """Place or preview one tiny post-only live limit order; defaults to dry-run."""
    settings = AppSettings()
    configure_logging(settings)

    try:
        payload = asyncio.run(
            _live_limit_order(
                settings=settings,
                token_id=token_id,
                side=side,
                price=cli_support.parse_decimal(price, "price"),
                size=cli_support.parse_decimal(size, "size"),
                dry_run=dry_run,
                strategy_id=strategy_id,
                reason=reason,
                current_position=cli_support.parse_decimal(current_position, "current_position"),
                current_market_position=cli_support.parse_decimal(
                    current_market_position,
                    "current_market_position",
                ),
                daily_pnl=cli_support.parse_decimal(daily_pnl, "daily_pnl"),
                open_orders_count=open_orders_count,
                market_data_age_ms=market_data_age_ms,
                i_understand_this_places_real_orders=(i_understand_this_places_real_orders),
            )
        )
    except (LiveBrokerError, PolymarketSecureAdapterError, ValueError) as error:
        print_error_and_exit(error)

    typer.echo(json.dumps(payload, sort_keys=True))


async def _live_open_orders(
    *,
    settings: AppSettings,
    token_id: str | None,
    order_id: str | None,
    market: str | None,
    i_understand_this_uses_live_account: bool,
) -> dict[str, object]:
    cli_support.apply_secure_env_from_settings(settings)
    adapter = PolymarketSecureAdapter()
    broker = _build_live_broker(settings=settings, adapter=adapter)
    try:
        result = await broker.get_open_orders(
            token_id=token_id,
            order_id=order_id,
            market=market,
            i_understand_this_uses_live_account=i_understand_this_uses_live_account,
        )
        orders = [cli_support.safe_open_order_to_dict(order) for order in result.response or []]
        return {
            "count": len(orders),
            "dry_run": result.dry_run,
            "orders": orders,
            "request": result.request,
            "status": "ok",
        }
    finally:
        await adapter.close()


async def _live_account_status(
    *,
    settings: AppSettings,
    i_understand_this_uses_live_account: bool,
) -> dict[str, object]:
    if settings.trading_mode != TradingMode.LIVE:
        raise LiveBrokerError("live account reads require TRADING_MODE=LIVE.")
    if not i_understand_this_uses_live_account:
        raise LiveBrokerError(
            "live account reads require --redact-secrets or --i-understand-this-uses-live-account."
        )

    cli_support.apply_secure_env_from_settings(settings)
    adapter = PolymarketSecureAdapter()
    try:
        await adapter.connect()
        identity = adapter.identity().to_dict()
        collateral = await cli_support.read_safe_balance_allowance(adapter)
        positions = await cli_support.read_safe_positions(adapter)
        open_orders = await cli_support.read_safe_open_orders(adapter)
        return {
            "account_identity": identity,
            "balance_readable": collateral["balance_readable"],
            "approval_readable": collateral["approval_readable"],
            "collateral": collateral,
            "open_order_count": open_orders["count"],
            "open_orders_readable": open_orders["readable"],
            "position_count": positions["count"],
            "positions_preview": positions["positions_preview"],
            "positions_readable": positions["readable"],
            "positions_truncated": positions["truncated"],
            "positive_approval_count": collateral["positive_approval_count"],
            "status": "ok",
        }
    finally:
        await adapter.close()


async def _live_cancel_order(
    *,
    settings: AppSettings,
    order_id: str,
    dry_run: bool,
    i_understand_this_modifies_live_orders: bool,
) -> dict[str, object]:
    cli_support.apply_secure_env_from_settings(settings)
    adapter = PolymarketSecureAdapter()
    broker = _build_live_broker(settings=settings, adapter=adapter)
    try:
        result = await broker.cancel_order(
            order_id=order_id,
            dry_run=dry_run,
            i_understand_this_modifies_live_orders=i_understand_this_modifies_live_orders,
        )
        return {
            "dry_run": result.dry_run,
            "request": result.request,
            "response": cli_support.safe_cancel_response(result.response),
            "status": "ok",
            "submitted": result.submitted,
        }
    finally:
        await adapter.close()


async def _live_cancel_market_orders(
    *,
    settings: AppSettings,
    token_id: str,
    dry_run: bool,
    i_understand_this_modifies_live_orders: bool,
) -> dict[str, object]:
    cli_support.apply_secure_env_from_settings(settings)
    adapter = PolymarketSecureAdapter()
    broker = _build_live_broker(settings=settings, adapter=adapter)
    try:
        result = await broker.cancel_market_orders(
            token_id=token_id,
            dry_run=dry_run,
            i_understand_this_modifies_live_orders=i_understand_this_modifies_live_orders,
        )
        return {
            "dry_run": result.dry_run,
            "request": result.request,
            "response": cli_support.safe_cancel_response(result.response),
            "status": "ok",
            "submitted": result.submitted,
        }
    finally:
        await adapter.close()


async def _live_limit_order(
    *,
    settings: AppSettings,
    token_id: str,
    side: str,
    price: Decimal,
    size: Decimal,
    dry_run: bool,
    strategy_id: str,
    reason: str,
    current_position: Decimal,
    current_market_position: Decimal,
    daily_pnl: Decimal,
    open_orders_count: int,
    market_data_age_ms: int,
    i_understand_this_places_real_orders: bool,
) -> dict[str, object]:
    cli_support.apply_secure_env_from_settings(settings)
    adapter = PolymarketSecureAdapter()
    broker = _build_tiny_live_order_broker(settings=settings, adapter=adapter)
    try:
        intent = OrderIntent(
            strategy_id=strategy_id,
            token_id=token_id,
            side=side,  # type: ignore[arg-type]
            price=price,
            size=size,
            reason=reason,
            confidence=Decimal("1"),
        )
        result = await broker.place_limit_order(
            intent,
            RiskContext(
                current_position=current_position,
                current_market_position=current_market_position,
                daily_pnl=daily_pnl,
                open_orders_count=open_orders_count,
                market_data_age_ms=market_data_age_ms,
            ),
            dry_run=dry_run,
            post_only=True,
            i_understand_this_places_real_orders=i_understand_this_places_real_orders,
        )
        return {
            "dry_run": result.dry_run,
            "request": result.request,
            "response": cli_support.safe_order_response(result.response),
            "status": "ok",
            "submitted": result.submitted,
        }
    finally:
        await adapter.close()


def _build_live_broker(*, settings: AppSettings, adapter: PolymarketSecureAdapter) -> LiveBroker:
    return LiveBroker(
        adapter=adapter,
        risk_engine=RiskEngine(),
        settings=settings,
        allowed_token_ids=settings.polymarket_live_token_allowlist,
    )


def _build_tiny_live_order_broker(
    *,
    settings: AppSettings,
    adapter: PolymarketSecureAdapter,
) -> LiveBroker:
    return LiveBroker(
        adapter=adapter,
        risk_engine=RiskEngine(
            limits=RiskLimits(
                max_order_notional=settings.polymarket_live_max_order_notional,
                max_position_per_token=settings.polymarket_live_max_order_size,
                max_position_per_market=settings.polymarket_live_max_order_size,
                max_open_orders=settings.polymarket_live_max_open_orders,
                allow_live_trading=True,
            )
        ),
        settings=settings,
        allowed_token_ids=settings.polymarket_live_token_allowlist,
    )
