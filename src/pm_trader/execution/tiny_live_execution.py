from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from html import escape
from pathlib import Path
from typing import Any, Literal, Protocol, cast

from pm_trader.adapters.geoblock import (
    GeoblockStatus,
    PreLiveOrderGeoblockCheck,
)
from pm_trader.adapters.polymarket_secure import (
    BalanceAssetType,
    MarketOrderType,
    OrderSide,
    PolymarketSecureAdapter,
    PolymarketSecureAdapterError,
)
from pm_trader.config.settings import AppSettings, TradingMode
from pm_trader.execution.intents import OrderIntent
from pm_trader.risk.checks import RiskContext, RiskDecision, RiskEngine
from pm_trader.risk.limits import RiskLimits

TinySide = Literal["BUY", "SELL"]
TinyOutcome = Literal["YES", "NO"]
TinyOrderType = Literal["FAK", "FOK"]
TinyExecutionResult = Literal[
    "DRY_RUN_PASS",
    "DRY_RUN_BLOCKED",
    "LIVE_ORDER_SUBMITTED",
    "LIVE_ORDER_FILLED",
    "LIVE_ORDER_PARTIALLY_FILLED",
    "LIVE_ORDER_REJECTED",
    "LIVE_ORDER_EXPIRED",
    "LIVE_ORDER_BLOCKED",
    "LIVE_ORDER_ERROR",
]
ReportFormat = Literal["json", "markdown", "html"]
Clock = Callable[[], datetime]
GitReader = Callable[[Path, tuple[str, ...]], str]

MAX_TINY_NOTIONAL = Decimal("1.00")


def utc_now() -> datetime:
    return datetime.now(UTC)


class TinyLiveExecutionError(RuntimeError):
    """Raised when a tiny live execution must fail safely."""


class TinyExecutionAdapter(Protocol):
    @property
    def is_connected(self) -> bool:
        """Whether the authenticated adapter is connected."""

    async def connect(self) -> None:
        """Connect to authenticated APIs."""

    async def close(self) -> None:
        """Close authenticated resources."""

    def identity(self) -> Any:
        """Return sanitized signer/funder diagnostics."""

    async def get_balance_allowance(
        self,
        *,
        asset_type: BalanceAssetType,
        token_id: str | None = None,
    ) -> Any:
        """Fetch balance and approval metadata."""

    async def get_open_orders(
        self,
        *,
        token_id: str | None = None,
        order_id: str | None = None,
        market: str | None = None,
    ) -> list[Any]:
        """Fetch open orders for risk context."""

    async def place_market_order(
        self,
        *,
        token_id: str,
        side: OrderSide,
        amount: Decimal | None = None,
        shares: Decimal | None = None,
        max_spend: Decimal | None = None,
        max_price: Decimal | None = None,
        min_price: Decimal | None = None,
        order_type: MarketOrderType = "FAK",
        builder_code: str | None = None,
    ) -> Any:
        """Submit one market FAK/FOK order."""


class TinyExecutionGeoblockCheck(Protocol):
    async def check(self) -> GeoblockStatus:
        """Return sanitized geoblock status."""


@dataclass(frozen=True, slots=True)
class TinyLiveExecutionConfig:
    settings: AppSettings
    token_id: str
    side: TinySide
    outcome: TinyOutcome
    max_notional: Decimal
    order_type: TinyOrderType
    output_dir: Path
    dry_run: bool = True
    require_clean_git: bool = False
    acknowledgement: bool = False
    market_slug: str | None = None
    condition_id: str | None = None
    price: Decimal | None = None
    redact_secrets: bool = True
    project_root: Path = Path(".")


@dataclass(frozen=True, slots=True)
class TinyOrderPlan:
    risk_price: Decimal
    risk_size: Decimal
    amount: Decimal | None
    shares: Decimal | None
    max_price: Decimal | None
    min_price: Decimal | None


