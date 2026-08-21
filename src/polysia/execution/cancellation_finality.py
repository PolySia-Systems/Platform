"""Bounded, durable, read-only finality after a cancellation boundary."""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol, cast

from polysia.application.ports.cancellation import (
    CancellationEvidencePort,
    CancellationResponse,
    OpenOrderEvidence,
    OrderDetailEvidence,
    OrderLookupStatus,
    OrderTradeEvidence,
)

Clock = Callable[[], datetime]
Sleeper = Callable[[float], Awaitable[None]]
CancellationMutation = Callable[[], Awaitable[CancellationResponse]]

_ACTIONABLE_TRADE_STATUSES = frozenset({"CONFIRMED"})
_NO_FILL_DETAIL_STATUSES = frozenset({"CANCELED", "CANCELED_MARKET_RESOLVED"})
_TERMINAL_OUTCOMES = frozenset({"CONFIRMED_NO_FILL", "FULL_FILL_DETECTED", "PARTIAL_FILL_DETECTED"})


class CancellationFinalityOutcome(StrEnum):
    """Explicit bounded outcomes for one cancellation operation."""

    CONFIRMED_NO_FILL = "CONFIRMED_NO_FILL"
    FULL_FILL_DETECTED = "FULL_FILL_DETECTED"
    PARTIAL_FILL_DETECTED = "PARTIAL_FILL_DETECTED"
    STILL_OPEN = "STILL_OPEN"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class CancellationTarget:
    """Expected order state recorded before finality observation begins."""

    order_id: str
    token_id: str
    side: str
    expected_size: Decimal
    matched_size_baseline: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if not self.order_id or not self.token_id:
            raise ValueError("cancellation target identifiers must be non-empty")
        if self.side not in {"BUY", "SELL"}:
            raise ValueError("cancellation target side must be BUY or SELL")
        if (
            not self.expected_size.is_finite()
            or not self.matched_size_baseline.is_finite()
            or self.expected_size <= 0
            or self.matched_size_baseline < 0
        ):
            raise ValueError("cancellation target sizes are invalid")


@dataclass(frozen=True, slots=True)
class CancellationFinalityConfig:
    """Bounded observation policy for deterministic finality."""

    maximum_observations: int = 4
    observation_interval_seconds: float = 1.0
    timeout_seconds: float = 15.0
    required_clean_observations: int = 2

    def __post_init__(self) -> None:
        if self.maximum_observations < 1:
            raise ValueError("maximum_observations must be positive")
        if self.observation_interval_seconds < 0 or self.timeout_seconds <= 0:
            raise ValueError("finality timing values are invalid")
        if not 1 < self.required_clean_observations <= self.maximum_observations:
            raise ValueError("finality requires at least two bounded clean observations")


@dataclass(frozen=True, slots=True)
class CancellationFinalityResult:
    """Terminal or fail-safe result with sanitized decision evidence."""

    operation_id: str
    outcome: CancellationFinalityOutcome
    observation_count: int
    reason: str
    fill_size: Decimal = Decimal("0")
    fill_price: Decimal = Decimal("0")


