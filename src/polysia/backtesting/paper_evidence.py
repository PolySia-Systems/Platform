"""Versioned recorded economics input for the generic Paper backtest CLI."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from polysia.domain.events import MarketDataEvent
from polysia.domain.market import MarketDetails, MarketFeeSchedule, MarketOutcomeSummary
from polysia.domain.market.settlement import verified_settlement_prices

PAPER_EVIDENCE_VERSION = "paper-backtest-evidence-v1"
MAX_EVIDENCE_BYTES = 1_000_000
MAX_FEE_SNAPSHOTS = 500


class PaperEvidenceError(ValueError):
    """Recorded evidence cannot support a causal Paper replay."""


@dataclass(frozen=True, slots=True)
class FeeSnapshot:
    token_id: str
    observed_at: datetime
    market: MarketDetails
    source_id: str


@dataclass(frozen=True, slots=True)
class PaperReplayEvidence:
    market_id: str
    token_ids: tuple[str, ...]
    cutoff_at: datetime
    fee_snapshots: tuple[FeeSnapshot, ...]
    terminal_market: MarketDetails | None
    terminal_observed_at: datetime | None

    def market_at(self, token_id: str, at: datetime) -> MarketDetails | None:
        causal = [
            snapshot
            for snapshot in self.fee_snapshots
            if snapshot.token_id == token_id and snapshot.observed_at < at.astimezone(UTC)
        ]
        return None if not causal else max(causal, key=lambda item: item.observed_at).market


def load_paper_replay_evidence(
    path: Path, events: Sequence[MarketDataEvent]
) -> PaperReplayEvidence:
    """Validate all identity and clock bindings before the first simulated order."""

    try:
        if path.stat().st_size > MAX_EVIDENCE_BYTES:
            raise PaperEvidenceError("paper evidence file exceeds the size limit")
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PaperEvidenceError("paper evidence file is unreadable or invalid JSON") from error
    root = _object(raw, "paper evidence")
    _fields(
        root,
        {"schema_version", "market_id", "token_ids", "cutoff_at", "fee_snapshots", "terminal"},
        "paper evidence",
    )
    if root["schema_version"] != PAPER_EVIDENCE_VERSION:
        raise PaperEvidenceError("unsupported paper evidence schema_version")
    market_id = _text(root["market_id"], "market_id")
    tokens_raw = root["token_ids"]
    if not isinstance(tokens_raw, list) or not tokens_raw:
        raise PaperEvidenceError("token_ids must be a non-empty list")
    token_ids = tuple(_text(token, "token_id") for token in tokens_raw)
    if len(set(token_ids)) != len(token_ids):
        raise PaperEvidenceError("token_ids are ambiguous")
    if not events:
        raise PaperEvidenceError("recorded fee evidence requires market events")
    cutoff_at = _time(root["cutoff_at"], "cutoff_at")
    event_times = tuple(_time(event.received_at, "market event clock") for event in events)
    if any(later < earlier for earlier, later in zip(event_times, event_times[1:], strict=False)):
        raise PaperEvidenceError("market events must be ordered by replay clock")
    if any(event.token_id not in token_ids for event in events):
        raise PaperEvidenceError("market event token_id does not match recorded evidence")
    if any(event_at > cutoff_at for event_at in event_times):
        raise PaperEvidenceError("market event is after the recorded cutoff")

    snapshots_raw = root["fee_snapshots"]
    if not isinstance(snapshots_raw, list) or not 0 < len(snapshots_raw) <= MAX_FEE_SNAPSHOTS:
        raise PaperEvidenceError("fee_snapshots must be a bounded non-empty list")
    snapshots: list[FeeSnapshot] = []
    identities: set[tuple[str, datetime]] = set()
    for item in snapshots_raw:
        row = _object(item, "fee snapshot")
        _fields(
            row,
            {"market_id", "token_id", "observed_at", "source_id", "fee_schedule"},
            "fee snapshot",
        )
        if row["market_id"] != market_id:
            raise PaperEvidenceError("fee snapshot market_id does not match")
        token_id = _text(row["token_id"], "fee snapshot token_id")
        if token_id not in token_ids:
            raise PaperEvidenceError("fee snapshot token_id does not match")
        observed_at = _time(row["observed_at"], "fee snapshot observed_at")
        if observed_at > cutoff_at:
            raise PaperEvidenceError("fee snapshot is after the recorded cutoff")
        identity = (token_id, observed_at)
        if identity in identities:
            raise PaperEvidenceError("fee snapshots are ambiguous at one token/time")
        identities.add(identity)
        snapshots.append(
            FeeSnapshot(
                token_id=token_id,
                observed_at=observed_at,
                market=MarketDetails(
                    id=market_id,
                    fee_schedule=_fee_schedule(row["fee_schedule"]),
                ),
                source_id=_text(row["source_id"], "fee snapshot source_id"),
            )
        )

    terminal_market: MarketDetails | None = None
    terminal_observed_at: datetime | None = None
    if root["terminal"] is not None:
        terminal = _object(root["terminal"], "terminal evidence")
        _fields(
            terminal,
            {"market_id", "observed_at", "source_id", "closed", "outcomes"},
            "terminal evidence",
        )
        if terminal["market_id"] != market_id:
            raise PaperEvidenceError("terminal market_id does not match")
        _text(terminal["source_id"], "terminal source_id")
        terminal_observed_at = _time(terminal["observed_at"], "terminal observed_at")
        if terminal_observed_at <= max(event_times) or terminal_observed_at > cutoff_at:
            raise PaperEvidenceError("terminal evidence is outside the replay interval")
        if terminal["closed"] is not True:
            raise PaperEvidenceError("terminal evidence is not closed")
        outcomes_raw = terminal["outcomes"]
        if not isinstance(outcomes_raw, list):
            raise PaperEvidenceError("terminal outcomes must be a list")
        outcomes: list[MarketOutcomeSummary] = []
        for item in outcomes_raw:
            outcome = _object(item, "terminal outcome")
            _fields(outcome, {"token_id", "label", "price"}, "terminal outcome")
            outcomes.append(
                MarketOutcomeSummary(
                    token_id=_text(outcome["token_id"], "terminal token_id"),
                    label=_text(outcome["label"], "terminal label"),
                    price=_decimal(outcome["price"], "terminal price"),
                )
            )
        terminal_market = MarketDetails(id=market_id, closed=True, outcomes=tuple(outcomes))
        if verified_settlement_prices(terminal_market) is None or {
            outcome.token_id for outcome in outcomes
        } != set(token_ids):
            raise PaperEvidenceError("terminal outcomes are ambiguous or mismatched")

    evidence = PaperReplayEvidence(
        market_id=market_id,
        token_ids=token_ids,
        cutoff_at=cutoff_at,
        fee_snapshots=tuple(snapshots),
        terminal_market=terminal_market,
        terminal_observed_at=terminal_observed_at,
    )
    if any(
        evidence.market_at(event.token_id, at) is None
        for event, at in zip(events, event_times, strict=True)
    ):
        raise PaperEvidenceError("recorded fee evidence is absent or future for a market event")
    return evidence


def _object(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise PaperEvidenceError(f"{name} must be an object")
    return value


def _fields(value: Mapping[str, Any], required: set[str], name: str) -> None:
    if set(value) != required:
        raise PaperEvidenceError(f"{name} fields are missing or unsupported")


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PaperEvidenceError(f"{name} must be a non-empty string")
    return value


def _time(value: object, name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise PaperEvidenceError(f"{name} is not an ISO timestamp") from error
    else:
        raise PaperEvidenceError(f"{name} is not an ISO timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PaperEvidenceError(f"{name} must include a UTC offset")
    return parsed.astimezone(UTC)


def _decimal(value: object, name: str) -> Decimal:
    if not isinstance(value, str):
        raise PaperEvidenceError(f"{name} must be a decimal string")
    try:
        result = Decimal(value)
    except InvalidOperation as error:
        raise PaperEvidenceError(f"{name} must be a decimal string") from error
    if not result.is_finite():
        raise PaperEvidenceError(f"{name} must be finite")
    return result


def _fee_schedule(value: object) -> MarketFeeSchedule:
    row = _object(value, "fee_schedule")
    enabled = row.get("enabled")
    if enabled is False and set(row) == {"enabled"}:
        return MarketFeeSchedule(enabled=False)
    if enabled is not True or set(row) != {"enabled", "rate", "exponent", "taker_only"}:
        raise PaperEvidenceError("fee_schedule is absent or ambiguous")
    rate = _decimal(row["rate"], "fee rate")
    exponent = _decimal(row["exponent"], "fee exponent")
    if rate < 0 or exponent < 0 or row["taker_only"] is not True:
        raise PaperEvidenceError("fee_schedule is not a verified taker schedule")
    return MarketFeeSchedule(enabled=True, rate=rate, exponent=exponent, taker_only=True)


__all__ = [
    "PAPER_EVIDENCE_VERSION",
    "PaperEvidenceError",
    "PaperReplayEvidence",
    "load_paper_replay_evidence",
]
