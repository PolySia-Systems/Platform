from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from html import escape
from pathlib import Path
from typing import Any, Literal

Clock = Callable[[], datetime]
ReportFormat = Literal["json", "markdown", "html"]
ExtendedEvaluationStatus = Literal[
    "EXTENDED_EVALUATION_READY",
    "EXTENDED_EVALUATION_WARNING",
    "EXTENDED_EVALUATION_NO_DATA",
]

_ADDRESS_RE = re.compile(r"0x[a-fA-F0-9]{40}")
_TX_HASH_RE = re.compile(r"0x[a-fA-F0-9]{64}")


class ExtendedStrategyEvaluationError(RuntimeError):
    """Raised when extended strategy evaluation input cannot be read."""


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class ExtendedStrategyEvaluationConfig:
    input_path: Path


@dataclass(frozen=True, slots=True)
class ExtendedSignalMetrics:
    intent_count: int
    buy_count: int
    sell_count: int
    average_confidence: Decimal | None
    average_modeled_edge: Decimal | None
    signal_frequency: Decimal | None

    def to_dict(self) -> dict[str, int | str | None]:
        return {
            "average_confidence": _optional_decimal(self.average_confidence),
            "average_modeled_edge": _optional_decimal(self.average_modeled_edge),
            "buy_count": self.buy_count,
            "intent_count": self.intent_count,
            "sell_count": self.sell_count,
            "signal_frequency": _optional_decimal(self.signal_frequency),
        }


@dataclass(frozen=True, slots=True)
class ExtendedRiskMetrics:
    approvals: int
    denials: int
    denial_reasons: dict[str, int]
    max_simulated_exposure: Decimal
    max_simulated_position: Decimal
    risk_limit_utilization: Decimal | None

    def to_dict(self) -> dict[str, int | str | dict[str, int] | None]:
        return {
            "approvals": self.approvals,
            "denial_reasons": dict(sorted(self.denial_reasons.items())),
            "denials": self.denials,
            "max_simulated_exposure": _decimal_to_str(self.max_simulated_exposure),
            "max_simulated_position": _decimal_to_str(self.max_simulated_position),
            "risk_limit_utilization": _optional_decimal(self.risk_limit_utilization),
        }


@dataclass(frozen=True, slots=True)
class ExtendedExecutionMetrics:
    paper_order_count: int
    paper_fill_count: int
    fill_ratio: Decimal
    missed_fill_count: int
    partial_fill_count: int
    average_simulated_slippage: Decimal | None
    adverse_selection_proxy: Decimal | None

    def to_dict(self) -> dict[str, int | str | None]:
        return {
            "adverse_selection_proxy": _optional_decimal(self.adverse_selection_proxy),
            "average_simulated_slippage": _optional_decimal(
                self.average_simulated_slippage
            ),
            "fill_ratio": _decimal_to_str(self.fill_ratio),
            "missed_fill_count": self.missed_fill_count,
            "paper_fill_count": self.paper_fill_count,
            "paper_order_count": self.paper_order_count,
            "partial_fill_count": self.partial_fill_count,
        }


@dataclass(frozen=True, slots=True)
class ExtendedPnLMetrics:
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    total_pnl: Decimal
    max_drawdown: Decimal
    win_count: int
    loss_count: int
    average_pnl_per_simulated_trade: Decimal | None

    def to_dict(self) -> dict[str, int | str | None]:
        return {
            "average_pnl_per_simulated_trade": _optional_decimal(
                self.average_pnl_per_simulated_trade
            ),
            "loss_count": self.loss_count,
            "max_drawdown": _decimal_to_str(self.max_drawdown),
            "realized_pnl": _decimal_to_str(self.realized_pnl),
            "total_pnl": _decimal_to_str(self.total_pnl),
            "unrealized_pnl": _decimal_to_str(self.unrealized_pnl),
            "win_count": self.win_count,
        }