@dataclass(frozen=True, slots=True)
class TinyLiveExecutionReport:
    timestamp: datetime
    dry_run: bool
    final_result: TinyExecutionResult
    token_allowlisted: bool
    geoblock_status: dict[str, object] | None
    kill_switch_active: bool
    risk_decision: dict[str, object]
    order_type: TinyOrderType
    side: TinySide
    outcome: TinyOutcome
    max_notional: str
    order_submitted: bool
    order_filled: bool
    fill_summary: dict[str, object]
    rejection_summary: dict[str, object]
    live_attempt_count: int
    no_retry_statement: str
    one_attempt_statement: str
    no_strategy_loop_statement: str
    blocking_reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    operator_next_steps: tuple[str, ...]
    diagnostics: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "blocking_reasons": list(self.blocking_reasons),
            "diagnostics": self.diagnostics,
            "dry_run": self.dry_run,
            "fill_summary": self.fill_summary,
            "final_result": self.final_result,
            "geoblock_status": self.geoblock_status,
            "kill_switch_active": self.kill_switch_active,
            "live_attempt_count": self.live_attempt_count,
            "max_notional": self.max_notional,
            "no_retry_statement": self.no_retry_statement,
            "no_strategy_loop_statement": self.no_strategy_loop_statement,
            "one_attempt_statement": self.one_attempt_statement,
            "operator_next_steps": list(self.operator_next_steps),
            "order_filled": self.order_filled,
            "order_submitted": self.order_submitted,
            "order_type": self.order_type,
            "outcome": self.outcome,
            "rejection_summary": self.rejection_summary,
            "risk_decision": self.risk_decision,
            "side": self.side,
            "timestamp": self.timestamp.isoformat(),
            "token_allowlisted": self.token_allowlisted,
            "warnings": list(self.warnings),
        }


class OneLiveOrderAttempt:
    """Enforces exactly one live submit attempt per command run."""

    def __init__(self) -> None:
        self.count = 0

    async def submit_once(
        self,
        adapter: TinyExecutionAdapter,
        *,
        token_id: str,
        side: TinySide,
        plan: TinyOrderPlan,
        order_type: TinyOrderType,
    ) -> Any:
        if self.count >= 1:
            raise TinyLiveExecutionError("one live order attempt invariant violated.")
        self.count += 1
        return await adapter.place_market_order(
            token_id=token_id,
            side=cast(OrderSide, side),
            amount=plan.amount,
            shares=plan.shares,
            max_price=plan.max_price,
            min_price=plan.min_price,
            order_type=cast(MarketOrderType, order_type),
        )