class CancellationCheckpointStore(Protocol):
    """Minimal durable checkpoint surface used by the finality gate."""

    def insert_if_absent(
        self,
        *,
        run_id: str,
        phase: str,
        client_order_id: str,
        venue_order_id: str | None,
        payload: Mapping[str, Any],
        persisted_at: datetime,
    ) -> bool: ...

    def get(self, *, run_id: str, phase: str) -> dict[str, object] | None: ...

    def upsert(
        self,
        *,
        run_id: str,
        phase: str,
        client_order_id: str,
        venue_order_id: str | None,
        payload: Mapping[str, Any],
        persisted_at: datetime,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class _ObservationDecision:
    kind: str
    reason: str
    payload: dict[str, object]
    fill_size: Decimal = Decimal("0")
    fill_price: Decimal = Decimal("0")


class CancellationFinalityGate:
    """Send at most one cancellation and establish finality with bounded reads."""

    def __init__(
        self,
        *,
        evidence_port: CancellationEvidencePort,
        checkpoints: CancellationCheckpointStore,
        run_id: str,
        clock: Clock,
        sleeper: Sleeper,
        config: CancellationFinalityConfig | None = None,
    ) -> None:
        self._evidence_port = evidence_port
        self._checkpoints = checkpoints
        self._run_id = run_id
        self._clock = clock
        self._sleeper = sleeper
        self._config = config or CancellationFinalityConfig()

    async def run(
        self,
        *,
        operation_id: str,
        targets: tuple[CancellationTarget, ...],
        position_baselines: Mapping[str, Decimal],
        mutation: CancellationMutation | None,
        account_wide: bool = False,
    ) -> CancellationFinalityResult:
        """Cross one durable mutation boundary, then use read-only observations."""

        self._validate_request(operation_id, targets, position_baselines)
        phase = f"cancellation_finality:{operation_id}"
        checkpoint = self._checkpoints.get(run_id=self._run_id, phase=phase)
        if checkpoint is not None:
            payload = _checkpoint_payload(checkpoint)
            _validate_restored_request(payload, targets, position_baselines, account_wide)
            restored = _terminal_result(operation_id, payload)
            if restored is not None:
                return restored
            may_send = False
        else:
            now = _aware(self._clock())
            payload = {
                "schema_version": 1,
                "operation_id": operation_id,
                "account_wide": account_wide,
                "order_ids": [target.order_id for target in targets],
                "targets": [
                    {
                        "expected_size": str(target.expected_size),
                        "matched_size_baseline": str(target.matched_size_baseline),
                        "order_id": target.order_id,
                        "side": target.side,
                        "token_id": target.token_id,
                    }
                    for target in targets
                ],
                "send_attempt_state": "MAY_SEND" if mutation is not None else "READ_ONLY",
                "outcome": None,
                "observation_attempts": [],
                "position_baselines": {
                    token_id: str(size) for token_id, size in position_baselines.items()
                },
                "started_at": now.isoformat(),
                "evidence_summary": {},
                "final_reason": None,
            }
            created = self._checkpoints.insert_if_absent(
                run_id=self._run_id,
                phase=phase,
                client_order_id=operation_id,
                venue_order_id=targets[0].order_id if len(targets) == 1 else None,
                payload=payload,
                persisted_at=now,
            )
            if not created:
                checkpoint = self._checkpoints.get(run_id=self._run_id, phase=phase)
                if checkpoint is None:
                    raise RuntimeError("cancellation boundary checkpoint disappeared")
                payload = _checkpoint_payload(checkpoint)
                may_send = False
            else:
                may_send = mutation is not None

        if may_send:
            boundary_at = _aware(self._clock())
            payload["send_attempt_state"] = "MAY_HAVE_BEEN_SENT"
            payload["mutation_boundary_at"] = boundary_at.isoformat()
            self._persist(phase, operation_id, targets, payload, boundary_at)
            try:
                response = await cast(CancellationMutation, mutation)()
                if not isinstance(response, CancellationResponse):
                    raise TypeError("cancellation mutation returned a non-canonical response")
            except Exception as error:
                payload["send_attempt_state"] = "SEND_FAILED_OR_UNKNOWN"
                payload["cancellation_error"] = _safe_error_summary(error)
            else:
                payload["send_attempt_state"] = "RESPONSE_RECEIVED"
                payload["response_received_at"] = _aware(self._clock()).isoformat()
                payload["cancellation_response"] = {
                    "canceled_order_ids": list(response.canceled_order_ids),
                    "not_canceled": {
                        order_id: _sanitize_reason(reason)
                        for order_id, reason in response.not_canceled.items()
                    },
                }
            self._persist(phase, operation_id, targets, payload, _aware(self._clock()))

        started_at = _aware(self._clock())
        deadline = started_at + timedelta(seconds=self._config.timeout_seconds)
        clean_observations = 0
        latest_kind = "UNKNOWN"
        latest_reason = "no complete observation was available"
        latest_fill_size = Decimal("0")
        latest_fill_price = Decimal("0")

        for attempt in range(1, self._config.maximum_observations + 1):
            observed_at = _aware(self._clock())
            if observed_at > deadline:
                latest_kind = "TIMEOUT"
                latest_reason = "bounded cancellation finality timeout elapsed"
                break
            decision = await self._observe(
                targets=targets,
                position_baselines=position_baselines,
                payload=payload,
                attempt=attempt,
                observed_at=observed_at,
                account_wide=account_wide,
            )
            attempts = cast(list[object], payload.setdefault("observation_attempts", []))
            attempts.append(decision.payload)
            latest_kind = decision.kind
            latest_reason = decision.reason
            latest_fill_size = decision.fill_size
            latest_fill_price = decision.fill_price
            payload["evidence_summary"] = decision.payload
            self._persist(phase, operation_id, targets, payload, _aware(self._clock()))

            if decision.kind in {"FULL_FILL", "PARTIAL_FILL"}:
                outcome = (
                    CancellationFinalityOutcome.FULL_FILL_DETECTED
                    if decision.kind == "FULL_FILL"
                    else CancellationFinalityOutcome.PARTIAL_FILL_DETECTED
                )
                return self._complete(
                    phase=phase,
                    operation_id=operation_id,
                    targets=targets,
                    payload=payload,
                    outcome=outcome,
                    reason=decision.reason,
                    fill_size=decision.fill_size,
                    fill_price=decision.fill_price,
                )
            if decision.kind == "CLEAN":
                clean_observations += 1
                if clean_observations >= self._config.required_clean_observations:
                    return self._complete(
                        phase=phase,
                        operation_id=operation_id,
                        targets=targets,
                        payload=payload,
                        outcome=CancellationFinalityOutcome.CONFIRMED_NO_FILL,
                        reason=(f"{clean_observations} consecutive complete clean observations"),
                    )
            else:
                clean_observations = 0

            if attempt < self._config.maximum_observations:
                await self._sleeper(self._config.observation_interval_seconds)

        outcome = (
            CancellationFinalityOutcome.STILL_OPEN
            if latest_kind == "OPEN"
            else CancellationFinalityOutcome.UNKNOWN
        )
        return self._complete(
            phase=phase,
            operation_id=operation_id,
            targets=targets,
            payload=payload,
            outcome=outcome,
            reason=latest_reason,
            fill_size=latest_fill_size,
            fill_price=latest_fill_price,
        )

    async def _observe(
        self,
        *,
        targets: tuple[CancellationTarget, ...],
        position_baselines: Mapping[str, Decimal],
        payload: Mapping[str, object],
        attempt: int,
        observed_at: datetime,
        account_wide: bool,
    ) -> _ObservationDecision:
        errors: list[dict[str, str]] = []
        open_orders: tuple[OpenOrderEvidence, ...] = ()
        details: dict[str, OrderDetailEvidence] = {}
        trades: dict[str, tuple[OrderTradeEvidence, ...]] = {}
        positions: dict[str, Decimal] = {}

        try:
            open_orders = await self._evidence_port.observe_open_orders(
                order_id=(
                    None if account_wide or len(targets) > 1 else targets[0].order_id
                )
            )
        except Exception as error:
            errors.append(_endpoint_error("open_orders", error))
        for target in targets:
            try:
                details[target.order_id] = await self._evidence_port.observe_order_detail(
                    order_id=target.order_id
                )
            except Exception as error:
                errors.append(_endpoint_error("order_detail", error, target.order_id))
            try:
                trades[target.order_id] = await self._evidence_port.observe_order_trades(
                    order_id=target.order_id,
                    token_id=target.token_id,
                )
            except Exception as error:
                errors.append(_endpoint_error("order_trades", error, target.order_id))
        for token_id in sorted(position_baselines):
            try:
                position = await self._evidence_port.observe_position_size(
                    token_id=token_id
                )
                if not position.is_finite() or position < 0:
                    raise ValueError("position evidence must be finite and non-negative")
                positions[token_id] = position
            except Exception as error:
                errors.append(_endpoint_error("position", error, token_id))

        target_ids = {target.order_id for target in targets}
        observed_open = tuple(
            sorted(
                order.order_id
                for order in open_orders
                if account_wide or order.order_id in target_ids
            )
        )
        detail_summary = {
            order_id: (
                {"lookup": detail.status.value}
                if detail.order is None
                else {
                    "lookup": detail.status.value,
                    "matched_size": str(detail.order.matched_size),
                    "status": detail.order.status,
                }
            )
            for order_id, detail in details.items()
        }
        trade_summary = {
            order_id: [
                {
                    "evidence_id": trade.evidence_id,
                    "price": str(trade.price),
                    "size": str(trade.size),
                    "status": trade.status,
                }
                for trade in order_trades
            ]
            for order_id, order_trades in trades.items()
        }
        observation_payload: dict[str, object] = {
            "attempt": attempt,
            "observed_at": observed_at.isoformat(),
            "open_order_ids": list(observed_open),
            "order_details": detail_summary,
            "order_trades": trade_summary,
            "positions": {token_id: str(size) for token_id, size in positions.items()},
            "errors": errors,
        }
        if errors:
            return _ObservationDecision(
                kind="UNKNOWN",
                reason="one or more required evidence reads failed",
                payload=observation_payload,
            )
        if account_wide and any(order.order_id not in target_ids for order in open_orders):
            return _ObservationDecision(
                kind="OPEN",
                reason="an additional account order appeared during emergency finality",
                payload=observation_payload,
            )
        contract_conflict = _order_contract_conflict(targets, open_orders, details)
        if contract_conflict is not None:
            return _ObservationDecision(
                kind="UNKNOWN",
                reason=contract_conflict,
                payload=observation_payload,
            )

        fill = _fill_decision(
            targets=targets,
            details=details,
            trades=trades,
            positions=positions,
            position_baselines=position_baselines,
            payload=observation_payload,
        )
        if fill is not None:
            if observed_open and fill.kind in {"FULL_FILL", "PARTIAL_FILL"}:
                return _ObservationDecision(
                    kind="OPEN",
                    reason="fill was detected while a target remainder remained open",
                    payload=observation_payload,
                )
            return fill
        if observed_open:
            return _ObservationDecision(
                kind="OPEN",
                reason="one or more target orders remain open",
                payload=observation_payload,
            )
        if not _cancellation_or_terminal_absence_proven(payload, targets, details):
            return _ObservationDecision(
                kind="UNKNOWN",
                reason="cancellation issuance or terminal absence is not proven",
                payload=observation_payload,
            )
        if not _details_support_no_fill(targets, details):
            return _ObservationDecision(
                kind="UNKNOWN",
                reason="order detail does not support a no-fill conclusion",
                payload=observation_payload,
            )
        if not _trades_support_no_fill(targets, trades):
            return _ObservationDecision(
                kind="UNKNOWN",
                reason="order-linked trades are pending or contradictory",
                payload=observation_payload,
            )
        if any(
            positions[token_id] != baseline for token_id, baseline in position_baselines.items()
        ):
            return _ObservationDecision(
                kind="UNKNOWN",
                reason="position evidence conflicts with the recorded baseline",
                payload=observation_payload,
            )
        return _ObservationDecision(
            kind="CLEAN",
            reason="complete observation supports no fill",
            payload=observation_payload,
        )

    def _complete(
        self,
        *,
        phase: str,
        operation_id: str,
        targets: tuple[CancellationTarget, ...],
        payload: dict[str, object],
        outcome: CancellationFinalityOutcome,
        reason: str,
        fill_size: Decimal = Decimal("0"),
        fill_price: Decimal = Decimal("0"),
    ) -> CancellationFinalityResult:
        now = _aware(self._clock())
        payload["outcome"] = outcome.value
        payload["completed_at"] = now.isoformat()
        payload["final_reason"] = reason
        payload["fill_size"] = str(fill_size)
        payload["fill_price"] = str(fill_price)
        self._persist(phase, operation_id, targets, payload, now)
        attempts = cast(list[object], payload.get("observation_attempts", []))
        return CancellationFinalityResult(
            operation_id=operation_id,
            outcome=outcome,
            observation_count=len(attempts),
            reason=reason,
            fill_size=fill_size,
            fill_price=fill_price,
        )

    def _persist(
        self,
        phase: str,
        operation_id: str,
        targets: tuple[CancellationTarget, ...],
        payload: Mapping[str, object],
        persisted_at: datetime,
    ) -> None:
        self._checkpoints.upsert(
            run_id=self._run_id,
            phase=phase,
            client_order_id=operation_id,
            venue_order_id=targets[0].order_id if len(targets) == 1 else None,
            payload=payload,
            persisted_at=persisted_at,
        )

    @staticmethod
    def _validate_request(
        operation_id: str,
        targets: tuple[CancellationTarget, ...],
        position_baselines: Mapping[str, Decimal],
    ) -> None:
        if not operation_id or not targets:
            raise ValueError("cancellation operation and targets are required")
        order_ids = [target.order_id for target in targets]
        if len(order_ids) != len(set(order_ids)):
            raise ValueError("cancellation target order identifiers must be unique")
        if {target.token_id for target in targets} != set(position_baselines):
            raise ValueError("every cancellation token requires one position baseline")
        if any(not size.is_finite() or size < 0 for size in position_baselines.values()):
            raise ValueError("position baselines cannot be negative")


def cancellation_operation_id(run_id: str, purpose: str, order_ids: tuple[str, ...]) -> str:
    """Return a deterministic sanitized identifier for restart-safe cancellation."""

    material = "\x1f".join((run_id, purpose, *sorted(order_ids))).encode()
    return f"cancel-{hashlib.sha256(material).hexdigest()[:24]}"


def _fill_decision(
    *,
    targets: tuple[CancellationTarget, ...],
    details: Mapping[str, OrderDetailEvidence],
    trades: Mapping[str, tuple[OrderTradeEvidence, ...]],
    positions: Mapping[str, Decimal],
    position_baselines: Mapping[str, Decimal],
    payload: dict[str, object],
) -> _ObservationDecision | None:
    expected_by_token: dict[str, Decimal] = {}
    side_by_token: dict[str, str] = {}
    actionable_by_token: dict[str, list[OrderTradeEvidence]] = {}
    pending_trade = False
    detail_delta_by_token: dict[str, Decimal] = {}
    for target in targets:
        expected_by_token[target.token_id] = (
            expected_by_token.get(target.token_id, Decimal("0")) + target.expected_size
        )
        prior_side = side_by_token.setdefault(target.token_id, target.side)
        if prior_side != target.side:
            return _ObservationDecision(
                kind="UNKNOWN",
                reason="opposing order sides share one cancellation token",
                payload=payload,
            )
        detail = details[target.order_id]
        if detail.order is not None:
            delta = detail.order.matched_size - target.matched_size_baseline
            if delta < 0:
                return _ObservationDecision(
                    kind="UNKNOWN",
                    reason="order detail regressed below its matched-size baseline",
                    payload=payload,
                )
            detail_delta_by_token[target.token_id] = (
                detail_delta_by_token.get(target.token_id, Decimal("0")) + delta
            )
        for trade in trades[target.order_id]:
            status = trade.status.upper()
            if status in _ACTIONABLE_TRADE_STATUSES:
                actionable_by_token.setdefault(target.token_id, []).append(trade)
            elif status != "FAILED":
                pending_trade = True

    total_fill = Decimal("0")
    total_notional = Decimal("0")
    total_expected = sum(expected_by_token.values(), Decimal("0"))
    movement_detected = False
    for token_id, expected in expected_by_token.items():
        baseline = position_baselines[token_id]
        current = positions[token_id]
        movement = current - baseline if side_by_token[token_id] == "BUY" else baseline - current
        if movement < 0 or movement > expected:
            return _ObservationDecision(
                kind="UNKNOWN",
                reason="position movement contradicts the cancellation target",
                payload=payload,
            )
        trade_items = actionable_by_token.get(token_id, [])
        trade_total = sum((trade.size for trade in trade_items), Decimal("0"))
        matched_baseline = sum(
            (target.matched_size_baseline for target in targets if target.token_id == token_id),
            Decimal("0"),
        )
        trade_delta = max(Decimal("0"), trade_total - matched_baseline)
        detail_delta = detail_delta_by_token.get(token_id, Decimal("0"))
        if movement == 0:
            if trade_delta > 0 or detail_delta > 0 or pending_trade:
                return _ObservationDecision(
                    kind="UNKNOWN",
                    reason="fill evidence is not corroborated by the current position",
                    payload=payload,
                )
            continue
        movement_detected = True
        if (
            pending_trade
            or trade_delta != movement
            or (detail_delta not in {Decimal("0"), movement})
        ):
            return _ObservationDecision(
                kind="UNKNOWN",
                reason="fill, trade, detail, and position evidence conflict",
                payload=payload,
            )
        total_fill += movement
        total_notional += sum((trade.size * trade.price for trade in trade_items), Decimal("0"))

    if not movement_detected:
        return None
    if total_fill <= 0 or total_notional <= 0:
        return _ObservationDecision(
            kind="UNKNOWN",
            reason="detected position movement lacks actionable fill-price evidence",
            payload=payload,
        )
    return _ObservationDecision(
        kind="FULL_FILL" if total_fill == total_expected else "PARTIAL_FILL",
        reason=(
            "full fill is corroborated by linked trades and position movement"
            if total_fill == total_expected
            else "partial fill is corroborated by linked trades and position movement"
        ),
        payload=payload,
        fill_size=total_fill,
        fill_price=total_notional / total_fill,
    )


def _order_contract_conflict(
    targets: tuple[CancellationTarget, ...],
    open_orders: tuple[OpenOrderEvidence, ...],
    details: Mapping[str, OrderDetailEvidence],
) -> str | None:
    targets_by_id = {target.order_id: target for target in targets}
    observed_ids = [order.order_id for order in open_orders if order.order_id in targets_by_id]
    if len(observed_ids) != len(set(observed_ids)):
        return "open-order evidence contains duplicate target identifiers"
    for order in open_orders:
        target = targets_by_id.get(order.order_id)
        if target is not None and not _order_matches_target(order, target):
            return "open-order identity or size evidence conflicts with the cancellation target"
    for order_id, detail in details.items():
        target = targets_by_id[order_id]
        if detail.order is not None and not _order_matches_target(detail.order, target):
            return "order-detail identity or size evidence conflicts with the cancellation target"
    return None


def _order_matches_target(order: OpenOrderEvidence, target: CancellationTarget) -> bool:
    return (
        order.order_id == target.order_id
        and order.token_id == target.token_id
        and order.side == target.side
        and order.original_size == target.expected_size + target.matched_size_baseline
    )


def _cancellation_or_terminal_absence_proven(
    payload: Mapping[str, object],
    targets: tuple[CancellationTarget, ...],
    details: Mapping[str, OrderDetailEvidence],
) -> bool:
    send_state = payload.get("send_attempt_state")
    if send_state in {"MAY_SEND", "MAY_HAVE_BEEN_SENT", "SEND_FAILED_OR_UNKNOWN"}:
        return False
    response = payload.get("cancellation_response")
    if isinstance(response, Mapping):
        canceled = response.get("canceled_order_ids")
        not_canceled = response.get("not_canceled")
        canceled_ids = {str(value) for value in canceled} if isinstance(canceled, list) else set()
        rejected_ids = set(not_canceled) if isinstance(not_canceled, Mapping) else set()
        target_ids = {target.order_id for target in targets}
        if target_ids & rejected_ids:
            return False
        if target_ids <= canceled_ids:
            return True
    return all(
        detail.status is OrderLookupStatus.NOT_FOUND
        or (detail.order is not None and detail.order.status in _NO_FILL_DETAIL_STATUSES)
        for detail in details.values()
    ) and len(details) == len(targets)


def _details_support_no_fill(
    targets: tuple[CancellationTarget, ...],
    details: Mapping[str, OrderDetailEvidence],
) -> bool:
    for target in targets:
        detail = details.get(target.order_id)
        if detail is None:
            return False
        if detail.status is OrderLookupStatus.NOT_FOUND:
            continue
        order = detail.order
        if (
            order is None
            or order.status not in _NO_FILL_DETAIL_STATUSES
            or order.matched_size != target.matched_size_baseline
        ):
            return False
    return True


def _trades_support_no_fill(
    targets: tuple[CancellationTarget, ...],
    trades: Mapping[str, tuple[OrderTradeEvidence, ...]],
) -> bool:
    for target in targets:
        actionable = sum(
            (
                trade.size
                for trade in trades.get(target.order_id, ())
                if trade.status.upper() in _ACTIONABLE_TRADE_STATUSES
            ),
            Decimal("0"),
        )
        if actionable != target.matched_size_baseline:
            return False
        if any(
            trade.status.upper() != "FAILED"
            and trade.status.upper() not in _ACTIONABLE_TRADE_STATUSES
            for trade in trades.get(target.order_id, ())
        ):
            return False
    return True


def _terminal_result(
    operation_id: str,
    payload: Mapping[str, object],
) -> CancellationFinalityResult | None:
    raw_outcome = payload.get("outcome")
    if not isinstance(raw_outcome, str) or raw_outcome not in _TERMINAL_OUTCOMES:
        return None
    attempts = payload.get("observation_attempts")
    return CancellationFinalityResult(
        operation_id=operation_id,
        outcome=CancellationFinalityOutcome(raw_outcome),
        observation_count=len(attempts) if isinstance(attempts, list) else 0,
        reason=str(payload.get("final_reason") or "restored terminal cancellation outcome"),
        fill_size=Decimal(str(payload.get("fill_size") or "0")),
        fill_price=Decimal(str(payload.get("fill_price") or "0")),
    )


def _checkpoint_payload(checkpoint: Mapping[str, object]) -> dict[str, object]:
    payload = checkpoint.get("payload")
    if not isinstance(payload, dict):
        raise RuntimeError("cancellation checkpoint payload is malformed")
    return cast(dict[str, object], payload)


def _validate_restored_request(
    payload: Mapping[str, object],
    targets: tuple[CancellationTarget, ...],
    position_baselines: Mapping[str, Decimal],
    account_wide: bool,
) -> None:
    expected_targets = [
        {
            "expected_size": str(target.expected_size),
            "matched_size_baseline": str(target.matched_size_baseline),
            "order_id": target.order_id,
            "side": target.side,
            "token_id": target.token_id,
        }
        for target in targets
    ]
    expected_baselines = {
        token_id: str(size) for token_id, size in position_baselines.items()
    }
    if (
        payload.get("targets") != expected_targets
        or payload.get("position_baselines") != expected_baselines
        or payload.get("account_wide") is not account_wide
    ):
        raise RuntimeError("restored cancellation request conflicts with durable evidence")


def _endpoint_error(endpoint: str, error: Exception, subject: str | None = None) -> dict[str, str]:
    result = {"endpoint": endpoint, "error_type": type(error).__name__}
    if subject is not None:
        result["subject"] = subject
    return result


def _safe_error_summary(error: Exception) -> dict[str, str]:
    return {"error_type": type(error).__name__}


def _sanitize_reason(value: object) -> str:
    text = " ".join(str(value).split())
    return text[:160] if text else "unspecified"


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [
    "CancellationFinalityConfig",
    "CancellationFinalityGate",
    "CancellationFinalityOutcome",
    "CancellationFinalityResult",
    "CancellationTarget",
    "cancellation_operation_id",
]