@dataclass(frozen=True, slots=True)
class ExtendedCalibrationMetrics:
    brier_score: Decimal | None
    probability_buckets: tuple[dict[str, int | str | None], ...]
    outcome_warning: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "brier_score": _optional_decimal(self.brier_score),
            "outcome_warning": self.outcome_warning,
            "probability_buckets": list(self.probability_buckets),
        }


@dataclass(frozen=True, slots=True)
class ExtendedStrategyEvaluationReport:
    timestamp: datetime
    input_path: str
    final_result: ExtendedEvaluationStatus
    signal_metrics: ExtendedSignalMetrics
    risk_metrics: ExtendedRiskMetrics
    execution_metrics: ExtendedExecutionMetrics
    pnl_metrics: ExtendedPnLMetrics
    calibration_metrics: ExtendedCalibrationMetrics
    warnings: tuple[str, ...]
    no_live_trading_statement: str

    def to_dict(self) -> dict[str, object]:
        return {
            "calibration_metrics": self.calibration_metrics.to_dict(),
            "execution_metrics": self.execution_metrics.to_dict(),
            "final_result": self.final_result,
            "formulas": {
                "brier_score": "mean((p_model - outcome)^2)",
                "fill_ratio": "paper_fill_count / paper_order_count",
                "max_drawdown": "minimum equity minus prior peak",
            },
            "input_path": self.input_path,
            "no_live_trading_statement": self.no_live_trading_statement,
            "pnl_metrics": self.pnl_metrics.to_dict(),
            "risk_metrics": self.risk_metrics.to_dict(),
            "signal_metrics": self.signal_metrics.to_dict(),
            "timestamp": self.timestamp.isoformat(),
            "warnings": list(self.warnings),
        }


def build_extended_strategy_evaluation(
    config: ExtendedStrategyEvaluationConfig,
    *,
    clock: Clock = utc_now,
) -> ExtendedStrategyEvaluationReport:
    payload = load_extended_strategy_input(config.input_path)
    data = _flatten(payload)
    signal_metrics = _signal_metrics(data)
    risk_metrics = _risk_metrics(data)
    execution_metrics = _execution_metrics(data)
    pnl_metrics = _pnl_metrics(data, execution_metrics)
    calibration_metrics = _calibration_metrics(data)
    warnings = _warnings(signal_metrics, execution_metrics, calibration_metrics)
    final_result = _classify(signal_metrics, warnings)
    report = ExtendedStrategyEvaluationReport(
        timestamp=clock(),
        input_path=str(config.input_path),
        final_result=final_result,
        signal_metrics=signal_metrics,
        risk_metrics=risk_metrics,
        execution_metrics=execution_metrics,
        pnl_metrics=pnl_metrics,
        calibration_metrics=calibration_metrics,
        warnings=warnings,
        no_live_trading_statement=(
            "Extended strategy evaluation is read-only and never calls live broker, "
            "live submit, or live cancel APIs."
        ),
    )
    if _contains_sensitive_pattern(render_extended_strategy_evaluation(report, "json")):
        return ExtendedStrategyEvaluationReport(
            timestamp=report.timestamp,
            input_path=report.input_path,
            final_result="EXTENDED_EVALUATION_WARNING",
            signal_metrics=report.signal_metrics,
            risk_metrics=report.risk_metrics,
            execution_metrics=report.execution_metrics,
            pnl_metrics=report.pnl_metrics,
            calibration_metrics=report.calibration_metrics,
            warnings=(*report.warnings, "sanitization warning detected"),
            no_live_trading_statement=report.no_live_trading_statement,
        )
    return report


def load_extended_strategy_input(path: Path) -> object:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ExtendedStrategyEvaluationError(f"could not read input file: {path}") from error

    if path.suffix.lower() == ".jsonl":
        records: list[object] = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                records.append(json.loads(stripped))
            except json.JSONDecodeError as error:
                raise ExtendedStrategyEvaluationError(
                    f"invalid JSONL on line {line_number}"
                ) from error
        return records

    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise ExtendedStrategyEvaluationError("input must be valid JSON or JSONL") from error