async def run_tiny_live_execution(
    config: TinyLiveExecutionConfig,
    *,
    adapter: TinyExecutionAdapter | None = None,
    geoblock_check: TinyExecutionGeoblockCheck | None = None,
    risk_engine: RiskEngine | None = None,
    clock: Clock = utc_now,
    git_reader: GitReader | None = None,
) -> TinyLiveExecutionReport:
    """Run a guarded one-attempt tiny live execution or dry-run preview."""

    active_adapter = adapter or PolymarketSecureAdapter()
    active_geoblock = geoblock_check or PreLiveOrderGeoblockCheck()
    active_risk_engine = risk_engine or _tiny_risk_engine(config.settings)
    attempt_guard = OneLiveOrderAttempt()
    blocking: list[str] = []
    warnings: list[str] = []
    diagnostics: dict[str, object] = {
        "market_scope": _market_scope(config.market_slug),
        "redact_secrets": config.redact_secrets,
    }
    geoblock_status: dict[str, object] | None = None
    risk_decision = RiskDecision(approved=False, reason="not evaluated")
    response_payload: dict[str, object] = {}
    order_submitted = False
    final_result: TinyExecutionResult = (
        "DRY_RUN_BLOCKED" if config.dry_run else "LIVE_ORDER_BLOCKED"
    )

    try:
        _validate_static_config(config)
        plan = _build_order_plan(config)
        _assert_common_gates(config, active_risk_engine, git_reader=git_reader)

        open_orders_count = 0
        if not config.dry_run:
            if not active_adapter.is_connected:
                await active_adapter.connect()
            identity = _safe_identity(active_adapter.identity())
            diagnostics["identity"] = identity
            _assert_identity_ready(identity)
            balance = await active_adapter.get_balance_allowance(
                asset_type="COLLATERAL" if config.side == "BUY" else "CONDITIONAL",
                token_id=None if config.side == "BUY" else config.token_id,
            )
            diagnostics["account_readable"] = True
            _assert_balance_allowance_ready(balance)
            open_orders_count = len(await active_adapter.get_open_orders(token_id=config.token_id))

            status = await active_geoblock.check()
            geoblock_status = status.to_safe_dict()
            _assert_geoblock_allows(status)
        else:
            diagnostics["identity"] = {
                "funder_configured": bool(config.settings.polymarket_funder_address),
                "signer_configured": config.settings.polymarket_private_key is not None,
            }
            diagnostics["account_readable"] = False
            geoblock_status = {"status": "not_checked", "blocked": None}

        risk_context = RiskContext(
            trading_mode=TradingMode.PAPER if config.dry_run else TradingMode.LIVE,
            live_trading_enabled=False if config.dry_run else config.settings.live_trading_enabled,
            current_position=Decimal("0"),
            current_market_position=Decimal("0"),
            daily_pnl=Decimal("0"),
            open_orders_count=open_orders_count,
            market_data_age_ms=0,
        )
        risk_decision = active_risk_engine.evaluate(
            OrderIntent(
                strategy_id="operator-tiny-live-execute",
                token_id=config.token_id,
                side=config.side,
                price=plan.risk_price,
                size=plan.risk_size,
                reason="manual tiny live execution",
                confidence=Decimal("1"),
            ),
            risk_context,
        )
        if not risk_decision.approved:
            raise TinyLiveExecutionError(f"risk engine blocked order: {risk_decision.reason}")

        if config.dry_run:
            final_result = "DRY_RUN_PASS"
        else:
            response = await attempt_guard.submit_once(
                active_adapter,
                token_id=config.token_id,
                side=config.side,
                plan=plan,
                order_type=config.order_type,
            )
            order_submitted = True
            response_payload = _model_or_mapping_to_dict(response)
            final_result = _classify_live_response(response_payload)
    except (
        TinyLiveExecutionError,
        PolymarketSecureAdapterError,
        OSError,
        subprocess.SubprocessError,
        ValueError,
    ) as error:
        blocking.append(str(error))
        if not config.dry_run and attempt_guard.count > 0:
            final_result = "LIVE_ORDER_ERROR"
        else:
            final_result = "DRY_RUN_BLOCKED" if config.dry_run else "LIVE_ORDER_BLOCKED"
    finally:
        await active_adapter.close()

    report = TinyLiveExecutionReport(
        timestamp=clock(),
        dry_run=config.dry_run,
        final_result=final_result,
        token_allowlisted=config.token_id in config.settings.polymarket_live_token_allowlist,
        geoblock_status=geoblock_status,
        kill_switch_active=active_risk_engine.kill_switch.is_active(),
        risk_decision=_risk_decision_to_dict(risk_decision),
        order_type=config.order_type,
        side=config.side,
        outcome=config.outcome,
        max_notional=str(config.max_notional),
        order_submitted=order_submitted,
        order_filled=final_result in {"LIVE_ORDER_FILLED", "LIVE_ORDER_PARTIALLY_FILLED"},
        fill_summary=_fill_summary(response_payload),
        rejection_summary=_rejection_summary(response_payload, final_result),
        live_attempt_count=attempt_guard.count,
        no_retry_statement="No retry was attempted",
        one_attempt_statement="Only one order attempt was allowed",
        no_strategy_loop_statement="No strategy loop or market-making loop was used",
        blocking_reasons=tuple(blocking),
        warnings=tuple(warnings),
        operator_next_steps=_next_steps(final_result),
        diagnostics=diagnostics,
    )
    write_tiny_live_execution_reports(report, config.output_dir)
    return report


def write_tiny_live_execution_reports(
    report: TinyLiveExecutionReport,
    output_dir: Path,
    formats: tuple[ReportFormat, ...] = ("json", "markdown", "html"),
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, str] = {}
    for report_format in formats:
        path = output_dir / tiny_live_execution_filename(report_format)
        path.write_text(
            f"{render_tiny_live_execution(report, report_format)}\n",
            encoding="utf-8",
        )
        artifacts[report_format] = str(path)
    return artifacts


def render_tiny_live_execution_json(report: TinyLiveExecutionReport) -> str:
    return json.dumps(report.to_dict(), indent=2, sort_keys=True)


