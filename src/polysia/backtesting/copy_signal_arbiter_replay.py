from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from polysia.domain.copytrading.signal_arbiter import (
    ArbiterMode,
    AssessmentStatus,
    ClosedSignalOutcome,
    ConcentrationCause,
    ConcentrationEvent,
    ExecutableEvidence,
    FollowerExecutionOutcome,
    SignalArbiter,
    SignalArbiterConfig,
    SignalCandidate,
    SignalContext,
    summarize_follower_execution_quality,
)

_WALLET_FRAGMENT = re.compile(r"(?<![0-9a-fA-F])0x[a-fA-F0-9]{40}(?![0-9a-fA-F])")
_ZERO = Decimal("0")


class CopySignalReplayError(RuntimeError):
    """Raised when a sanitized chronological Replay dataset is invalid."""


@dataclass(frozen=True, slots=True)
class CopySignalReplayManifest:
    schema_version: str
    outcome_labeling_version: str
    evaluation_horizon_seconds: int
    generated_at: datetime

    def __post_init__(self) -> None:
        if self.schema_version != "1":
            raise ValueError("unsupported Copy Signal Replay schema version")
        if not self.outcome_labeling_version:
            raise ValueError("outcome_labeling_version must not be empty")
        if _WALLET_FRAGMENT.search(self.outcome_labeling_version):
            raise ValueError("outcome_labeling_version must not contain a wallet address")
        if self.evaluation_horizon_seconds <= 0:
            raise ValueError("evaluation_horizon_seconds must be positive")
        _require_utc("generated_at", self.generated_at)


@dataclass(frozen=True, slots=True)
class CopySignalReplayRecord:
    snapshot_id: str
    decision_at: datetime
    candidate: SignalCandidate
    wallet_outcome: ClosedSignalOutcome | None = None
    follower_outcome: FollowerExecutionOutcome | None = None
    late_signal_attributable: bool = False

    def __post_init__(self) -> None:
        if not self.snapshot_id:
            raise ValueError("snapshot_id must not be empty")
        _require_utc("decision_at", self.decision_at)
        if self.decision_at < self.candidate.observed_at:
            raise ValueError("decision_at must not precede observed_at")
        if self.wallet_outcome is not None:
            if self.wallet_outcome.leader_key != self.candidate.leader_key:
                raise ValueError("wallet outcome leader does not match its signal")
            if self.wallet_outcome.context != self.candidate.context:
                raise ValueError("wallet outcome context does not match its signal")
        if self.follower_outcome is not None:
            if self.follower_outcome.leader_key != self.candidate.leader_key:
                raise ValueError("follower outcome leader does not match its signal")
            if self.follower_outcome.context != self.candidate.context:
                raise ValueError("follower outcome context does not match its signal")


@dataclass(frozen=True, slots=True)
class CopySignalReplayDataset:
    manifest: CopySignalReplayManifest
    records: tuple[CopySignalReplayRecord, ...]

    def __post_init__(self) -> None:
        signal_ids: set[str] = set()
        for record in self.records:
            signal_id = record.candidate.signal_id
            if signal_id in signal_ids:
                raise ValueError("Replay signal identifiers must be unique")
            signal_ids.add(signal_id)
            if record.decision_at > self.manifest.generated_at:
                raise ValueError("Replay decisions must not postdate the frozen manifest")
            closures = (
                None if record.wallet_outcome is None else record.wallet_outcome.closed_at,
                None
                if record.follower_outcome is None
                else record.follower_outcome.closed_at,
            )
            if any(
                closed_at is not None and closed_at > self.manifest.generated_at
                for closed_at in closures
            ):
                raise ValueError("Replay outcomes must not postdate the frozen manifest")


@dataclass(frozen=True, slots=True)
class CopySignalReplayConfig:
    arbiter: SignalArbiterConfig = field(default_factory=SignalArbiterConfig)
    minimum_comparable_fills: int = 30
    confidence_multiplier: Decimal = Decimal("1.645")

    def __post_init__(self) -> None:
        if self.minimum_comparable_fills < 3:
            raise ValueError("minimum_comparable_fills must be at least three")
        if self.confidence_multiplier < _ZERO:
            raise ValueError("confidence_multiplier must not be negative")