def write_extended_strategy_evaluation_reports(
    report: ExtendedStrategyEvaluationReport,
    output_dir: Path,
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, str] = {}
    for report_format in ("json", "markdown", "html"):
        path = output_dir / extended_strategy_evaluation_filename(report_format)
        path.write_text(
            f"{render_extended_strategy_evaluation(report, report_format)}\n",
            encoding="utf-8",
        )
        artifacts[report_format] = str(path)
    return artifacts


def render_extended_strategy_evaluation(
    report: ExtendedStrategyEvaluationReport,
    report_format: ReportFormat,
) -> str:
    if report_format == "json":
        return json.dumps(report.to_dict(), indent=2, sort_keys=True)
    if report_format == "markdown":
        return render_extended_strategy_evaluation_markdown(report)
    return render_extended_strategy_evaluation_html(report)


def render_extended_strategy_evaluation_markdown(
    report: ExtendedStrategyEvaluationReport,
) -> str:
    warnings = "\n".join(f"- {warning}" for warning in report.warnings) or "- None"
    return "\n".join(
        (
            "# PolySia — Polymarket Adapter — Extended Strategy Evaluation",
            "",
            f"- Final result: {report.final_result}",
            f"- Generated at: {report.timestamp.isoformat()}",
            "",
            "## Signal Metrics",
            "",
            _table(report.signal_metrics.to_dict()),
            "",
            "## Risk Metrics",
            "",
            _table(report.risk_metrics.to_dict()),
            "",
            "## Execution Metrics",
            "",
            _table(report.execution_metrics.to_dict()),
            "",
            "## PnL Metrics",
            "",
            _table(report.pnl_metrics.to_dict()),
            "",
            "## Calibration Metrics",
            "",
            _table(report.calibration_metrics.to_dict()),
            "",
            "## Warnings",
            "",
            warnings,
            "",
            "## Live Trading",
            "",
            report.no_live_trading_statement,
            "",
        )
    )