def render_tiny_live_execution_markdown(report: TinyLiveExecutionReport) -> str:
    blockers = "\n".join(f"- {reason}" for reason in report.blocking_reasons) or "- None"
    warnings = "\n".join(f"- {warning}" for warning in report.warnings) or "- None"
    next_steps = "\n".join(f"- {step}" for step in report.operator_next_steps) or "- None"
    return "\n".join(
        (
            "# Polymarket Tiny Live Execution",
            "",
            f"- Final result: {report.final_result}",
            f"- Dry run: {report.dry_run}",
            f"- Order submitted: {report.order_submitted}",
            f"- Live attempt count: {report.live_attempt_count}",
            f"- Side/outcome: {report.side} {report.outcome}",
            f"- Order type: {report.order_type}",
            f"- Max notional: {report.max_notional}",
            f"- Token allowlisted: {report.token_allowlisted}",
            "",
            "## Safety Statements",
            "",
            f"- {report.no_retry_statement}",
            f"- {report.one_attempt_statement}",
            f"- {report.no_strategy_loop_statement}",
            "",
            "## Blocking Reasons",
            "",
            blockers,
            "",
            "## Warnings",
            "",
            warnings,
            "",
            "## Operator Next Steps",
            "",
            next_steps,
            "",
        )
    )


