from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from html import escape
from pathlib import Path
from typing import Any, Literal, cast

from polysia.execution.intents import OrderSide

Clock = Callable[[], datetime]
FillModelName = Literal["conservative", "top-of-book", "queue-aware"]
ReportFormat = Literal["json", "markdown", "html"]
FillModelClassification = Literal[
    "FILL_MODEL_CONSERVATIVE_OK",
    "FILL_MODEL_NEEDS_MORE_DATA",
    "FILL_MODEL_TOO_OPTIMISTIC",
    "FILL_MODEL_NOT_READY",
]


class FillSimulationAuditError(RuntimeError):
    """Raised when fill simulation audit input cannot be parsed."""


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class FillSimulationAuditConfig:
    input_path: Path | None
    strategy: str = "stale-price"
    models: tuple[FillModelName, ...] = (
        "conservative",
        "top-of-book",
        "queue-aware",
    )
    queue_penalty: Decimal = Decimal("0.50")

    def __post_init__(self) -> None:
        if not self.strategy:
            raise ValueError("strategy must not be empty")
        if not self.models:
            raise ValueError("at least one fill model is required")
        if self.queue_penalty < Decimal("0") or self.queue_penalty >= Decimal("1"):
            raise ValueError("queue_penalty must be in [0, 1)")


@dataclass(frozen=True, slots=True)
class SimulatedOrderSpec:
    order_id: str
    token_id: str
    side: OrderSide
    limit_price: Decimal
    size: Decimal
    best_bid: Decimal | None
    best_ask: Decimal | None
    bid_depth: Decimal
    ask_depth: Decimal
    reference_mid: Decimal | None
    time_to_fill_seconds: Decimal | None = None

    def visible_depth(self) -> Decimal:
        return self.ask_depth if self.side == "BUY" else self.bid_depth

    def top_price(self) -> Decimal | None:
        return self.best_ask if self.side == "BUY" else self.best_bid


@dataclass(frozen=True, slots=True)
class SimulatedFill:
    order_id: str
    model: FillModelName
    side: OrderSide
    requested_size: Decimal
    filled_size: Decimal
    fill_price: Decimal | None
    slippage: Decimal | None
    paper_pnl: Decimal
    status: Literal["filled", "partial", "missed"]
    reason: str
    time_to_fill_seconds: Decimal | None

    def to_dict(self) -> dict[str, object]:
        return {
            "fill_price": _optional_decimal(self.fill_price),
            "filled_size": _decimal_to_str(self.filled_size),
            "model": self.model,
            "order_id": self.order_id,
            "paper_pnl": _decimal_to_str(self.paper_pnl),
            "reason": self.reason,
            "requested_size": _decimal_to_str(self.requested_size),
            "side": self.side,
            "slippage": _optional_decimal(self.slippage),
            "status": self.status,
            "time_to_fill_seconds": _optional_decimal(self.time_to_fill_seconds),
        }


@dataclass(frozen=True, slots=True)
class FillModelMetrics:
    model: FillModelName
    simulated_order_count: int
    simulated_fill_count: int
    fill_rate: Decimal
    partial_fill_count: int
    missed_fill_count: int
    average_fill_price: Decimal | None
    average_slippage: Decimal | None
    max_slippage: Decimal | None
    average_time_to_fill_seconds: Decimal | None
    paper_pnl: Decimal
    conservatism_score: Decimal
    warning_too_optimistic: bool
    fills: tuple[SimulatedFill, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "average_fill_price": _optional_decimal(self.average_fill_price),
            "average_slippage": _optional_decimal(self.average_slippage),
            "average_time_to_fill_seconds": _optional_decimal(
                self.average_time_to_fill_seconds
            ),
            "conservatism_score": _decimal_to_str(self.conservatism_score),
            "fill_rate": _decimal_to_str(self.fill_rate),
            "fills": [fill.to_dict() for fill in self.fills],
            "max_slippage": _optional_decimal(self.max_slippage),
            "missed_fill_count": self.missed_fill_count,
            "model": self.model,
            "paper_pnl": _decimal_to_str(self.paper_pnl),
            "partial_fill_count": self.partial_fill_count,
            "simulated_fill_count": self.simulated_fill_count,
            "simulated_order_count": self.simulated_order_count,
            "warning_too_optimistic": self.warning_too_optimistic,
        }