def render_extended_strategy_evaluation_html(
    report: ExtendedStrategyEvaluationReport,
) -> str:
    warnings = "".join(f"<li>{escape(warning)}</li>" for warning in report.warnings)
    warnings = warnings or "<li>None</li>"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PolySia — Polymarket Adapter — Extended Strategy Evaluation</title>
  <style>
    body {{ margin: 0; font-family: Arial, Helvetica, sans-serif; color: #1f2933; }}
    main {{ max-width: 980px; margin: 0 auto; padding: 28px 18px; }}
    h1 {{ font-size: 28px; margin: 0 0 8px; letter-spacing: 0; }}
    h2 {{ font-size: 18px; margin-top: 24px; letter-spacing: 0; }}
    .badge {{ display: inline-block; border-radius: 8px; padding: 8px 12px; color: #fff;
      background: #1f5f8b; font-weight: 700; }}
    section {{ border: 1px solid #d7dce0; border-radius: 8px; padding: 14px; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border-top: 1px solid #d7dce0; padding: 9px 6px; text-align: left; }}
    tr:first-child th, tr:first-child td {{ border-top: 0; }}
    th {{ color: #687582; width: 44%; }}
  </style>
</head>
<body>
  <main>
    <h1>PolySia — Polymarket Adapter — Extended Strategy Evaluation</h1>
    <p>{escape(report.timestamp.isoformat())}</p>
    <div class="badge">{escape(report.final_result)}</div>
    <section><h2>Signal Metrics</h2>{_html_table(report.signal_metrics.to_dict())}</section>
    <section><h2>Risk Metrics</h2>{_html_table(report.risk_metrics.to_dict())}</section>
    <section><h2>Execution Metrics</h2>{_html_table(report.execution_metrics.to_dict())}</section>
    <section><h2>PnL Metrics</h2>{_html_table(report.pnl_metrics.to_dict())}</section>
    <section>
      <h2>Calibration Metrics</h2>
      {_html_table(report.calibration_metrics.to_dict())}
    </section>
    <section><h2>Warnings</h2><ul>{warnings}</ul></section>
    <section><h2>Live Trading</h2><p>{escape(report.no_live_trading_statement)}</p></section>
  </main>
</body>
</html>
"""


def extended_strategy_evaluation_filename(report_format: ReportFormat) -> str:
    return {
        "html": "strategy-evaluation-extended.html",
        "json": "strategy-evaluation-extended.json",
        "markdown": "strategy-evaluation-extended.md",
    }[report_format]


def _flatten(payload: object) -> dict[str, Any]:
    if isinstance(payload, list):
        return {"items": payload}
    if isinstance(payload, dict):
        return dict(payload)
    raise ExtendedStrategyEvaluationError("input root must be a JSON object or JSONL records")


def _signal_metrics(data: Mapping[str, Any]) -> ExtendedSignalMetrics:
    metrics = _mapping(data.get("metrics"))
    orders = _sequence(data.get("orders"))
    items = _sequence(data.get("items"))
    fallback_intent_count = len(orders) if orders else len(items)
    intent_count = _first_int(
        data.get("intents_generated"),
        metrics.get("strategy_intent_count"),
        _sum_samples(data, "strategy_intents"),
        fallback_intent_count,
    )
    buy_count, sell_count = _side_counts(orders, items)
    confidences = _collect_decimals(("confidence", "probability", "p_model"), orders, items)
    edges = _collect_decimals(("modeled_edge", "estimated_edge", "edge"), orders, items)
    event_count = _first_int(
        data.get("events_processed"),
        metrics.get("event_count"),
        len(_sequence(data.get("events"))),
        len(_sequence(data.get("samples"))),
    )
    return ExtendedSignalMetrics(
        intent_count=intent_count,
        buy_count=buy_count,
        sell_count=sell_count,
        average_confidence=_average(tuple(confidences)) if confidences else None,
        average_modeled_edge=_average(tuple(edges)) if edges else None,
        signal_frequency=_rate(intent_count, event_count) if event_count else None,
    )


def _risk_metrics(data: Mapping[str, Any]) -> ExtendedRiskMetrics:
    metrics = _mapping(data.get("metrics"))
    reasons: Counter[str] = Counter()
    order_approvals = 0
    order_denials = 0
    for order in _sequence(data.get("orders")):
        risk = _mapping(_mapping(order).get("risk_decision"))
        if not risk:
            continue
        if risk.get("approved") is True:
            order_approvals += 1
        else:
            order_denials += 1
            reasons[_reason_bucket(_text(risk.get("reason")))] += 1
    approvals = _first_int(
        metrics.get("risk_approval_count"),
        _sum_samples(data, "risk_approved"),
        order_approvals,
    )
    denials = _first_int(
        data.get("risk_rejections"),
        metrics.get("risk_denial_count"),
        metrics.get("risk_rejection_count"),
        _sum_samples(data, "risk_rejected"),
        order_denials,
    )
    max_position = _max_abs_decimal(
        [
            metrics.get("paper_position"),
            *(_mapping(sample).get("paper_position") for sample in _sequence(data.get("samples"))),
        ]
    )
    max_exposure = _max_abs_decimal(
        [
            metrics.get("paper_exposure"),
            metrics.get("max_simulated_exposure"),
            max_position,
        ]
    )
    risk_limit = _first_decimal(metrics.get("max_position_limit"), data.get("max_position_limit"))
    utilization = None
    if risk_limit is not None and risk_limit > 0:
        utilization = (max_position / risk_limit).quantize(Decimal("0.0001"))
    elif max_position:
        utilization = (max_position / Decimal("100")).quantize(Decimal("0.0001"))
    return ExtendedRiskMetrics(
        approvals=approvals,
        denials=denials,
        denial_reasons=dict(reasons),
        max_simulated_exposure=max_exposure,
        max_simulated_position=max_position,
        risk_limit_utilization=utilization,
    )


def _execution_metrics(data: Mapping[str, Any]) -> ExtendedExecutionMetrics:
    metrics = _mapping(data.get("metrics"))
    orders = _sequence(data.get("orders"))
    order_count = _first_int(
        data.get("orders_created"),
        metrics.get("paper_order_count"),
        _sum_samples(data, "paper_orders"),
        len(orders),
    )
    filled_status_count = 0
    partial_count = 0
    slippages: list[Decimal] = []
    for order in orders:
        order_map = _mapping(order)
        intent = _mapping(order_map.get("intent"))
        paper_order = _mapping(order_map.get("order"))
        status = str(paper_order.get("status", "")).upper()
        if status == "FILLED":
            filled_status_count += 1
        if status == "PARTIALLY_FILLED":
            partial_count += 1
        intent_price = _first_decimal(intent.get("price"))
        fill_price = _first_decimal(paper_order.get("avg_fill_price"))
        if intent_price is not None and fill_price is not None:
            slippages.append(fill_price - intent_price)
    fill_count = _first_int(
        data.get("fills_created"),
        metrics.get("paper_fill_count"),
        _sum_samples(data, "paper_fills"),
        filled_status_count,
    )
    missed = max(order_count - fill_count - partial_count, 0)
    adverse = _first_decimal(metrics.get("adverse_selection_proxy"))
    return ExtendedExecutionMetrics(
        paper_order_count=order_count,
        paper_fill_count=fill_count,
        fill_ratio=_rate(fill_count, order_count),
        missed_fill_count=missed,
        partial_fill_count=partial_count,
        average_simulated_slippage=_average(tuple(slippages)) if slippages else None,
        adverse_selection_proxy=adverse,
    )


def _pnl_metrics(
    data: Mapping[str, Any],
    execution: ExtendedExecutionMetrics,
) -> ExtendedPnLMetrics:
    metrics = _mapping(data.get("metrics"))
    portfolio = _mapping(data.get("portfolio"))
    realized = _first_decimal(
        data.get("realized_pnl"),
        metrics.get("paper_realized_pnl"),
        portfolio.get("realized_pnl"),
    ) or Decimal("0")
    unrealized = _first_decimal(
        metrics.get("paper_unrealized_pnl"),
        portfolio.get("unrealized_pnl"),
    ) or Decimal("0")
    total = _first_decimal(metrics.get("paper_total_pnl"), portfolio.get("total_pnl"))
    if total is None:
        total = realized + unrealized
    equity_curve = _equity_curve(data)
    drawdown = _first_decimal(metrics.get("max_drawdown"))
    calculated_drawdown = _max_drawdown(equity_curve)
    if drawdown is None or calculated_drawdown < drawdown:
        drawdown = calculated_drawdown
    trade_pnls = _trade_pnls(data)
    if not trade_pnls and execution.paper_fill_count > 0:
        trade_pnls = [total]
    win_count = sum(1 for value in trade_pnls if value > 0)
    loss_count = sum(1 for value in trade_pnls if value < 0)
    denominator = len(trade_pnls) or execution.paper_fill_count
    return ExtendedPnLMetrics(
        realized_pnl=realized,
        unrealized_pnl=unrealized,
        total_pnl=total,
        max_drawdown=drawdown or Decimal("0"),
        win_count=win_count,
        loss_count=loss_count,
        average_pnl_per_simulated_trade=_divide_optional(total, denominator),
    )


def _calibration_metrics(data: Mapping[str, Any]) -> ExtendedCalibrationMetrics:
    points = _calibration_points(data)
    if not points:
        return ExtendedCalibrationMetrics(
            brier_score=None,
            probability_buckets=_probability_buckets(()),
            outcome_warning="outcomes are not available; calibration metrics are limited",
        )
    errors = tuple((probability - outcome) ** 2 for probability, outcome in points)
    return ExtendedCalibrationMetrics(
        brier_score=_average(errors),
        probability_buckets=_probability_buckets(tuple(points)),
        outcome_warning=None,
    )


def _warnings(
    signals: ExtendedSignalMetrics,
    execution: ExtendedExecutionMetrics,
    calibration: ExtendedCalibrationMetrics,
) -> tuple[str, ...]:
    warnings: list[str] = []
    if signals.intent_count == 0:
        warnings.append("no strategy intents were found")
    if execution.paper_order_count == 0:
        warnings.append("no paper orders were found")
    if calibration.outcome_warning is not None:
        warnings.append(calibration.outcome_warning)
    return tuple(warnings)


def _classify(
    signals: ExtendedSignalMetrics,
    warnings: tuple[str, ...],
) -> ExtendedEvaluationStatus:
    if signals.intent_count == 0:
        return "EXTENDED_EVALUATION_NO_DATA"
    if warnings:
        return "EXTENDED_EVALUATION_WARNING"
    return "EXTENDED_EVALUATION_READY"


def _side_counts(orders: list[object], items: list[object]) -> tuple[int, int]:
    buy_count = 0
    sell_count = 0
    for source in (*orders, *items):
        source_map = _mapping(source)
        intent = _mapping(source_map.get("intent")) or source_map
        side = _text(intent.get("side"))
        if side == "BUY":
            buy_count += 1
        elif side == "SELL":
            sell_count += 1
    return buy_count, sell_count


def _collect_decimals(
    keys: tuple[str, ...],
    orders: list[object],
    items: list[object],
) -> list[Decimal]:
    values: list[Decimal] = []
    for source in (*orders, *items):
        source_map = _mapping(source)
        intent = _mapping(source_map.get("intent")) or source_map
        for key in keys:
            parsed = _first_decimal(intent.get(key))
            if parsed is not None:
                values.append(parsed)
                break
    return values


def _equity_curve(data: Mapping[str, Any]) -> list[Decimal]:
    values = [Decimal("0")]
    for sample in _sequence(data.get("samples")):
        sample_map = _mapping(sample)
        value = _first_decimal(sample_map.get("paper_total_pnl"), sample_map.get("total_pnl"))
        if value is not None:
            values.append(value)
    for event in _sequence(data.get("events")):
        event_map = _mapping(event)
        value = _first_decimal(event_map.get("paper_total_pnl"), event_map.get("total_pnl"))
        if value is not None:
            values.append(value)
    return values


def _trade_pnls(data: Mapping[str, Any]) -> list[Decimal]:
    values: list[Decimal] = []
    for key in ("trades", "fills", "orders"):
        for item in _sequence(data.get(key)):
            item_map = _mapping(item)
            order = _mapping(item_map.get("order"))
            value = _first_decimal(
                item_map.get("pnl"),
                item_map.get("paper_pnl"),
                order.get("pnl"),
                order.get("paper_pnl"),
            )
            if value is not None:
                values.append(value)
    return values


def _calibration_points(data: Mapping[str, Any]) -> list[tuple[Decimal, Decimal]]:
    points: list[tuple[Decimal, Decimal]] = []
    for source in (
        *_sequence(data.get("items")),
        *_sequence(data.get("events")),
        *_sequence(data.get("orders")),
    ):
        source_map = _mapping(source)
        intent = _mapping(source_map.get("intent")) or source_map
        probability = _first_decimal(
            intent.get("p_model"),
            intent.get("probability"),
            intent.get("confidence"),
        )
        outcome = _first_decimal(
            intent.get("outcome"),
            intent.get("realized_outcome"),
            source_map.get("outcome"),
            source_map.get("realized_outcome"),
        )
        if probability is not None and outcome is not None:
            points.append((probability, outcome))
    return points


def _probability_buckets(
    points: tuple[tuple[Decimal, Decimal], ...],
) -> tuple[dict[str, int | str | None], ...]:
    buckets: list[dict[str, int | str | None]] = []
    for index in range(10):
        lower = Decimal(index) / Decimal("10")
        upper = Decimal(index + 1) / Decimal("10")
        bucket_points = [
            point
            for point in points
            if lower <= point[0] < upper or (index == 9 and point[0] == 1)
        ]
        hit_rate = _average(tuple(point[1] for point in bucket_points)) if bucket_points else None
        buckets.append(
            {
                "bucket": f"{lower:.1f}-{upper:.1f}",
                "bucket_hit_rate": _optional_decimal(hit_rate),
                "count": len(bucket_points),
            }
        )
    return tuple(buckets)


def _reason_bucket(reason: str | None) -> str:
    text = (reason or "").lower()
    if "notional" in text:
        return "max_notional"
    if "position" in text:
        return "position"
    if "stale" in text:
        return "stale_data"
    if "kill" in text:
        return "kill_switch"
    if "live" in text:
        return "live_guard"
    return "other"


def _flatten_number_sources(values: list[object]) -> list[Decimal]:
    return [parsed for value in values if (parsed := _first_decimal(value)) is not None]


def _max_abs_decimal(values: list[object]) -> Decimal:
    parsed = _flatten_number_sources(values)
    if not parsed:
        return Decimal("0")
    return max(abs(value) for value in parsed)


def _first_int(*values: object) -> int:
    for value in values:
        parsed = _int_or_none(value)
        if parsed is not None:
            return parsed
    return 0


def _int_or_none(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    return None


def _sum_samples(data: Mapping[str, Any], key: str) -> int | None:
    values = [
        value
        for sample in _sequence(data.get("samples"))
        if (value := _int_or_none(_mapping(sample).get(key))) is not None
    ]
    return sum(values) if values else None


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _sequence(value: object) -> list[object]:
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    return []


def _text(value: object) -> str | None:
    return value.upper() if isinstance(value, str) and value else None


def _first_decimal(*values: object) -> Decimal | None:
    for value in values:
        if value is None or isinstance(value, bool):
            continue
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            continue
    return None


def _rate(numerator: int, denominator: int) -> Decimal:
    if denominator <= 0:
        return Decimal("0")
    return (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("0.0001"))


def _average(values: tuple[Decimal, ...]) -> Decimal:
    if not values:
        return Decimal("0")
    return (sum(values, Decimal("0")) / Decimal(len(values))).quantize(Decimal("0.0001"))


def _divide_optional(value: Decimal, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return (value / Decimal(denominator)).quantize(Decimal("0.0001"))


def _max_drawdown(values: list[Decimal]) -> Decimal:
    if not values:
        return Decimal("0")
    peak = values[0]
    max_drawdown = Decimal("0")
    for value in values:
        peak = max(peak, value)
        max_drawdown = min(max_drawdown, value - peak)
    return max_drawdown


def _decimal_to_str(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _optional_decimal(value: Decimal | None) -> str | None:
    return None if value is None else _decimal_to_str(value)


def _table(payload: Mapping[str, object]) -> str:
    return "\n".join(f"| {key} | {value} |" for key, value in sorted(payload.items()))


def _html_table(payload: Mapping[str, object]) -> str:
    rows = "".join(
        "<tr>"
        f"<th>{escape(str(key))}</th>"
        f"<td>{escape(str(value))}</td>"
        "</tr>"
        for key, value in sorted(payload.items())
    )
    return f"<table>{rows}</table>"


def _contains_sensitive_pattern(text: str) -> bool:
    return bool(_ADDRESS_RE.search(text) or _TX_HASH_RE.search(text))


__all__ = [
    "ExtendedStrategyEvaluationConfig",
    "ExtendedStrategyEvaluationError",
    "ExtendedStrategyEvaluationReport",
    "build_extended_strategy_evaluation",
    "extended_strategy_evaluation_filename",
    "load_extended_strategy_input",
    "render_extended_strategy_evaluation",
    "render_extended_strategy_evaluation_html",
    "render_extended_strategy_evaluation_markdown",
    "write_extended_strategy_evaluation_reports",
]
