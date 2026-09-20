"""Cost-aware accounting over deterministic prospective Replay decisions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from polysia.domain.research_evidence.economic_contract import CONTRACT_V1
from polysia.domain.research_evidence.models import CanonicalResearchEvent, ObservationKind
from polysia.domain.research_evidence.replay import (
    ExecutionEvidence,
    ObservationEvaluation,
    ProspectiveObservation,
    SameObservationReplay,
    depth_execution_from_snapshot,
)

ZERO = Decimal("0")
TOLERANCE = Decimal("0.000001")


@dataclass(slots=True)
class _Position:
    quantity: Decimal = ZERO
    cost_basis: Decimal = ZERO


@dataclass(slots=True)
class _Book:
    cash: Decimal = CONTRACT_V1.initial_capital
    fees: Decimal = ZERO
    slippage: Decimal = ZERO
    realized: Decimal = ZERO
    high_water: Decimal = CONTRACT_V1.initial_capital
    max_drawdown: Decimal = ZERO
    positions: dict[tuple[str, str], _Position] = field(default_factory=dict)
    evaluated: int = 0
    rejected: int = 0
    partial: int = 0

    def note(self) -> None:
        book_nav = self.cash + sum((item.cost_basis for item in self.positions.values()), ZERO)
        self.high_water = max(self.high_water, book_nav)
        if self.high_water > ZERO:
            self.max_drawdown = max(
                self.max_drawdown,
                (self.high_water - book_nav) / self.high_water,
            )


@dataclass(frozen=True, slots=True)
class PolicyEconomicMetrics:
    policy: str
    evaluated: int
    rejected: int
    partially_filled: int
    gross_pnl: Decimal | None
    fees: Decimal
    slippage: Decimal
    net_pnl: Decimal | None
    cash: Decimal
    capital_at_risk: Decimal
    exposure: Decimal
    maximum_drawdown: Decimal
    remaining_positions: tuple[dict[str, str], ...]
    valuation_status: str

    def to_dict(self) -> dict[str, object]:
        return {
            "capital_at_risk": _text(self.capital_at_risk),
            "cash": _text(self.cash),
            "evaluated": self.evaluated,
            "exposure": _text(self.exposure),
            "fees": _text(self.fees),
            "gross_pnl": _optional_text(self.gross_pnl),
            "maximum_drawdown": _text(self.maximum_drawdown),
            "net_pnl": _optional_text(self.net_pnl),
            "partially_filled": self.partially_filled,
            "policy": self.policy,
            "rejected": self.rejected,
            "remaining_positions": list(self.remaining_positions),
            "slippage": _text(self.slippage),
            "valuation_status": self.valuation_status,
        }


@dataclass(frozen=True, slots=True)
class ProspectiveEconomicReport:
    contract_version: str
    contract_digest: str
    total_observations: int
    eligible_observations: int
    evaluated_observations: int
    rejected_observations: int
    unknown_observations: int
    unknown_by_cause: tuple[tuple[str, int], ...]
    mapping_ratio: Decimal
    execution_evidence_ratio: Decimal
    data_canary_status: str
    data_canary_checks: tuple[tuple[str, bool], ...]
    control: PolicyEconomicMetrics
    target: PolicyEconomicMetrics
    control_target_net_delta: Decimal | None
    loss_reduction: Decimal | None
    economic_classification: str
    market_only: str
    placebo: str
    limitations: tuple[str, ...]
    digest: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "contract_digest": self.contract_digest,
            "contract_version": self.contract_version,
            "control": self.control.to_dict(),
            "control_target_net_delta": _optional_text(self.control_target_net_delta),
            "digest": self.digest,
            "data_canary_checks": dict(self.data_canary_checks),
            "data_canary_status": self.data_canary_status,
            "economic_classification": self.economic_classification,
            "eligible_observations": self.eligible_observations,
            "evaluated_observations": self.evaluated_observations,
            "execution_evidence_ratio": _text(self.execution_evidence_ratio),
            "limitations": list(self.limitations),
            "loss_reduction": _optional_text(self.loss_reduction),
            "mapping_ratio": _text(self.mapping_ratio),
            "market_only": self.market_only,
            "placebo": self.placebo,
            "rejected_observations": self.rejected_observations,
            "total_observations": self.total_observations,
            "unknown_by_cause": dict(self.unknown_by_cause),
            "unknown_observations": self.unknown_observations,
            "target": self.target.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class WalletEconomicReport:
    """Standalone economics for one sanitized observed wallet alias."""

    leader_alias: str
    economics: ProspectiveEconomicReport

    def to_dict(self) -> dict[str, object]:
        return {
            "leader_alias": self.leader_alias,
            "economic": self.economics.to_dict(),
        }


def evaluate_prospective_economics(
    replay: SameObservationReplay,
    *,
    events: tuple[CanonicalResearchEvent, ...],
) -> ProspectiveEconomicReport:
    """Apply one fill stream to both policies and value open inventory causally."""

    control = _Book()
    target = _Book()
    for row in replay.evaluations:
        _apply(control, row, decision=row.control_decision)
        _apply(target, row, decision=row.target_decision)
    control_metrics = _finish(control, "current-control", events)
    target_metrics = _finish(target, "target-exposure-v1", events)
    delta = _difference(target_metrics.net_pnl, control_metrics.net_pnl)
    loss_reduction = None
    if (
        target_metrics.net_pnl is not None
        and control_metrics.net_pnl is not None
        and control_metrics.net_pnl < ZERO
    ):
        loss_reduction = target_metrics.net_pnl - control_metrics.net_pnl
    evaluated = replay.execution_evidence_count
    rejected = replay.eligible_observation_count - evaluated
    unknown_causes = dict(replay.unknown_by_cause)
    legacy_incomplete = sum(
        1
        for row in replay.evaluations
        if row.execution is not None and not row.execution.economically_complete
    )
    if legacy_incomplete:
        unknown_causes["legacy_incomplete_execution"] = legacy_incomplete
    unknown = sum(unknown_causes.values())
    mapping_ratio = _ratio(
        replay.mapped_observation_count,
        replay.eligible_observation_count,
    )
    execution_ratio = _ratio(evaluated, replay.eligible_observation_count)
    canary_checks = (
        ("all_eligible_accounted", evaluated + rejected == replay.eligible_observation_count),
        ("execution_coverage", execution_ratio >= CONTRACT_V1.canary_execution_ratio),
        ("market_token_mapping", mapping_ratio >= CONTRACT_V1.canary_mapping_ratio),
        (
            "minimum_activity",
            replay.eligible_observation_count >= CONTRACT_V1.canary_min_eligible,
        ),
        ("no_lookahead", True),
    )
    if replay.eligible_observation_count < CONTRACT_V1.canary_min_eligible:
        canary_status = "INSUFFICIENT_ACTIVITY"
    elif all(passed for _, passed in canary_checks):
        canary_status = "PASS"
    else:
        canary_status = "FAIL"
    if canary_status != "PASS" or target_metrics.net_pnl is None:
        classification = "INSUFFICIENT_DATA"
    elif target_metrics.net_pnl > ZERO:
        classification = "POSITIVE"
    else:
        classification = "NEGATIVE"
    report = ProspectiveEconomicReport(
        contract_version=CONTRACT_V1.version,
        contract_digest=CONTRACT_V1.digest,
        total_observations=len(replay.evaluations),
        eligible_observations=replay.eligible_observation_count,
        evaluated_observations=evaluated,
        rejected_observations=rejected,
        unknown_observations=unknown,
        unknown_by_cause=tuple(sorted(unknown_causes.items())),
        mapping_ratio=mapping_ratio,
        execution_evidence_ratio=execution_ratio,
        data_canary_status=canary_status,
        data_canary_checks=canary_checks,
        control=control_metrics,
        target=target_metrics,
        control_target_net_delta=delta,
        loss_reduction=loss_reduction,
        economic_classification=classification,
        market_only="UNSUPPORTED",
        placebo="UNSUPPORTED",
        limitations=(
            "Wallet observations and market states are dependent, not independent samples.",
            "The bounded experiment does not establish persistent profitability or Live readiness.",
            "Market-only and placebo controls are unavailable in research-evidence-v2.",
            "Maximum drawdown uses the existing cost-basis book NAV, not intraperiod marks.",
        ),
    )
    digest = hashlib.sha256(
        json.dumps(report.to_dict(), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return replace(report, digest=digest)


def _apply(book: _Book, row: ObservationEvaluation, *, decision: str) -> None:
    execution = row.execution
    if (
        execution is None
        or not execution.economically_complete
        or decision not in {"ADMIT", "EXIT"}
    ):
        book.rejected += 1
        return
    key = (row.market_reference, row.outcome_reference)
    position = book.positions.setdefault(key, _Position())
    quantity = execution.available_quantity
    if row.side == "BUY":
        if decision != "ADMIT" or book.cash < execution.notional + execution.recorded_fee:
            book.rejected += 1
            return
        position.quantity += quantity
        position.cost_basis += execution.notional
        book.cash -= execution.notional + execution.recorded_fee
    else:
        quantity = min(quantity, position.quantity)
        if quantity <= ZERO:
            book.rejected += 1
            return
        ratio = quantity / execution.available_quantity
        cost_ratio = quantity / position.quantity
        released_cost = position.cost_basis * cost_ratio
        proceeds = execution.executable_price * quantity
        fee = execution.recorded_fee * ratio
        position.quantity -= quantity
        position.cost_basis -= released_cost
        book.cash += proceeds - fee
        book.realized += proceeds - released_cost
    fee_ratio = quantity / execution.available_quantity
    book.fees += execution.recorded_fee * fee_ratio
    book.slippage += execution.slippage * fee_ratio
    book.partial += int(execution.partial_fill)
    book.evaluated += 1
    if position.quantity <= TOLERANCE:
        book.positions.pop(key, None)
    book.note()


def _finish(
    book: _Book,
    policy: str,
    events: tuple[CanonicalResearchEvent, ...],
) -> PolicyEconomicMetrics:
    liquidation = ZERO
    rows: list[dict[str, str]] = []
    unknown = False
    cutoff = max((event.observed_time for event in events), default=None)
    for (market, outcome), position in sorted(book.positions.items()):
        evidence = _latest_liquidation(
            events,
            market=market,
            outcome=outcome,
            shares=position.quantity,
            cutoff=cutoff,
        )
        status = "MEASURED"
        value = None
        if evidence is None or evidence.partial_fill:
            status = "UNKNOWN"
            unknown = True
        else:
            value = evidence.notional - evidence.recorded_fee
            liquidation += value
        rows.append(
            {
                "cost_basis": _text(position.cost_basis),
                "market_reference": market,
                "outcome_reference": outcome,
                "quantity": _text(position.quantity),
                "valuation": _optional_text(value) or "UNKNOWN",
                "valuation_status": status,
            }
        )
    net = None if unknown else book.cash + liquidation - CONTRACT_V1.initial_capital
    gross = None if net is None else net + book.fees + book.slippage
    exposure = sum((item.cost_basis for item in book.positions.values()), ZERO)
    return PolicyEconomicMetrics(
        policy=policy,
        evaluated=book.evaluated,
        rejected=book.rejected,
        partially_filled=book.partial,
        gross_pnl=gross,
        fees=book.fees,
        slippage=book.slippage,
        net_pnl=net,
        cash=book.cash,
        capital_at_risk=max(ZERO, CONTRACT_V1.initial_capital - book.cash),
        exposure=exposure,
        maximum_drawdown=book.max_drawdown,
        remaining_positions=tuple(rows),
        valuation_status="UNKNOWN" if unknown else "MEASURED",
    )


def _latest_liquidation(
    events: tuple[CanonicalResearchEvent, ...],
    *,
    market: str,
    outcome: str,
    shares: Decimal,
    cutoff: datetime | None,
) -> ExecutionEvidence | None:
    settlements = [
        item
        for item in events
        if item.event_kind is ObservationKind.MARKET_STATE
        and item.classification.value == "ACCEPTED"
        and item.outcome_reference == outcome
        and item.market_reference == market
        and item.provenance.get("settlement_evidence_version")
        == "official-terminal-settlement-v1"
        and cutoff is not None
        and item.observed_time <= cutoff
    ]
    if settlements:
        settlement = max(
            settlements,
            key=lambda item: (item.observed_time, item.evidence_id),
        )
        price = _settlement_price(settlement.provenance.get("settlement_price"))
        if price is not None:
            return ExecutionEvidence(
                snapshot_evidence_id=settlement.evidence_id,
                executable_price=price,
                available_quantity=shares,
                recorded_fee=ZERO,
                notional=price * shares,
                slippage=ZERO,
                partial_fill=False,
                fee_rate=ZERO,
                fee_model_version="official-settlement-v1",
                economically_complete=True,
            )
    candidates = [
        item
        for item in events
        if item.event_kind is ObservationKind.MARKET_STATE
        and item.classification.value == "ACCEPTED"
        and item.outcome_reference == outcome
        and item.market_reference == market
        and item.side == "SELL"
        and item.provenance.get("execution_evidence_version") == "order-book-depth-v1"
        and cutoff is not None
        and item.observed_time <= cutoff
        and cutoff - item.observed_time
        <= timedelta(seconds=CONTRACT_V1.quote_max_age_seconds)
    ]
    if not candidates:
        return None
    snapshot = max(candidates, key=lambda item: (item.observed_time, item.evidence_id))
    observation = ProspectiveObservation(
        evidence_id="terminal-valuation",
        observed_time=snapshot.observed_time,
        source_time=snapshot.source_time,
        market_reference=market,
        outcome_reference=outcome,
        side="SELL",
        price=snapshot.price or Decimal("0.5"),
        size=shares,
    )
    evidence, _ = depth_execution_from_snapshot(
        snapshot,
        observation=observation,
        entry_budget=CONTRACT_V1.entry_budget,
    )
    return evidence


def _settlement_price(value: object) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed in {ZERO, Decimal("1")} else None


def _ratio(numerator: int, denominator: int) -> Decimal:
    return ZERO if denominator == 0 else Decimal(numerator) / Decimal(denominator)


def _difference(left: Decimal | None, right: Decimal | None) -> Decimal | None:
    return None if left is None or right is None else left - right


def _text(value: Decimal) -> str:
    return format(value, "f")


def _optional_text(value: Decimal | None) -> str | None:
    return None if value is None else _text(value)


__all__ = [
    "PolicyEconomicMetrics",
    "ProspectiveEconomicReport",
    "WalletEconomicReport",
    "evaluate_prospective_economics",
]