@dataclass(frozen=True, slots=True)
class FillSimulationAuditReport:
    timestamp: datetime
    strategy: str
    input_file: str | None
    classification: FillModelClassification
    reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    models: tuple[FillModelMetrics, ...]
    pnl_difference_across_models: Decimal | None

    def to_dict(self) -> dict[str, object]:
        return {
            "classification": self.classification,
            "formulas": {
                "detrimental_slippage": "BUY: fill_price - mid; SELL: mid - fill_price",
                "paper_pnl": (
                    "BUY: (mid - fill_price) * filled_size; "
                    "SELL: (fill_price - mid) * filled_size"
                ),
            },
            "input_file": self.input_file,
            "models": [model.to_dict() for model in self.models],
            "pnl_difference_across_models": _optional_decimal(
                self.pnl_difference_across_models
            ),
            "reasons": list(self.reasons),
            "strategy": self.strategy,
            "timestamp": self.timestamp.isoformat(),
            "warnings": list(self.warnings),
        }


def build_fill_simulation_audit(
    config: FillSimulationAuditConfig,
    *,
    clock: Clock = utc_now,
) -> FillSimulationAuditReport:
    records = load_fill_simulation_records(config.input_path)
    orders = extract_simulated_orders(records)
    raw_metrics = tuple(
        _evaluate_model(
            model=model,
            orders=orders,
            queue_penalty=config.queue_penalty,
        )
        for model in config.models
    )
    metrics = _mark_optimistic_models(raw_metrics)
    classification, reasons, warnings = classify_fill_simulation(metrics)
    return FillSimulationAuditReport(
        timestamp=clock(),
        strategy=config.strategy,
        input_file=config.input_path.name if config.input_path is not None else None,
        classification=classification,
        reasons=reasons,
        warnings=warnings,
        models=metrics,
        pnl_difference_across_models=_pnl_difference(metrics),
    )


def load_fill_simulation_records(path: Path | None) -> object:
    if path is None:
        default = Path("release-artifacts") / "backtest_result.json"
        if default.is_file():
            path = default
        else:
            return {}

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise FillSimulationAuditError(f"could not read input file: {path}") from error

    if path.suffix.lower() == ".jsonl":
        records: list[object] = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                records.append(json.loads(stripped))
            except json.JSONDecodeError as error:
                raise FillSimulationAuditError(
                    f"invalid JSONL on line {line_number}"
                ) from error
        return records

    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise FillSimulationAuditError("input must be valid JSON or JSONL") from error


def extract_simulated_orders(records: object) -> tuple[SimulatedOrderSpec, ...]:
    data = _flatten_records(records)
    last_books = _mapping(data.get("last_books"))
    candidates = _candidate_order_records(data)
    orders: list[SimulatedOrderSpec] = []
    for index, candidate in enumerate(candidates, start=1):
        spec = _order_spec_from_record(
            candidate,
            index=index,
            last_books=last_books,
        )
        if spec is not None:
            orders.append(spec)
    return tuple(orders)


def classify_fill_simulation(
    metrics: tuple[FillModelMetrics, ...],
) -> tuple[FillModelClassification, tuple[str, ...], tuple[str, ...]]:
    warnings = [
        f"{metric.model} appears more optimistic than the conservative baseline"
        for metric in metrics
        if metric.warning_too_optimistic
    ]
    if not metrics:
        return (
            "FILL_MODEL_NOT_READY",
            ("no fill models were evaluated",),
            tuple(warnings),
        )
    order_count = max((metric.simulated_order_count for metric in metrics), default=0)
    if order_count == 0:
        return (
            "FILL_MODEL_NEEDS_MORE_DATA",
            ("no simulated orders with usable orderbook context were found",),
            tuple(warnings),
        )
    if warnings:
        return (
            "FILL_MODEL_TOO_OPTIMISTIC",
            ("one or more models fill more aggressively than the conservative baseline",),
            tuple(warnings),
        )
    conservative = next(
        (metric for metric in metrics if metric.model == "conservative"),
        None,
    )
    if conservative is not None and conservative.simulated_fill_count > 0:
        return (
            "FILL_MODEL_CONSERVATIVE_OK",
            ("conservative fill simulation produced fills without optimistic warnings",),
            tuple(warnings),
        )
    if any(metric.simulated_fill_count > 0 for metric in metrics):
        return (
            "FILL_MODEL_NEEDS_MORE_DATA",
            ("fills exist, but the conservative baseline was not available",),
            tuple(warnings),
        )
    return (
        "FILL_MODEL_NEEDS_MORE_DATA",
        ("all simulated orders missed; more marketable samples are required",),
        tuple(warnings),
    )