@dataclass(frozen=True, slots=True)
class CopySignalModeResult:
    mode: ArbiterMode
    snapshot_count: int
    selected_count: int
    distinct_wallets: int
    concentration_hhi: Decimal | None
    stale_rejections: int
    unknown_evidence: int
    safety_rejections: int
    missed_eligible_signals: int
    known_fill_count: int
    unknown_fill_count: int
    fill_rate: Decimal | None
    net_pnl: Decimal | None
    maximum_drawdown: Decimal | None
    mean_selected_latency_ms: Decimal | None
    mean_selected_spread_cost: Decimal | None
    pnl_mean: Decimal | None
    pnl_confidence_low: Decimal | None
    pnl_confidence_high: Decimal | None
    pnl_window_means: tuple[Decimal, ...]
    pnl_stability: str
    decisions: tuple[dict[str, object], ...]
    selected_signals: tuple[str, ...]
    follower_execution_quality: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "concentration_hhi": _decimal_text(self.concentration_hhi),
            "decisions": list(self.decisions),
            "distinct_wallets": self.distinct_wallets,
            "fill_rate": _decimal_text(self.fill_rate),
            "follower_execution_quality": self.follower_execution_quality,
            "known_fill_count": self.known_fill_count,
            "maximum_drawdown": _decimal_text(self.maximum_drawdown),
            "mean_selected_latency_ms": _decimal_text(self.mean_selected_latency_ms),
            "mean_selected_spread_cost": _decimal_text(
                self.mean_selected_spread_cost
            ),
            "missed_eligible_signals": self.missed_eligible_signals,
            "mode": self.mode.value,
            "net_pnl": _decimal_text(self.net_pnl),
            "pnl_confidence_high": _decimal_text(self.pnl_confidence_high),
            "pnl_confidence_low": _decimal_text(self.pnl_confidence_low),
            "pnl_mean": _decimal_text(self.pnl_mean),
            "pnl_stability": self.pnl_stability,
            "pnl_window_means": [str(value) for value in self.pnl_window_means],
            "safety_rejections": self.safety_rejections,
            "selected_count": self.selected_count,
            "selected_signals": list(self.selected_signals),
            "snapshot_count": self.snapshot_count,
            "stale_rejections": self.stale_rejections,
            "unknown_evidence": self.unknown_evidence,
            "unknown_fill_count": self.unknown_fill_count,
        }


@dataclass(frozen=True, slots=True)
class CopySignalReplayResult:
    manifest: CopySignalReplayManifest
    modes: tuple[CopySignalModeResult, ...]
    conclusion: str
    conclusion_reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "conclusion": self.conclusion,
            "conclusion_reason": self.conclusion_reason,
            "manifest": {
                "evaluation_horizon_seconds": self.manifest.evaluation_horizon_seconds,
                "generated_at": self.manifest.generated_at.isoformat(),
                "outcome_labeling_version": self.manifest.outcome_labeling_version,
                "schema_version": self.manifest.schema_version,
            },
            "modes": [mode.to_dict() for mode in self.modes],
            "status": "ok",
        }


