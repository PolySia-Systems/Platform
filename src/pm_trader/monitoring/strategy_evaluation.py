from __future__ import annotations

import json
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
StrategyClassification = Literal[
    "STRATEGY_RESEARCH_ONLY",
    "STRATEGY_READY_FOR_SHADOW",
    "STRATEGY_READY_FOR_TINY_LIVE_REVIEW",
    "STRATEGY_NOT_READY",
]


class StrategyEvaluationError(RuntimeError):
    """Raised when strategy evaluation input cannot be read or parsed."""


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class StrategyEvaluationConfig:
    input_path: Path | None
    strategy: str = "stale-price"
    min_sample_size: int = 30

    def __post_init__(self) -> None:
        if not self.strategy:
            raise ValueError("strategy must not be empty")
        if self.min_sample_size <= 0:
            raise ValueError("min_sample_size must be positive")


@dataclass(frozen=True, slots=True)
class CalibrationBucket:
    bucket: str
    count: int
    average_probability: Decimal | None
    realized_rate: Decimal | None

    def to_dict(self) -> dict[str, int | str | None]:
        return {
            "average_probability": _optional_decimal(self.average_probability),
            "bucket": self.bucket,
            "count": self.count,
            "realized_rate": _optional_decimal(self.realized_rate),
        }


@dataclass(frozen=True, slots=True)
class SignalQuality:
    total_signals: int
    approved_signals: int
    rejected_signals: int
    approval_rate: Decimal
    rejection_rate: Decimal
    average_estimated_edge: Decimal | None
    signal_reasons: dict[str, int]

    def to_dict(self) -> dict[str, object]:
        return {
            "approval_rate": _decimal_to_str(self.approval_rate),
            "approved_signals": self.approved_signals,
            "average_estimated_edge": _optional_decimal(self.average_estimated_edge),
            "rejected_signals": self.rejected_signals,
            "rejection_rate": _decimal_to_str(self.rejection_rate),
            "signal_reasons": dict(sorted(self.signal_reasons.items())),
            "total_signals": self.total_signals,
        }


@dataclass(frozen=True, slots=True)
class ExecutionQuality:
    paper_order_count: int
    paper_fill_count: int
    paper_fill_rate: Decimal
    average_simulated_slippage: Decimal | None
    adverse_selection_proxy: Decimal | None
    average_holding_time_seconds: Decimal | None

    def to_dict(self) -> dict[str, int | str | None]:
        return {
            "adverse_selection_proxy": _optional_decimal(self.adverse_selection_proxy),
            "average_holding_time_seconds": _optional_decimal(
                self.average_holding_time_seconds
            ),
            "average_simulated_slippage": _optional_decimal(
                self.average_simulated_slippage
            ),
            "paper_fill_count": self.paper_fill_count,
            "paper_fill_rate": _decimal_to_str(self.paper_fill_rate),
            "paper_order_count": self.paper_order_count,
        }


@dataclass(frozen=True, slots=True)
class PnLQuality:
    total_paper_pnl: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    max_drawdown: Decimal
    pnl_per_signal: Decimal | None
    pnl_per_approved_signal: Decimal | None
    win_rate: Decimal | None
    profit_factor: Decimal | None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "max_drawdown": _decimal_to_str(self.max_drawdown),
            "pnl_per_approved_signal": _optional_decimal(
                self.pnl_per_approved_signal
            ),
            "pnl_per_signal": _optional_decimal(self.pnl_per_signal),
            "profit_factor": _optional_decimal(self.profit_factor),
            "realized_pnl": _decimal_to_str(self.realized_pnl),
            "total_paper_pnl": _decimal_to_str(self.total_paper_pnl),
            "unrealized_pnl": _decimal_to_str(self.unrealized_pnl),
            "win_rate": _optional_decimal(self.win_rate),
        }