def render_fill_simulation_audit_json(report: FillSimulationAuditReport) -> str:
    return json.dumps(report.to_dict(), indent=2, sort_keys=True)


def render_fill_simulation_audit_markdown(report: FillSimulationAuditReport) -> str:
    reasons = "\n".join(f"- {reason}" for reason in report.reasons) or "- None"
    warnings = "\n".join(f"- {warning}" for warning in report.warnings) or "- None"
    model_sections = "\n\n".join(_model_markdown(model) for model in report.models)
    return "\n".join(
        (
            "# PolySia — Polymarket Adapter — Fill Simulation Audit",
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
            "## Models",
            "",
            model_sections or "No fill models were evaluated.",
            "",
            "## Formulas",
            "",
            "- `detrimental_slippage = BUY(fill_price - mid), SELL(mid - fill_price)`",
            "- `paper_pnl = BUY((mid - fill_price) * filled_size), "
            "SELL((fill_price - mid) * filled_size)`",
            "",
            "## Live Trading",
            "",
            "No live trading is approved, enabled, or executed by this audit.",
            "",
        )
    )


def render_fill_simulation_audit_html(report: FillSimulationAuditReport) -> str:
    reason_items = "".join(
        f"<li>{escape(reason)}</li>" for reason in report.reasons
    ) or "<li>None</li>"
    warning_items = "".join(
        f"<li>{escape(warning)}</li>" for warning in report.warnings
    ) or "<li>None</li>"
    model_sections = "".join(_model_html(model) for model in report.models)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PolySia — Polymarket Adapter — Fill Simulation Audit</title>
  <style>
    body {{ margin: 0; font-family: Arial, Helvetica, sans-serif; color: #1f2933; }}
    main {{ max-width: 980px; margin: 0 auto; padding: 28px 18px; }}
    h1 {{ margin: 0 0 8px; font-size: 28px; letter-spacing: 0; }}
    h2 {{ font-size: 18px; margin-top: 24px; letter-spacing: 0; }}
    .badge {{ display: inline-block; border-radius: 8px; padding: 8px 12px; color: #fff;
      background: #1f5f8b; font-weight: 700; }}
    section {{ border: 1px solid #d7dce0; border-radius: 8px; padding: 14px; margin-top: 12px; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border-top: 1px solid #d7dce0; padding: 9px 6px; text-align: left; }}
    tr:first-child th, tr:first-child td {{ border-top: 0; }}
    th {{ color: #687582; width: 44%; }}
  </style>
</head>
<body>
  <main>
    <h1>PolySia — Polymarket Adapter — Fill Simulation Audit</h1>
    <p>{escape(report.timestamp.isoformat())}</p>
    <div class="badge">{escape(report.classification)}</div>
    <h2>Reasons</h2>
    <ul>{reason_items}</ul>
    <h2>Warnings</h2>
    <ul>{warning_items}</ul>
    <h2>Models</h2>
    {model_sections or "<p>No fill models were evaluated.</p>"}
    <section>
      <h2>Live Trading</h2>
      <p>No live trading is approved, enabled, or executed by this audit.</p>
    </section>
  </main>
</body>
</html>
"""


def render_fill_simulation_audit(
    report: FillSimulationAuditReport,
    report_format: ReportFormat,
) -> str:
    if report_format == "json":
        return render_fill_simulation_audit_json(report)
    if report_format == "markdown":
        return render_fill_simulation_audit_markdown(report)
    return render_fill_simulation_audit_html(report)


def normalize_fill_report_formats(
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


def normalize_fill_models(values: tuple[str, ...] | list[str] | None) -> tuple[FillModelName, ...]:
    if not values:
        return ("conservative", "top-of-book", "queue-aware")
    models: list[FillModelName] = []
    for value in values:
        normalized = value.strip().lower()
        if normalized not in {"conservative", "top-of-book", "queue-aware"}:
            raise ValueError(
                "model must be one of conservative, top-of-book, or queue-aware"
            )
        model = cast(FillModelName, normalized)
        if model not in models:
            models.append(model)
    return tuple(models)


def fill_simulation_filename(report_format: ReportFormat) -> str:
    return {
        "html": "fill_simulation_audit.html",
        "json": "fill_simulation_audit.json",
        "markdown": "fill_simulation_audit.md",
    }[report_format]


def _evaluate_model(
    *,
    model: FillModelName,
    orders: tuple[SimulatedOrderSpec, ...],
    queue_penalty: Decimal,
) -> FillModelMetrics:
    fills = tuple(
        _simulate_order(model=model, order=order, queue_penalty=queue_penalty)
        for order in orders
    )
    filled = tuple(fill for fill in fills if fill.filled_size > Decimal("0"))
    partial_count = sum(1 for fill in filled if fill.status == "partial")
    missed_count = sum(1 for fill in fills if fill.status == "missed")
    slippages = tuple(
        fill.slippage for fill in filled if fill.slippage is not None
    )
    times = tuple(
        fill.time_to_fill_seconds
        for fill in filled
        if fill.time_to_fill_seconds is not None
    )
    paper_pnl = sum((fill.paper_pnl for fill in fills), Decimal("0"))
    missed_rate = _rate(missed_count, len(fills))
    partial_rate = _rate(partial_count, len(fills))
    average_slippage = _average(slippages) if slippages else None
    conservatism_score = (
        missed_rate
        + (partial_rate / Decimal("2"))
        + (average_slippage or Decimal("0"))
    ).quantize(Decimal("0.0001"))
    return FillModelMetrics(
        model=model,
        simulated_order_count=len(fills),
        simulated_fill_count=len(filled),
        fill_rate=_rate(len(filled), len(fills)),
        partial_fill_count=partial_count,
        missed_fill_count=missed_count,
        average_fill_price=_weighted_average_fill_price(filled),
        average_slippage=average_slippage,
        max_slippage=max(slippages) if slippages else None,
        average_time_to_fill_seconds=_average(times) if times else None,
        paper_pnl=paper_pnl.quantize(Decimal("0.0001")),
        conservatism_score=conservatism_score,
        warning_too_optimistic=False,
        fills=fills,
    )


def _simulate_order(
    *,
    model: FillModelName,
    order: SimulatedOrderSpec,
    queue_penalty: Decimal,
) -> SimulatedFill:
    top_price = order.top_price()
    depth = order.visible_depth()
    if top_price is None or depth <= Decimal("0"):
        return _missed_fill(order, model, "no visible top-of-book depth")

    if order.side == "BUY":
        crosses = order.limit_price >= top_price
    else:
        crosses = order.limit_price <= top_price
    if not crosses:
        return _missed_fill(order, model, "limit price did not cross top of book")

    available_depth = depth
    if model == "queue-aware":
        available_depth = (depth * (Decimal("1") - queue_penalty)).quantize(
            Decimal("0.0001")
        )
    filled_size = min(order.size, available_depth)
    if filled_size <= Decimal("0"):
        return _missed_fill(order, model, "queue penalty consumed visible depth")

    status: Literal["filled", "partial"] = (
        "filled" if filled_size == order.size else "partial"
    )
    reason = (
        "filled against top of book"
        if status == "filled"
        else "partially filled against visible top-of-book depth"
    )
    if model == "queue-aware":
        reason = f"{reason} after deterministic queue penalty"
    slippage = _slippage(order, top_price)
    return SimulatedFill(
        order_id=order.order_id,
        model=model,
        side=order.side,
        requested_size=order.size,
        filled_size=filled_size,
        fill_price=top_price,
        slippage=slippage,
        paper_pnl=_paper_pnl(order, fill_price=top_price, filled_size=filled_size),
        status=status,
        reason=reason,
        time_to_fill_seconds=order.time_to_fill_seconds,
    )


def _missed_fill(
    order: SimulatedOrderSpec,
    model: FillModelName,
    reason: str,
) -> SimulatedFill:
    return SimulatedFill(
        order_id=order.order_id,
        model=model,
        side=order.side,
        requested_size=order.size,
        filled_size=Decimal("0"),
        fill_price=None,
        slippage=None,
        paper_pnl=Decimal("0"),
        status="missed",
        reason=reason,
        time_to_fill_seconds=None,
    )


def _mark_optimistic_models(
    metrics: tuple[FillModelMetrics, ...],
) -> tuple[FillModelMetrics, ...]:
    conservative = next(
        (metric for metric in metrics if metric.model == "conservative"),
        None,
    )
    if conservative is None:
        return metrics

    conservative_slippage = conservative.average_slippage or Decimal("0")
    marked: list[FillModelMetrics] = []
    for metric in metrics:
        is_more_optimistic = False
        if metric.model != "conservative":
            if metric.fill_rate > conservative.fill_rate + Decimal("0.0500"):
                is_more_optimistic = True
            metric_slippage = metric.average_slippage or Decimal("0")
            if metric_slippage < conservative_slippage - Decimal("0.0100"):
                is_more_optimistic = True
        marked.append(replace(metric, warning_too_optimistic=is_more_optimistic))
    return tuple(marked)


def _candidate_order_records(data: Mapping[str, Any]) -> list[object]:
    if _sequence(data.get("orders")):
        return _sequence(data.get("orders"))
    if _sequence(data.get("items")):
        return _sequence(data.get("items"))
    if data.get("side") is not None or data.get("intent") is not None:
        return [dict(data)]
    return []


def _order_spec_from_record(
    record: object,
    *,
    index: int,
    last_books: Mapping[str, Any],
) -> SimulatedOrderSpec | None:
    raw = _mapping(record)
    intent = _mapping(raw.get("intent")) or raw
    order = _mapping(raw.get("order"))
    token_id = (
        _text(raw.get("token_id"))
        or _text(intent.get("token_id"))
        or _text(order.get("token_id"))
    )
    side = _side(
        _text(intent.get("side"))
        or _text(order.get("side"))
        or _text(raw.get("side"))
    )
    limit_price = _first_decimal(
        intent.get("price"),
        order.get("price"),
        raw.get("limit_price"),
        raw.get("price"),
    )
    size = _first_decimal(
        intent.get("size"),
        order.get("size"),
        raw.get("size"),
    )
    if token_id is None or side is None or limit_price is None or size is None:
        return None
    if size <= Decimal("0"):
        return None

    book = (
        _mapping(raw.get("book"))
        or _mapping(raw.get("orderbook"))
        or _mapping(raw.get("last_book"))
        or _mapping(last_books.get(token_id))
        or raw
    )
    best_bid, bid_depth = _best_level(book, side="BUY")
    best_ask, ask_depth = _best_level(book, side="SELL")
    if side == "BUY" and best_ask is None:
        return None
    if side == "SELL" and best_bid is None:
        return None

    reference_mid = _first_decimal(book.get("mid"), raw.get("mid"))
    if reference_mid is None and best_bid is not None and best_ask is not None:
        reference_mid = (best_bid + best_ask) / Decimal("2")
    return SimulatedOrderSpec(
        order_id=_text(raw.get("order_id"))
        or _text(order.get("order_id"))
        or f"sim-{index}",
        token_id=token_id,
        side=side,
        limit_price=limit_price,
        size=size,
        best_bid=best_bid,
        best_ask=best_ask,
        bid_depth=bid_depth,
        ask_depth=ask_depth,
        reference_mid=reference_mid,
        time_to_fill_seconds=_first_decimal(
            raw.get("time_to_fill_seconds"),
            order.get("time_to_fill_seconds"),
        ),
    )


def _best_level(
    book: Mapping[str, Any],
    *,
    side: Literal["BUY", "SELL"],
) -> tuple[Decimal | None, Decimal]:
    if side == "BUY":
        price = _first_decimal(book.get("best_bid"))
        depth = _first_decimal(book.get("bid_depth"))
        levels = _sequence(book.get("bids"))
    else:
        price = _first_decimal(book.get("best_ask"))
        depth = _first_decimal(book.get("ask_depth"))
        levels = _sequence(book.get("asks"))

    if (price is None or depth is None) and levels:
        level = _mapping(levels[0])
        price = price if price is not None else _first_decimal(level.get("price"))
        depth = depth if depth is not None else _first_decimal(level.get("size"))
    return price, depth or Decimal("0")


def _slippage(order: SimulatedOrderSpec, fill_price: Decimal) -> Decimal:
    reference = order.reference_mid or order.limit_price
    slippage = (
        fill_price - reference
        if order.side == "BUY"
        else reference - fill_price
    )
    return max(slippage, Decimal("0")).quantize(Decimal("0.0001"))


def _paper_pnl(
    order: SimulatedOrderSpec,
    *,
    fill_price: Decimal,
    filled_size: Decimal,
) -> Decimal:
    mark = order.reference_mid
    if mark is None:
        return Decimal("0")
    if order.side == "BUY":
        pnl = (mark - fill_price) * filled_size
    else:
        pnl = (fill_price - mark) * filled_size
    return pnl.quantize(Decimal("0.0001"))


def _pnl_difference(metrics: tuple[FillModelMetrics, ...]) -> Decimal | None:
    if len(metrics) < 2:
        return None
    pnls = tuple(metric.paper_pnl for metric in metrics)
    return (max(pnls) - min(pnls)).quantize(Decimal("0.0001"))


def _weighted_average_fill_price(fills: tuple[SimulatedFill, ...]) -> Decimal | None:
    total_size = sum((fill.filled_size for fill in fills), Decimal("0"))
    if total_size <= Decimal("0"):
        return None
    notional = sum(
        (
            (fill.fill_price or Decimal("0")) * fill.filled_size
            for fill in fills
        ),
        Decimal("0"),
    )
    return (notional / total_size).quantize(Decimal("0.0001"))


def _flatten_records(value: object) -> dict[str, Any]:
    if isinstance(value, list):
        return {"items": value}
    if isinstance(value, dict):
        return dict(value)
    raise FillSimulationAuditError("input root must be a JSON object or JSONL records")


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


def _side(value: str | None) -> OrderSide | None:
    if value == "BUY":
        return "BUY"
    if value == "SELL":
        return "SELL"
    return None


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
    return (sum(values, Decimal("0")) / Decimal(len(values))).quantize(
        Decimal("0.0001")
    )


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


def _model_summary(model: FillModelMetrics) -> dict[str, object]:
    payload = model.to_dict()
    payload.pop("fills", None)
    return payload


def _model_markdown(model: FillModelMetrics) -> str:
    return "\n".join(
        (
            f"### {model.model}",
            "",
            _table(_model_summary(model)),
        )
    )


def _model_html(model: FillModelMetrics) -> str:
    return (
        "<section>"
        f"<h2>{escape(model.model)}</h2>"
        f"{_html_table(_model_summary(model))}"
        "</section>"
    )


__all__ = [
    "FillModelMetrics",
    "FillModelName",
    "FillSimulationAuditConfig",
    "FillSimulationAuditError",
    "FillSimulationAuditReport",
    "SimulatedFill",
    "SimulatedOrderSpec",
    "build_fill_simulation_audit",
    "classify_fill_simulation",
    "extract_simulated_orders",
    "fill_simulation_filename",
    "load_fill_simulation_records",
    "normalize_fill_models",
    "normalize_fill_report_formats",
    "render_fill_simulation_audit",
    "render_fill_simulation_audit_html",
    "render_fill_simulation_audit_json",
    "render_fill_simulation_audit_markdown",
]