class CopySignalArbiterReplay:
    """Compare fixed policies without waiting, mutation, or future-data leakage."""

    def __init__(self, config: CopySignalReplayConfig | None = None) -> None:
        self._config = config or CopySignalReplayConfig()
        self._arbiter = SignalArbiter(self._config.arbiter)

    def run(self, dataset: CopySignalReplayDataset) -> CopySignalReplayResult:
        snapshots = _group_snapshots(dataset.records)
        modes = tuple(
            self._run_mode(dataset, snapshots=snapshots, mode=mode)
            for mode in (
                ArbiterMode.CURRENT,
                ArbiterMode.COOLDOWN_ONLY,
                ArbiterMode.FULL,
            )
        )
        conclusion, reason = self._conclusion(modes)
        return CopySignalReplayResult(
            manifest=dataset.manifest,
            modes=modes,
            conclusion=conclusion,
            conclusion_reason=reason,
        )

    def _run_mode(
        self,
        dataset: CopySignalReplayDataset,
        *,
        snapshots: tuple[tuple[datetime, str, tuple[CopySignalReplayRecord, ...]], ...],
        mode: ArbiterMode,
    ) -> CopySignalModeResult:
        all_wallet_outcomes = tuple(
            record.wallet_outcome
            for record in dataset.records
            if record.wallet_outcome is not None
        )
        used_leaders: set[str] = set()
        concentration_events: list[ConcentrationEvent] = []
        selected_records: list[CopySignalReplayRecord] = []
        selected_signals: list[str] = []
        selected_leaders: list[str] = []
        selected_follower_outcomes: list[FollowerExecutionOutcome] = []
        decisions: list[dict[str, object]] = []
        stale_rejections = 0
        unknown_evidence = 0
        safety_rejections = 0
        missed_eligible = 0
        latency_values: list[Decimal] = []
        spread_costs: list[Decimal] = []

        for decision_at, _snapshot_id, records in snapshots:
            available_outcomes = tuple(
                outcome for outcome in all_wallet_outcomes if outcome.closed_at <= decision_at
            )
            decision = self._arbiter.decide(
                tuple(record.candidate for record in records),
                mode=mode,
                as_of=decision_at,
                wallet_outcomes=available_outcomes,
                concentration_events=tuple(concentration_events),
                used_leaders=frozenset(used_leaders),
            )
            decisions.append(decision.to_dict())
            stale_rejections += sum(
                1
                for assessment in decision.assessments
                if assessment.status is AssessmentStatus.REJECTED
                and "freshness" in assessment.reason
            )
            unknown_evidence += sum(
                1
                for assessment in decision.assessments
                if assessment.status is AssessmentStatus.UNKNOWN
            )
            safety_rejections += sum(
                1
                for assessment in decision.assessments
                if assessment.status is AssessmentStatus.REJECTED
                and assessment.reason.startswith("safety rejected")
            )
            eligible_count = sum(
                1
                for assessment in decision.assessments
                if assessment.status is AssessmentStatus.ELIGIBLE
            )
            if decision.selected_signal_id is not None:
                missed_eligible += max(0, eligible_count - 1)
                selected = next(
                    record
                    for record in records
                    if record.candidate.signal_id == decision.selected_signal_id
                )
                selected_records.append(selected)
                selected_signals.append(selected.candidate.signal_id)
                selected_leaders.append(selected.candidate.leader_key)
                latency_values.append(
                    Decimal(
                        str(
                            (decision_at - selected.candidate.executed_at).total_seconds()
                            * 1_000
                        )
                    )
                )
                selected_assessment = next(
                    assessment
                    for assessment in decision.assessments
                    if assessment.signal_id == decision.selected_signal_id
                    and assessment.status is AssessmentStatus.ELIGIBLE
                )
                if selected_assessment.spread_cost is not None:
                    spread_costs.append(selected_assessment.spread_cost)
                if mode is ArbiterMode.CURRENT:
                    used_leaders.add(selected.candidate.leader_key)
                if selected.follower_outcome is not None:
                    selected_follower_outcomes.append(selected.follower_outcome)
                    if selected.follower_outcome.completed_cycle:
                        concentration_events.append(
                            ConcentrationEvent(
                                event_id=(
                                    f"{mode.value}:cycle:{selected.follower_outcome.execution_id}"
                                ),
                                leader_key=selected.candidate.leader_key,
                                cause=ConcentrationCause.COMPLETED_CYCLE,
                                occurred_at=selected.follower_outcome.closed_at,
                            )
                        )
            for record in records:
                if record.late_signal_attributable and (
                    decision_at - record.candidate.executed_at
                    > self._config.arbiter.maximum_signal_age
                ):
                    concentration_events.append(
                        ConcentrationEvent(
                            event_id=f"{mode.value}:late:{record.candidate.signal_id}",
                            leader_key=record.candidate.leader_key,
                            cause=ConcentrationCause.LATE_SIGNAL,
                            occurred_at=decision_at,
                        )
                    )

        counts = Counter(selected_leaders)
        concentration_hhi = _concentration_hhi(counts)
        known_fills = tuple(
            outcome
            for outcome in selected_follower_outcomes
            if outcome.filled
            and outcome.execution_cost is not None
            and outcome.slippage is not None
        )
        unknown_fill_count = sum(
            1
            for record in selected_records
            if record.follower_outcome is None
            or (
                record.follower_outcome.filled
                and (
                    record.follower_outcome.execution_cost is None
                    or record.follower_outcome.slippage is None
                )
            )
        )
        pnl_values = tuple(
            outcome.net_pnl for outcome in known_fills if outcome.net_pnl is not None
        )
        net_pnl = None if not pnl_values else sum(pnl_values, _ZERO)
        maximum_drawdown = _maximum_drawdown(pnl_values)
        mean, low, high = _confidence_interval(
            pnl_values,
            multiplier=self._config.confidence_multiplier,
        )
        window_means, stability = _pnl_stability(
            pnl_values,
            minimum=self._config.minimum_comparable_fills,
        )
        return CopySignalModeResult(
            mode=mode,
            snapshot_count=len(snapshots),
            selected_count=len(selected_records),
            distinct_wallets=len(counts),
            concentration_hhi=concentration_hhi,
            stale_rejections=stale_rejections,
            unknown_evidence=unknown_evidence,
            safety_rejections=safety_rejections,
            missed_eligible_signals=missed_eligible,
            known_fill_count=len(known_fills),
            unknown_fill_count=unknown_fill_count,
            fill_rate=(
                None
                if not selected_records
                else Decimal(len(known_fills)) / Decimal(len(selected_records))
            ),
            net_pnl=net_pnl,
            maximum_drawdown=maximum_drawdown,
            mean_selected_latency_ms=(
                None
                if not latency_values
                else sum(latency_values, _ZERO) / Decimal(len(latency_values))
            ),
            mean_selected_spread_cost=(
                None
                if not spread_costs
                else sum(spread_costs, _ZERO) / Decimal(len(spread_costs))
            ),
            pnl_mean=mean,
            pnl_confidence_low=low,
            pnl_confidence_high=high,
            pnl_window_means=window_means,
            pnl_stability=stability,
            decisions=tuple(decisions),
            selected_signals=tuple(selected_signals),
            follower_execution_quality=summarize_follower_execution_quality(
                tuple(selected_follower_outcomes),
                as_of=max(
                    (
                        *(decision_at for decision_at, _, _ in snapshots),
                        *(outcome.closed_at for outcome in selected_follower_outcomes),
                    ),
                    default=dataset.manifest.generated_at,
                ),
            ),
        )

    def _conclusion(
        self,
        modes: tuple[CopySignalModeResult, ...],
    ) -> tuple[str, str]:
        current = next(mode for mode in modes if mode.mode is ArbiterMode.CURRENT)
        full = next(mode for mode in modes if mode.mode is ArbiterMode.FULL)
        minimum = self._config.minimum_comparable_fills
        if (
            current.known_fill_count < minimum
            or full.known_fill_count < minimum
            or current.unknown_fill_count > 0
            or full.unknown_fill_count > 0
            or current.pnl_confidence_low is None
            or current.pnl_confidence_high is None
            or full.pnl_confidence_low is None
            or full.pnl_confidence_high is None
        ):
            return (
                "INCONCLUSIVE",
                "insufficient complete, comparable follower outcomes for the frozen gate",
            )
        if (
            full.pnl_confidence_low > current.pnl_confidence_high
            and _not_worse(full.maximum_drawdown, current.maximum_drawdown)
            and _not_worse(full.concentration_hhi, current.concentration_hhi)
            and current.pnl_stability == "CONSISTENT"
            and full.pnl_stability == "CONSISTENT"
        ):
            return "BETTER", "full Arbiter clears the conservative return and risk gates"
        if (
            full.pnl_confidence_high < current.pnl_confidence_low
            or not _not_worse(full.maximum_drawdown, current.maximum_drawdown)
        ):
            return "NOT BETTER", "full Arbiter fails the conservative return or risk gate"
        return (
            "INCONCLUSIVE",
            "confidence, stability, or concentration does not clear the frozen gate",
        )


