from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from polysia.config.settings import TradingMode
from polysia.risk.checks import RiskContext, RiskEvidenceKind


class LiveStateUnavailableError(RuntimeError):
    """Raised when a required Live safety value cannot be observed."""


class LiveStateStaleError(RuntimeError):
    """Raised when verified Live evidence is older than the freshness limit."""


@dataclass(frozen=True, slots=True)
class MeasuredDecimal:
    """A Decimal that distinguishes measured zero from unknown."""

    value: Decimal | None
    kind: RiskEvidenceKind
    observed_at: datetime | None = None

    @classmethod
    def verified(cls, value: Decimal, *, observed_at: datetime) -> MeasuredDecimal:
        return cls(value=value, kind=RiskEvidenceKind.VERIFIED, observed_at=observed_at)

    @classmethod
    def unknown(cls) -> MeasuredDecimal:
        return cls(value=None, kind=RiskEvidenceKind.UNKNOWN, observed_at=None)

    @classmethod
    def assumed(cls, value: Decimal) -> MeasuredDecimal:
        return cls(value=value, kind=RiskEvidenceKind.ASSUMED, observed_at=None)

    def require_verified(self, *, field: str) -> Decimal:
        if self.kind is not RiskEvidenceKind.VERIFIED or self.value is None:
            raise LiveStateUnavailableError(f"{field} is {self.kind.value}, not verified")
        return self.value


@dataclass(frozen=True, slots=True)
class MeasuredInt:
    """An integer that distinguishes measured zero from unknown."""

    value: int | None
    kind: RiskEvidenceKind
    observed_at: datetime | None = None

    @classmethod
    def verified(cls, value: int, *, observed_at: datetime) -> MeasuredInt:
        return cls(value=value, kind=RiskEvidenceKind.VERIFIED, observed_at=observed_at)

    def require_verified(self, *, field: str) -> int:
        if self.kind is not RiskEvidenceKind.VERIFIED or self.value is None:
            raise LiveStateUnavailableError(f"{field} is {self.kind.value}, not verified")
        return self.value


@dataclass(frozen=True, slots=True)
class VerifiedLiveRiskSnapshot:
    """Immutable evidence carrier for Live risk. Not an account-state subsystem."""

    current_position: MeasuredDecimal
    current_market_position: MeasuredDecimal
    daily_pnl: MeasuredDecimal
    open_order_count: MeasuredInt
    market_data_observed_at: datetime
    account_source_id: str
    observed_at: datetime

    def __post_init__(self) -> None:
        if not self.account_source_id.strip():
            raise LiveStateUnavailableError("account/source identity is unavailable")
        if self.observed_at.tzinfo is None or self.market_data_observed_at.tzinfo is None:
            raise LiveStateUnavailableError("verified live timestamps must be timezone-aware")
        for field, measured in (
            ("current_position", self.current_position),
            ("current_market_position", self.current_market_position),
            ("daily_pnl", self.daily_pnl),
        ):
            measured.require_verified(field=field)
        self.open_order_count.require_verified(field="open_order_count")

    def require_fresh(self, *, now: datetime, max_age_ms: int) -> None:
        ages = (
            _age_ms(self.observed_at, now),
            _age_ms(self.market_data_observed_at, now),
            _age_ms(self.current_position.observed_at, now),
            _age_ms(self.current_market_position.observed_at, now),
            _age_ms(self.daily_pnl.observed_at, now),
            _age_ms(self.open_order_count.observed_at, now),
        )
        age_ms = max(ages)
        if age_ms > max_age_ms:
            raise LiveStateStaleError(
                f"verified live state age {age_ms}ms exceeds max_stale_data_age_ms {max_age_ms}"
            )

    def to_risk_context(
        self,
        *,
        trading_mode: TradingMode,
        live_trading_enabled: bool,
        now: datetime,
        max_stale_data_age_ms: int,
        edge: Decimal | None = None,
    ) -> RiskContext:
        self.require_fresh(now=now, max_age_ms=max_stale_data_age_ms)
        return RiskContext(
            trading_mode=trading_mode,
            live_trading_enabled=live_trading_enabled,
            current_position=self.current_position.require_verified(field="current_position"),
            current_market_position=self.current_market_position.require_verified(
                field="current_market_position"
            ),
            daily_pnl=self.daily_pnl.require_verified(field="daily_pnl"),
            open_orders_count=self.open_order_count.require_verified(field="open_order_count"),
            market_data_age_ms=_age_ms(self.market_data_observed_at, now),
            edge=edge,
            evidence_kind=RiskEvidenceKind.VERIFIED,
            observed_at=self.observed_at,
            account_source_id=self.account_source_id,
            market_data_observed_at=self.market_data_observed_at,
        )


def _age_ms(observed_at: datetime | None, now: datetime) -> int:
    if observed_at is None:
        raise LiveStateUnavailableError("verified live observation time is missing")
    elapsed = now - observed_at
    return max(0, int(elapsed.total_seconds() * 1000))