@dataclass(frozen=True, slots=True)
class RiskQuality:
    risk_rejection_count: int
    rejection_reasons: dict[str, int]
    stale_data_blocks: int
    kill_switch_blocks: int
    max_notional_blocks: int
    max_position_blocks: int

    def to_dict(self) -> dict[str, int | dict[str, int]]:
        return {
            "kill_switch_blocks": self.kill_switch_blocks,
            "max_notional_blocks": self.max_notional_blocks,
            "max_position_blocks": self.max_position_blocks,
            "rejection_reasons": dict(sorted(self.rejection_reasons.items())),
            "risk_rejection_count": self.risk_rejection_count,
            "stale_data_blocks": self.stale_data_blocks,
        }


@dataclass(frozen=True, slots=True)
class CalibrationQuality:
    brier_score: Decimal | None
    buckets: tuple[CalibrationBucket, ...]
    small_sample_warning: bool
    confidence_vs_realized: Decimal | None

    def to_dict(self) -> dict[str, object]:
        return {
            "brier_score": _optional_decimal(self.brier_score),
            "buckets": [bucket.to_dict() for bucket in self.buckets],
            "confidence_vs_realized": _optional_decimal(self.confidence_vs_realized),
            "small_sample_warning": self.small_sample_warning,
        }


@dataclass(frozen=True, slots=True)
class StrategyEvaluationReport:
    timestamp: datetime
    strategy: str
    input_path: str | None
    classification: StrategyClassification
    warnings: tuple[str, ...]
    reasons: tuple[str, ...]
    signal_quality: SignalQuality
    execution_quality: ExecutionQuality
    pnl_quality: PnLQuality
    risk_quality: RiskQuality
    calibration: CalibrationQuality

    def to_dict(self) -> dict[str, object]:
        return {
            "calibration": self.calibration.to_dict(),
            "classification": self.classification,
            "execution_quality": self.execution_quality.to_dict(),
            "formulas": {
                "brier_score": "mean((p_model - outcome)^2)",
                "expected_value": "p_model - execution_price - cost_buffer",
            },
            "input_path": self.input_path,
            "pnl_quality": self.pnl_quality.to_dict(),
            "reasons": list(self.reasons),
            "risk_quality": self.risk_quality.to_dict(),
            "signal_quality": self.signal_quality.to_dict(),
            "strategy": self.strategy,
            "timestamp": self.timestamp.isoformat(),
            "warnings": list(self.warnings),
        }


def build_strategy_evaluation(
    config: StrategyEvaluationConfig,
    *,
    clock: Clock = utc_now,
) -> StrategyEvaluationReport:
    """Evaluate strategy outputs from backtest, shadow, audit, or JSONL data."""

    records = load_strategy_records(config.input_path)
    flattened = _flatten_records(records)
    signal_quality = _signal_quality(flattened)
    execution_quality = _execution_quality(flattened, signal_quality)
    pnl_quality = _pnl_quality(flattened, signal_quality)
    risk_quality = _risk_quality(flattened, signal_quality)
    calibration = _calibration_quality(
        flattened,
        min_sample_size=config.min_sample_size,
    )
    classification, reasons, warnings = classify_strategy_evaluation(
        signal_quality=signal_quality,
        execution_quality=execution_quality,
        pnl_quality=pnl_quality,
        risk_quality=risk_quality,
        calibration=calibration,
        min_sample_size=config.min_sample_size,
    )
    return StrategyEvaluationReport(
        timestamp=clock(),
        strategy=config.strategy,
        input_path=str(config.input_path) if config.input_path is not None else None,
        classification=classification,
        warnings=warnings,
        reasons=reasons,
        signal_quality=signal_quality,
        execution_quality=execution_quality,
        pnl_quality=pnl_quality,
        risk_quality=risk_quality,
        calibration=calibration,
    )