def load_copy_signal_replay_jsonl(path: Path) -> CopySignalReplayDataset:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise CopySignalReplayError(f"could not read Replay input: {path}") from error
    payloads: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        if _WALLET_FRAGMENT.search(stripped):
            raise CopySignalReplayError(f"wallet-like value found on line {line_number}")
        try:
            value = json.loads(stripped)
        except json.JSONDecodeError as error:
            raise CopySignalReplayError(f"invalid JSON on line {line_number}") from error
        if not isinstance(value, dict):
            raise CopySignalReplayError(f"line {line_number} must be a JSON object")
        payloads.append(value)
    if not payloads or payloads[0].get("record_type") != "manifest":
        raise CopySignalReplayError("first Replay record must be a frozen manifest")
    manifest = _manifest_from_dict(payloads[0])
    records = tuple(_record_from_dict(payload) for payload in payloads[1:])
    return CopySignalReplayDataset(manifest=manifest, records=records)


def convert_tiny_live_events_to_unknown_replay(
    source: Path,
    target: Path,
    *,
    generated_at: datetime,
    market_type: str = "btc-updown",
    timeframe_seconds: int = 900,
) -> CopySignalReplayDataset:
    """Convert legacy sanitized OPEN events without inventing missing evidence.

    The old Tiny Live report does not contain decision-time order-book evidence or
    closed outcomes. The converted candidates therefore remain explicitly UNKNOWN.
    Events sharing one observed timestamp form one ready-now snapshot.
    """

    _require_utc("generated_at", generated_at)
    context = SignalContext(
        market_type=market_type,
        timeframe_seconds=timeframe_seconds,
    )
    try:
        lines = source.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise CopySignalReplayError(f"could not read Tiny Live events: {source}") from error

    payloads: list[dict[str, object]] = [
        {
            "record_type": "manifest",
            "schema_version": "1",
            "outcome_labeling_version": "legacy-no-outcomes-v1",
            "evaluation_horizon_seconds": timeframe_seconds,
            "generated_at": generated_at.isoformat(),
        }
    ]
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        if _WALLET_FRAGMENT.search(stripped):
            raise CopySignalReplayError(
                f"wallet-like value found in Tiny Live events on line {line_number}"
            )
        try:
            raw = json.loads(stripped)
        except json.JSONDecodeError as error:
            raise CopySignalReplayError(
                f"invalid Tiny Live JSON on line {line_number}"
            ) from error
        if not isinstance(raw, dict):
            raise CopySignalReplayError(
                f"Tiny Live line {line_number} must be a JSON object"
            )
        if raw.get("position_effect") != "OPEN" or raw.get("trade_action") != "BUY":
            continue
        event_id = _required_text(raw, "event_id")
        observed_at = _datetime(raw.get("observed_at"), "observed_at")
        executed_at = _datetime(raw.get("executed_at"), "executed_at")
        if executed_at > observed_at:
            raise CopySignalReplayError(
                f"Tiny Live event on line {line_number} executes after observation"
            )
        payloads.append(
            {
                "record_type": "signal",
                "snapshot_id": f"observed-{observed_at.isoformat()}",
                "signal_id": event_id,
                "leader_key": _required_text(raw, "leader_alias"),
                "context": {
                    "market_type": context.market_type,
                    "timeframe_seconds": context.timeframe_seconds,
                },
                "executed_at": executed_at.isoformat(),
                "observed_at": observed_at.isoformat(),
                "decision_at": observed_at.isoformat(),
                "safety_eligible": True,
                "safety_reason": (
                    "historical OPEN classification; executable evidence unavailable"
                ),
                "evidence": {
                    "leader_price": None,
                    "executable_price": None,
                    "quantity": None,
                    "best_bid": None,
                    "best_ask": None,
                    "expected_fees": None,
                    "estimated_slippage": None,
                    "captured_at": None,
                },
            }
        )

    if len(payloads) == 1:
        raise CopySignalReplayError("Tiny Live input contains no sanitized OPEN BUY events")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "\n".join(json.dumps(payload, sort_keys=True) for payload in payloads) + "\n",
        encoding="utf-8",
    )
    return load_copy_signal_replay_jsonl(target)