def render_tiny_live_execution_html(report: TinyLiveExecutionReport) -> str:
    payload = report.to_dict()
    rows = "".join(
        "<tr>"
        f"<th>{escape(str(key))}</th>"
        f"<td>{escape(str(value))}</td>"
        "</tr>"
        for key, value in sorted(payload.items())
        if key not in {"diagnostics"}
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Polymarket Tiny Live Execution</title>
  <style>
    body {{ margin: 0; font-family: Arial, Helvetica, sans-serif; color: #1f2933; }}
    main {{ max-width: 980px; margin: 0 auto; padding: 28px 18px; }}
    h1 {{ margin: 0 0 8px; font-size: 28px; letter-spacing: 0; }}
    .badge {{ display: inline-block; border-radius: 8px; padding: 8px 12px; color: #fff;
      background: #1f5f8b; font-weight: 700; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 18px; }}
    th, td {{ border-top: 1px solid #d7dce0; padding: 9px 6px; text-align: left; }}
    th {{ color: #687582; width: 36%; }}
  </style>
</head>
<body>
  <main>
    <h1>Polymarket Tiny Live Execution</h1>
    <p>{escape(report.timestamp.isoformat())}</p>
    <div class="badge">{escape(report.final_result)}</div>
    <table>{rows}</table>
  </main>
</body>
</html>
"""


def render_tiny_live_execution(
    report: TinyLiveExecutionReport,
    report_format: ReportFormat,
) -> str:
    if report_format == "json":
        return render_tiny_live_execution_json(report)
    if report_format == "markdown":
        return render_tiny_live_execution_markdown(report)
    return render_tiny_live_execution_html(report)


def normalize_tiny_live_execution_formats(
    *,
    json_enabled: bool,
    markdown_enabled: bool,
    html_enabled: bool,
) -> tuple[ReportFormat, ...]:
    selected: list[ReportFormat] = []
    if json_enabled:
        selected.append("json")
    if markdown_enabled:
        selected.append("markdown")
    if html_enabled:
        selected.append("html")
    if not selected:
        return ("json", "markdown", "html")
    return tuple(selected)


def tiny_live_execution_filename(report_format: ReportFormat) -> str:
    return {
        "html": "tiny_live_execution.html",
        "json": "tiny_live_execution.json",
        "markdown": "tiny_live_execution.md",
    }[report_format]


def _validate_static_config(config: TinyLiveExecutionConfig) -> None:
    if not config.token_id.strip():
        raise TinyLiveExecutionError("--token-id is required.")
    if config.side not in {"BUY", "SELL"}:
        raise TinyLiveExecutionError("--side must be BUY or SELL.")
    if config.outcome not in {"YES", "NO"}:
        raise TinyLiveExecutionError("--outcome must be YES or NO.")
    if config.order_type not in {"FAK", "FOK"}:
        raise TinyLiveExecutionError("tiny-live-execute only supports FAK or FOK.")
    if config.max_notional <= 0:
        raise TinyLiveExecutionError("--max-notional must be positive.")
    if config.max_notional > MAX_TINY_NOTIONAL:
        raise TinyLiveExecutionError("--max-notional above 1.00 is rejected.")
    if config.price is not None and (config.price <= 0 or config.price > 1):
        raise TinyLiveExecutionError("--price must be within (0, 1].")
    if config.side == "SELL" and config.price is None:
        raise TinyLiveExecutionError("SELL tiny-live-execute requires --price.")
    if config.market_slug is not None and not _is_btc_updown_5m_slug(config.market_slug):
        raise TinyLiveExecutionError("tiny-live-execute is restricted to BTC Up/Down 5m.")


def _assert_common_gates(
    config: TinyLiveExecutionConfig,
    risk_engine: RiskEngine,
    *,
    git_reader: GitReader | None,
) -> None:
    if risk_engine.kill_switch.is_active():
        reason = risk_engine.kill_switch.reason or "kill switch active"
        raise TinyLiveExecutionError(f"tiny live execution blocked by kill switch: {reason}")
    if not config.settings.polymarket_live_token_allowlist:
        raise TinyLiveExecutionError("tiny-live-execute requires POLYMARKET_LIVE_TOKEN_ALLOWLIST.")
    if config.token_id not in config.settings.polymarket_live_token_allowlist:
        raise TinyLiveExecutionError("selected token_id is not in POLYMARKET_LIVE_TOKEN_ALLOWLIST.")
    if config.dry_run:
        return
    if config.settings.trading_mode != TradingMode.LIVE:
        raise TinyLiveExecutionError("real tiny order requires TRADING_MODE=LIVE.")
    if not config.settings.live_trading_enabled:
        raise TinyLiveExecutionError("real tiny order requires LIVE_TRADING_ENABLED=true.")
    if not config.acknowledgement:
        raise TinyLiveExecutionError(
            "real tiny order requires --i-understand-this-places-one-real-order."
        )
    if config.settings.polymarket_private_key is None:
        raise TinyLiveExecutionError("real tiny order requires POLYMARKET_PRIVATE_KEY.")
    if not config.settings.polymarket_funder_address:
        raise TinyLiveExecutionError("real tiny order requires POLYMARKET_FUNDER_ADDRESS.")
    if config.require_clean_git and _git_status(config.project_root, git_reader=git_reader).strip():
        raise TinyLiveExecutionError("Repository has uncommitted changes.")


def _build_order_plan(config: TinyLiveExecutionConfig) -> TinyOrderPlan:
    risk_price = config.price or Decimal("1")
    risk_size = (config.max_notional / risk_price).quantize(Decimal("0.000001"))
    if config.side == "BUY":
        return TinyOrderPlan(
            risk_price=risk_price,
            risk_size=risk_size,
            amount=config.max_notional,
            shares=None,
            max_price=config.price,
            min_price=None,
        )
    return TinyOrderPlan(
        risk_price=risk_price,
        risk_size=risk_size,
        amount=None,
        shares=risk_size,
        max_price=None,
        min_price=config.price,
    )


def _tiny_risk_engine(settings: AppSettings) -> RiskEngine:
    return RiskEngine(
        limits=RiskLimits(
            max_order_notional=min(settings.polymarket_live_max_order_notional, MAX_TINY_NOTIONAL),
            max_position_per_token=settings.polymarket_live_max_order_size,
            max_position_per_market=settings.polymarket_live_max_order_size,
            max_open_orders=settings.polymarket_live_max_open_orders,
            allow_live_trading=True,
        )
    )


def _assert_geoblock_allows(status: GeoblockStatus) -> None:
    if status.status == "allowed" and status.blocked is False:
        return
    if status.status == "blocked" or status.blocked is True:
        raise TinyLiveExecutionError("Polymarket geoblock returned blocked=true.")
    raise TinyLiveExecutionError("Polymarket geoblock check failed closed.")


def _assert_identity_ready(identity: dict[str, object]) -> None:
    if identity.get("signer_configured") is not True:
        raise TinyLiveExecutionError("signer is not configured.")
    if identity.get("funder_configured") is not True:
        raise TinyLiveExecutionError("funder is not configured.")


def _assert_balance_allowance_ready(balance_allowance: Any) -> None:
    payload = _model_or_mapping_to_dict(balance_allowance)
    balance = _decimal_or_none(payload.get("balance"))
    if balance is None or balance <= 0:
        raise TinyLiveExecutionError("balance is missing or zero.")
    allowances = payload.get("allowances")
    if not isinstance(allowances, dict):
        raise TinyLiveExecutionError("approval allowance is not readable.")
    if not any((_decimal_or_none(value) or Decimal("0")) > 0 for value in allowances.values()):
        raise TinyLiveExecutionError("approval allowance is missing or zero.")


def _classify_live_response(response: dict[str, object]) -> TinyExecutionResult:
    if response.get("ok", True) is False:
        return "LIVE_ORDER_REJECTED"
    status = str(response.get("status", "")).lower()
    if status in {"matched", "filled", "fill"}:
        return "LIVE_ORDER_FILLED"
    if "partial" in status:
        return "LIVE_ORDER_PARTIALLY_FILLED"
    if status in {"expired", "no_fill", "unmatched"}:
        return "LIVE_ORDER_EXPIRED"
    if status in {"rejected", "failed"}:
        return "LIVE_ORDER_REJECTED"
    return "LIVE_ORDER_SUBMITTED"


def _fill_summary(response: dict[str, object]) -> dict[str, object]:
    return {
        "average_fill_price": _safe_value(
            response.get("average_fill_price") or response.get("price")
        ),
        "filled_size": _safe_value(
            response.get("filled_size")
            or response.get("takingAmount")
            or response.get("taking_amount")
        ),
        "status": _safe_value(response.get("status")),
    }


def _rejection_summary(
    response: dict[str, object],
    final_result: TinyExecutionResult,
) -> dict[str, object]:
    if final_result not in {"LIVE_ORDER_REJECTED", "LIVE_ORDER_ERROR", "LIVE_ORDER_EXPIRED"}:
        return {}
    return {
        "code": _safe_value(response.get("code")),
        "message": _safe_value(response.get("message")),
        "status": _safe_value(response.get("status")),
    }


def _risk_decision_to_dict(decision: RiskDecision) -> dict[str, object]:
    return {
        "approved": decision.approved,
        "adjusted_size": (
            str(decision.adjusted_size) if decision.adjusted_size is not None else None
        ),
        "reason": decision.reason,
    }


def _safe_identity(identity: Any) -> dict[str, object]:
    payload = _model_or_mapping_to_dict(identity)
    allowed = {
        "active_wallet_source",
        "configured_signature_type",
        "funder_configured",
        "legacy_wallet_configured",
        "sdk_signature_type",
        "signature_type_matches_sdk",
        "signer_configured",
        "wallet_type",
    }
    return {key: value for key, value in payload.items() if key in allowed}


def _next_steps(final_result: TinyExecutionResult) -> tuple[str, ...]:
    if final_result == "DRY_RUN_PASS":
        return ("Review the dry-run report before any separate human-approved real run.",)
    if final_result.startswith("LIVE_ORDER_"):
        return ("Review account state and open orders manually before any further action.",)
    return ("Fix blocking reasons and rerun dry-run only.",)


def _market_scope(market_slug: str | None) -> str:
    return market_slug or "BTC Up/Down 5m operator-selected token"


def _is_btc_updown_5m_slug(market_slug: str) -> bool:
    normalized = market_slug.lower().replace("_", "-")
    return "btc" in normalized and "5m" in normalized and (
        "updown" in normalized or ("up" in normalized and "down" in normalized)
    )


def _model_or_mapping_to_dict(source: object) -> dict[str, object]:
    if hasattr(source, "to_dict"):
        return dict(source.to_dict())
    if hasattr(source, "model_dump"):
        return dict(source.model_dump(mode="python"))
    if isinstance(source, dict):
        return dict(source)
    return {
        field_name: getattr(source, field_name)
        for field_name in dir(source)
        if not field_name.startswith("_") and not callable(getattr(source, field_name))
    }


def _safe_value(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (bool, int, str)):
        return str(value)
    return str(value)


def _decimal_or_none(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _git_status(project_root: Path, *, git_reader: GitReader | None) -> str:
    if git_reader is not None:
        return git_reader(project_root.resolve(), ("git", "status", "--short"))
    result = subprocess.run(
        ["git", "status", "--short"],
        check=True,
        capture_output=True,
        cwd=project_root.resolve(),
        text=True,
        timeout=5,
    )
    return result.stdout


__all__ = [
    "OneLiveOrderAttempt",
    "TinyLiveExecutionConfig",
    "TinyLiveExecutionError",
    "TinyLiveExecutionReport",
    "normalize_tiny_live_execution_formats",
    "render_tiny_live_execution",
    "render_tiny_live_execution_html",
    "render_tiny_live_execution_json",
    "render_tiny_live_execution_markdown",
    "run_tiny_live_execution",
    "tiny_live_execution_filename",
    "write_tiny_live_execution_reports",
]