def load_strategy_records(path: Path | None) -> object:
    if path is None:
        default = Path("release-artifacts") / "shadow_run.json"
        if default.is_file():
            path = default
        else:
            return {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise StrategyEvaluationError(f"could not read input file: {path}") from error

    if path.suffix.lower() == ".jsonl":
        records: list[object] = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                records.append(json.loads(stripped))
            except json.JSONDecodeError as error:
                raise StrategyEvaluationError(
                    f"invalid JSONL on line {line_number}"
                ) from error
        return records

    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise StrategyEvaluationError("input must be valid JSON or JSONL") from error


def classify_strategy_evaluation(
    *,
    signal_quality: SignalQuality,
    execution_quality: ExecutionQuality,
    pnl_quality: PnLQuality,
    risk_quality: RiskQuality,
    calibration: CalibrationQuality,
    min_sample_size: int,
) -> tuple[StrategyClassification, tuple[str, ...], tuple[str, ...]]:
    warnings: list[str] = []
    if signal_quality.total_signals < min_sample_size:
        warnings.append(
            f"sample size {signal_quality.total_signals} is below minimum {min_sample_size}"
        )
    if calibration.small_sample_warning:
        warnings.append("calibration sample is too small")

    if signal_quality.total_signals == 0:
        return (
            "STRATEGY_NOT_READY",
            ("no strategy signals were found in the input",),
            tuple(warnings),
        )
    if signal_quality.approved_signals == 0:
        return (
            "STRATEGY_NOT_READY",
            ("risk engine approved no signals",),
            tuple(warnings),
        )
    if signal_quality.total_signals < min_sample_size:
        return (
            "STRATEGY_RESEARCH_ONLY",
            ("sample size is too small for readiness decisions",),
            tuple(warnings),
        )
    if execution_quality.paper_fill_count == 0:
        return (
            "STRATEGY_READY_FOR_SHADOW",
            ("signals exist, but no paper fills were available for execution review",),
            tuple(warnings),
        )
    if pnl_quality.total_paper_pnl < Decimal("0") or risk_quality.kill_switch_blocks > 0:
        return (
            "STRATEGY_READY_FOR_SHADOW",
            ("paper results need more shadow review before tiny-live review",),
            tuple(warnings),
        )
    return (
        "STRATEGY_READY_FOR_TINY_LIVE_REVIEW",
        ("strategy evaluation is suitable for human tiny-live review only",),
        tuple(warnings),
    )


def render_strategy_evaluation_json(report: StrategyEvaluationReport) -> str:
    return json.dumps(report.to_dict(), indent=2, sort_keys=True)


def render_strategy_evaluation_markdown(report: StrategyEvaluationReport) -> str:
    warnings = "\n".join(f"- {warning}" for warning in report.warnings) or "- None"
    reasons = "\n".join(f"- {reason}" for reason in report.reasons) or "- None"
    return "\n".join(
        (
            "# Polymarket Strategy Evaluation",
            "",
            f"- Classification: {report.classification}",
            f"- Generated at: {report.timestamp.isoformat()}",
            f"- Strategy: {report.strategy}",
            "",
            "## Reasons",
            "",
            reasons,
            "",
            "## Warnings",
            "",
            warnings,
            "",
            "## Signal Quality",
            "",
            _table(report.signal_quality.to_dict()),
            "",
            "## Execution Quality",
            "",
            _table(report.execution_quality.to_dict()),
            "",
            "## PnL Quality",
            "",
            _table(report.pnl_quality.to_dict()),
            "",
            "## Risk Quality",
            "",
            _table(report.risk_quality.to_dict()),
            "",
            "## Calibration",
            "",
            _table(report.calibration.to_dict()),
            "",
            "## Copy-Friendly Formulas",
            "",
            "- `brier_score = mean((p_model - outcome)^2)`",
            "- `expected_value = p_model - execution_price - cost_buffer`",
            "",
            "## Live Trading",
            "",
            "No live trading is approved or enabled by this evaluation.",
            "",
        )
    )


def render_strategy_evaluation_html(report: StrategyEvaluationReport) -> str:
    warning_items = "".join(
        f"<li>{escape(warning)}</li>" for warning in report.warnings
    ) or "<li>None</li>"
    reason_items = "".join(
        f"<li>{escape(reason)}</li>" for reason in report.reasons
    ) or "<li>None</li>"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Polymarket Strategy Evaluation</title>
  <style>
    body {{ margin: 0; font-family: Arial, Helvetica, sans-serif; color: #1f2933; }}
    main {{ max-width: 980px; margin: 0 auto; padding: 28px 18px; }}
    h1 {{ margin: 0 0 8px; font-size: 28px; letter-spacing: 0; }}
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
    <h1>Polymarket Strategy Evaluation</h1>
    <p>{escape(report.timestamp.isoformat())}</p>
    <div class="badge">{escape(report.classification)}</div>
    <h2>Reasons</h2>
    <ul>{reason_items}</ul>
    <h2>Warnings</h2>
    <ul>{warning_items}</ul>
    <section><h2>Signal Quality</h2>{_html_table(report.signal_quality.to_dict())}</section>
    <section><h2>Execution Quality</h2>{_html_table(report.execution_quality.to_dict())}</section>
    <section><h2>PnL Quality</h2>{_html_table(report.pnl_quality.to_dict())}</section>
    <section><h2>Risk Quality</h2>{_html_table(report.risk_quality.to_dict())}</section>
    <section><h2>Calibration</h2>{_html_table(report.calibration.to_dict())}</section>
    <section>
      <h2>Formulas</h2>
      <p><code>brier_score = mean((p_model - outcome)^2)</code></p>
      <p><code>expected_value = p_model - execution_price - cost_buffer</code></p>
      <p>No live trading is approved or enabled by this evaluation.</p>
    </section>
  </main>
</body>
</html>
"""


def render_strategy_evaluation(
    report: StrategyEvaluationReport,
    report_format: ReportFormat,
) -> str:
    if report_format == "json":
        return render_strategy_evaluation_json(report)
    if report_format == "markdown":
        return render_strategy_evaluation_markdown(report)
    return render_strategy_evaluation_html(report)


def _flatten_records(value: object) -> dict[str, Any]:
    if isinstance(value, list):
        return {"items": value}
    if isinstance(value, dict):
        return dict(value)
    raise StrategyEvaluationError("input root must be a JSON object or JSONL records")


def _signal_quality(data: Mapping[str, Any]) -> SignalQuality:
    total = _int_value(data, "intents_generated") or _metric_int(
        data, "strategy_intent_count"
    ) or _sample_sum(data, "strategy_intents")
    orders = _sequence(data.get("orders"))
    if orders:
        total = max(total, len(orders))
    approved = _metric_int(data, "risk_approval_count") or _sample_sum(
        data, "risk_approved"
    )
    rejected = _int_value(data, "risk_rejections") or _metric_int(
        data, "risk_rejection_count"
    ) or _sample_sum(data, "risk_rejected")
    reason_counts: Counter[str] = Counter()
    edges: list[Decimal] = []

    for order in orders:
        order_map = _mapping(order)
        intent = _mapping(order_map.get("intent"))
        reason = _text(intent.get("reason")) or "unknown"
        reason_counts[reason] += 1
        edge = _first_decimal(intent.get("edge"), intent.get("estimated_edge"))
        if edge is not None:
            edges.append(edge)
        risk = _mapping(order_map.get("risk_decision"))
        if risk:
            if bool(risk.get("approved")):
                approved += 1
            else:
                rejected += 1

    if total == 0 and approved + rejected > 0:
        total = approved + rejected
    if total > 0 and approved == 0 and rejected == 0:
        approved = max(0, total - rejected)
    return SignalQuality(
        total_signals=total,
        approved_signals=approved,
        rejected_signals=rejected,
        approval_rate=_rate(approved, total),
        rejection_rate=_rate(rejected, total),
        average_estimated_edge=_average(tuple(edges)) if edges else None,
        signal_reasons=dict(reason_counts),
    )


def _execution_quality(data: Mapping[str, Any], signal: SignalQuality) -> ExecutionQuality:
    order_count = _int_value(data, "orders_created") or _metric_int(
        data, "paper_order_count"
    ) or _sample_sum(data, "paper_orders")
    fill_count = _int_value(data, "fills_created") or _metric_int(
        data, "paper_fill_count"
    ) or _sample_sum(data, "paper_fills")
    slippages: list[Decimal] = []
    for order in _sequence(data.get("orders")):
        order_map = _mapping(order)
        intent = _mapping(order_map.get("intent"))
        paper_order = _mapping(order_map.get("order"))
        intent_price = _decimal_or_none(intent.get("price"))
        fill_price = _decimal_or_none(paper_order.get("avg_fill_price"))
        if intent_price is not None and fill_price is not None:
            slippages.append(fill_price - intent_price)
    return ExecutionQuality(
        paper_order_count=order_count,
        paper_fill_count=fill_count,
        paper_fill_rate=_rate(fill_count, max(order_count, signal.approved_signals)),
        average_simulated_slippage=_average(tuple(slippages)) if slippages else None,
        adverse_selection_proxy=None,
        average_holding_time_seconds=None,
    )


def _pnl_quality(data: Mapping[str, Any], signal: SignalQuality) -> PnLQuality:
    metrics = _mapping(data.get("metrics"))
    portfolio = _mapping(data.get("portfolio"))
    realized = (
        _first_decimal(
            data.get("realized_pnl"),
            metrics.get("paper_realized_pnl"),
            portfolio.get("realized_pnl"),
        )
        or Decimal("0")
    )
    unrealized = (
        _first_decimal(
            metrics.get("paper_unrealized_pnl"),
            portfolio.get("unrealized_pnl"),
        )
        or Decimal("0")
    )
    total = _first_decimal(
        metrics.get("paper_total_pnl"),
        metrics.get("paper_pnl"),
    )
    if total is None:
        total = realized + unrealized
    max_drawdown = _first_decimal(metrics.get("max_drawdown"))
    if max_drawdown is None:
        max_drawdown = Decimal("0")
    samples = _sequence(data.get("samples"))
    sample_pnls = [
        pnl
        for sample in samples
        if (pnl := _decimal_or_none(_mapping(sample).get("paper_total_pnl"))) is not None
    ]
    if sample_pnls:
        max_drawdown = min(max_drawdown, _max_drawdown([Decimal("0"), *sample_pnls]))
    return PnLQuality(
        total_paper_pnl=total,
        realized_pnl=realized,
        unrealized_pnl=unrealized,
        max_drawdown=max_drawdown,
        pnl_per_signal=_divide_optional(total, signal.total_signals),
        pnl_per_approved_signal=_divide_optional(total, signal.approved_signals),
        win_rate=None,
        profit_factor=None,
    )


def _risk_quality(data: Mapping[str, Any], signal: SignalQuality) -> RiskQuality:
    reasons: Counter[str] = Counter()
    for order in _sequence(data.get("orders")):
        risk = _mapping(_mapping(order).get("risk_decision"))
        if risk and not bool(risk.get("approved")):
            reasons[_text(risk.get("reason")) or "unknown"] += 1
    stale = sum(count for reason, count in reasons.items() if "stale" in reason.lower())
    kill = sum(count for reason, count in reasons.items() if "kill" in reason.lower())
    notional = sum(count for reason, count in reasons.items() if "notional" in reason.lower())
    position = sum(count for reason, count in reasons.items() if "position" in reason.lower())
    return RiskQuality(
        risk_rejection_count=signal.rejected_signals,
        rejection_reasons=dict(reasons),
        stale_data_blocks=stale,
        kill_switch_blocks=kill,
        max_notional_blocks=notional,
        max_position_blocks=position,
    )


def _calibration_quality(
    data: Mapping[str, Any],
    *,
    min_sample_size: int,
) -> CalibrationQuality:
    points = _calibration_points(data)
    if not points:
        return CalibrationQuality(
            brier_score=None,
            buckets=(),
            small_sample_warning=True,
            confidence_vs_realized=None,
        )
    errors = [(probability - outcome) ** 2 for probability, outcome in points]
    brier = _average(tuple(errors))
    buckets = _calibration_buckets(points)
    average_probability = _average(tuple(point[0] for point in points))
    realized_rate = _average(tuple(point[1] for point in points))
    return CalibrationQuality(
        brier_score=brier,
        buckets=buckets,
        small_sample_warning=len(points) < min_sample_size,
        confidence_vs_realized=average_probability - realized_rate,
    )


def _calibration_points(data: Mapping[str, Any]) -> list[tuple[Decimal, Decimal]]:
    points: list[tuple[Decimal, Decimal]] = []
    for item in _sequence(data.get("items")):
        item_map = _mapping(item)
        probability = _first_decimal(
            item_map.get("p_model"),
            item_map.get("probability"),
            item_map.get("confidence"),
        )
        outcome = _first_decimal(
            item_map.get("outcome"),
            item_map.get("realized_outcome"),
        )
        if probability is not None and outcome is not None:
            points.append((probability, outcome))
    for order in _sequence(data.get("orders")):
        intent = _mapping(_mapping(order).get("intent"))
        probability = _first_decimal(
            intent.get("p_model"),
            intent.get("confidence"),
        )
        outcome = _first_decimal(
            intent.get("outcome"),
            intent.get("realized_outcome"),
        )
        if probability is not None and outcome is not None:
            points.append((probability, outcome))
    return points


def _calibration_buckets(
    points: list[tuple[Decimal, Decimal]],
) -> tuple[CalibrationBucket, ...]:
    buckets: list[CalibrationBucket] = []
    for index in range(10):
        lower = Decimal(index) / Decimal("10")
        upper = Decimal(index + 1) / Decimal("10")
        bucket_points = [
            point
            for point in points
            if lower <= point[0] < upper or (index == 9 and point[0] == 1)
        ]
        if not bucket_points:
            buckets.append(
                CalibrationBucket(
                    bucket=f"{lower:.1f}-{upper:.1f}",
                    count=0,
                    average_probability=None,
                    realized_rate=None,
                )
            )
            continue
        buckets.append(
            CalibrationBucket(
                bucket=f"{lower:.1f}-{upper:.1f}",
                count=len(bucket_points),
                average_probability=_average(tuple(point[0] for point in bucket_points)),
                realized_rate=_average(tuple(point[1] for point in bucket_points)),
            )
        )
    return tuple(buckets)


def _metric_int(data: Mapping[str, Any], key: str) -> int:
    return _int_value(_mapping(data.get("metrics")), key)


def _sample_sum(data: Mapping[str, Any], key: str) -> int:
    return sum(
        _int_from_value(_mapping(sample).get(key))
        for sample in _sequence(data.get("samples"))
    )


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _sequence(value: object) -> list[object]:
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    return []


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _int_value(data: Mapping[str, Any], key: str) -> int:
    return _int_from_value(data.get(key))


def _int_from_value(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    return 0


def _decimal_or_none(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _first_decimal(*values: object) -> Decimal | None:
    for value in values:
        decimal_value = _decimal_or_none(value)
        if decimal_value is not None:
            return decimal_value
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


def normalize_strategy_evaluation_formats(
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


def strategy_evaluation_filename(report_format: ReportFormat) -> str:
    return {
        "html": "strategy_evaluation.html",
        "json": "strategy_evaluation.json",
        "markdown": "strategy_evaluation.md",
    }[report_format]


__all__ = [
    "CalibrationBucket",
    "CalibrationQuality",
    "ExecutionQuality",
    "PnLQuality",
    "RiskQuality",
    "SignalQuality",
    "StrategyEvaluationConfig",
    "StrategyEvaluationError",
    "StrategyEvaluationReport",
    "build_strategy_evaluation",
    "classify_strategy_evaluation",
    "load_strategy_records",
    "normalize_strategy_evaluation_formats",
    "render_strategy_evaluation",
    "render_strategy_evaluation_html",
    "render_strategy_evaluation_json",
    "render_strategy_evaluation_markdown",
    "strategy_evaluation_filename",
]