def write_copy_signal_replay_result(
    result: CopySignalReplayResult,
    path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _manifest_from_dict(data: Mapping[str, Any]) -> CopySignalReplayManifest:
    return CopySignalReplayManifest(
        schema_version=_required_text(data, "schema_version"),
        outcome_labeling_version=_required_text(data, "outcome_labeling_version"),
        evaluation_horizon_seconds=_required_int(data, "evaluation_horizon_seconds"),
        generated_at=_datetime(data.get("generated_at"), "generated_at"),
    )


def _record_from_dict(data: Mapping[str, Any]) -> CopySignalReplayRecord:
    if data.get("record_type") != "signal":
        raise CopySignalReplayError("non-manifest Replay records must have type 'signal'")
    context = _context(data.get("context"))
    candidate = SignalCandidate(
        signal_id=_required_text(data, "signal_id"),
        leader_key=_required_text(data, "leader_key"),
        context=context,
        executed_at=_datetime(data.get("executed_at"), "executed_at"),
        observed_at=_datetime(data.get("observed_at"), "observed_at"),
        safety_eligible=_required_bool(data, "safety_eligible"),
        safety_reason=_required_text(data, "safety_reason"),
        evidence=_evidence(data.get("evidence")),
    )
    return CopySignalReplayRecord(
        snapshot_id=_required_text(data, "snapshot_id"),
        decision_at=_datetime(data.get("decision_at"), "decision_at"),
        candidate=candidate,
        wallet_outcome=_wallet_outcome(data.get("wallet_outcome"), candidate=candidate),
        follower_outcome=_follower_outcome(
            data.get("follower_outcome"), candidate=candidate
        ),
        late_signal_attributable=bool(data.get("late_signal_attributable", False)),
    )


def _context(value: object) -> SignalContext:
    data = _mapping(value, "context")
    return SignalContext(
        market_type=_required_text(data, "market_type"),
        timeframe_seconds=_required_int(data, "timeframe_seconds"),
    )


def _evidence(value: object) -> ExecutableEvidence:
    data = _mapping(value, "evidence")
    return ExecutableEvidence(
        leader_price=_optional_decimal(data.get("leader_price")),
        executable_price=_optional_decimal(data.get("executable_price")),
        quantity=_optional_decimal(data.get("quantity")),
        best_bid=_optional_decimal(data.get("best_bid")),
        best_ask=_optional_decimal(data.get("best_ask")),
        expected_fees=_optional_decimal(data.get("expected_fees")),
        estimated_slippage=_optional_decimal(data.get("estimated_slippage")),
        captured_at=_optional_datetime(data.get("captured_at"), "captured_at"),
    )


def _wallet_outcome(
    value: object,
    *,
    candidate: SignalCandidate,
) -> ClosedSignalOutcome | None:
    if value is None:
        return None
    data = _mapping(value, "wallet_outcome")
    return ClosedSignalOutcome(
        outcome_id=_required_text(data, "outcome_id"),
        leader_key=candidate.leader_key,
        context=candidate.context,
        opened_at=candidate.executed_at,
        closed_at=_datetime(data.get("closed_at"), "wallet_outcome.closed_at"),
        net_return=_required_decimal(data, "net_return"),
        maximum_drawdown=_required_decimal(data, "maximum_drawdown"),
    )


def _follower_outcome(
    value: object,
    *,
    candidate: SignalCandidate,
) -> FollowerExecutionOutcome | None:
    if value is None:
        return None
    data = _mapping(value, "follower_outcome")
    return FollowerExecutionOutcome(
        execution_id=_required_text(data, "execution_id"),
        leader_key=candidate.leader_key,
        context=candidate.context,
        closed_at=_datetime(data.get("closed_at"), "follower_outcome.closed_at"),
        filled=_required_bool(data, "filled"),
        net_pnl=_optional_decimal(data.get("net_pnl")),
        execution_cost=_optional_decimal(data.get("execution_cost")),
        slippage=_optional_decimal(data.get("slippage")),
        completed_cycle=_optional_bool(data, "completed_cycle", default=False),
    )


def _group_snapshots(
    records: Iterable[CopySignalReplayRecord],
) -> tuple[tuple[datetime, str, tuple[CopySignalReplayRecord, ...]], ...]:
    grouped: dict[tuple[datetime, str], list[CopySignalReplayRecord]] = {}
    for record in records:
        grouped.setdefault((record.decision_at, record.snapshot_id), []).append(record)
    return tuple(
        (
            decision_at,
            snapshot_id,
            tuple(
                sorted(
                    grouped[(decision_at, snapshot_id)],
                    key=lambda record: (
                        record.candidate.executed_at,
                        record.candidate.leader_key,
                        record.candidate.signal_id,
                    ),
                )
            ),
        )
        for decision_at, snapshot_id in sorted(grouped)
    )


def _concentration_hhi(counts: Counter[str]) -> Decimal | None:
    total = sum(counts.values())
    if total == 0:
        return None
    denominator = Decimal(total)
    return sum(
        ((Decimal(count) / denominator) ** 2 for count in counts.values()),
        _ZERO,
    )


def _maximum_drawdown(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    equity = _ZERO
    peak = _ZERO
    drawdown = _ZERO
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return drawdown


def _confidence_interval(
    values: tuple[Decimal, ...],
    *,
    multiplier: Decimal,
) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    if not values:
        return None, None, None
    mean = sum(values, _ZERO) / Decimal(len(values))
    if len(values) == 1:
        return mean, None, None
    variance = sum(((value - mean) ** 2 for value in values), _ZERO) / Decimal(
        len(values) - 1
    )
    standard_error = (variance / Decimal(len(values))).sqrt()
    margin = multiplier * standard_error
    return mean, mean - margin, mean + margin


def _pnl_stability(
    values: tuple[Decimal, ...],
    *,
    minimum: int,
) -> tuple[tuple[Decimal, ...], str]:
    if len(values) < minimum:
        return (), "UNKNOWN"
    window_means = tuple(
        sum(values[index * len(values) // 3 : (index + 1) * len(values) // 3], _ZERO)
        / Decimal((index + 1) * len(values) // 3 - index * len(values) // 3)
        for index in range(3)
    )
    overall = sum(values, _ZERO) / Decimal(len(values))
    if overall > _ZERO and all(value > _ZERO for value in window_means):
        return window_means, "CONSISTENT"
    if overall < _ZERO and all(value < _ZERO for value in window_means):
        return window_means, "CONSISTENT"
    if overall == _ZERO and all(value == _ZERO for value in window_means):
        return window_means, "CONSISTENT"
    return window_means, "UNSTABLE"


def _not_worse(candidate: Decimal | None, baseline: Decimal | None) -> bool:
    return candidate is not None and baseline is not None and candidate <= baseline


def _decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise CopySignalReplayError(f"{name} must be an object")
    return value


def _required_text(data: Mapping[str, Any], name: str) -> str:
    value = data.get(name)
    if not isinstance(value, str) or not value:
        raise CopySignalReplayError(f"{name} must be a non-empty string")
    return value


def _required_int(data: Mapping[str, Any], name: str) -> int:
    value = data.get(name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise CopySignalReplayError(f"{name} must be an integer")
    return value


def _required_bool(data: Mapping[str, Any], name: str) -> bool:
    value = data.get(name)
    if not isinstance(value, bool):
        raise CopySignalReplayError(f"{name} must be a boolean")
    return value


def _optional_bool(data: Mapping[str, Any], name: str, *, default: bool) -> bool:
    value = data.get(name, default)
    if not isinstance(value, bool):
        raise CopySignalReplayError(f"{name} must be a boolean")
    return value


def _required_decimal(data: Mapping[str, Any], name: str) -> Decimal:
    value = _optional_decimal(data.get(name))
    if value is None:
        raise CopySignalReplayError(f"{name} must be a decimal value")
    return value


def _optional_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise CopySignalReplayError("boolean is not a decimal value")
    try:
        return Decimal(str(value))
    except Exception as error:
        raise CopySignalReplayError("invalid decimal value") from error


def _datetime(value: object, name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise CopySignalReplayError(f"{name} must be an ISO datetime")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise CopySignalReplayError(f"{name} is not a valid datetime") from error
    _require_utc(name, parsed)
    return parsed


def _optional_datetime(value: object, name: str) -> datetime | None:
    return None if value is None else _datetime(value, name)


def _require_utc(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError(f"{name} must be timezone-aware UTC")


__all__ = [
    "CopySignalArbiterReplay",
    "CopySignalModeResult",
    "CopySignalReplayConfig",
    "CopySignalReplayDataset",
    "CopySignalReplayError",
    "CopySignalReplayManifest",
    "CopySignalReplayRecord",
    "CopySignalReplayResult",
    "convert_tiny_live_events_to_unknown_replay",
    "load_copy_signal_replay_jsonl",
    "write_copy_signal_replay_result",
]
